from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from riftlens.domain.capture import CaptureArtifactSpec, CaptureManifest
from riftlens.visual.errors import ArtifactMissing, EmptyClip, MalformedVideo, VisualSpikeError

RgbImage = NDArray[np.uint8]


@dataclass(frozen=True)
class SampledFrame:
    """One deterministically sampled frame with GAME/SOURCE timestamp mapping."""

    index: int
    offset_ms: int
    game_t_ms: int
    source_t_ms: int | None
    width: int
    height: int
    pixels: RgbImage


def expected_sample_count(*, duration_ms: int, fps: float) -> int:
    """Return how many samples a closed interval of ``duration_ms`` should yield."""
    if fps <= 0:
        raise VisualSpikeError("fps must be > 0")
    if duration_ms < 0:
        raise VisualSpikeError("duration_ms must be >= 0")
    interval_ms = 1000.0 / fps
    return int(duration_ms / interval_ms) + 1


def game_time_for_offset(*, start_game_ms: int, offset_ms: int) -> int:
    """Map clip-relative offset onto canonical GAME milliseconds."""
    if start_game_ms < 0 or offset_ms < 0:
        raise VisualSpikeError("GAME/offset milliseconds must be >= 0")
    return int(start_game_ms) + int(offset_ms)


def source_time_for_offset(*, start_source_ms: int | None, offset_ms: int) -> int | None:
    """Map clip-relative offset onto SOURCE milliseconds when the capture recorded one."""
    if start_source_ms is None:
        return None
    if start_source_ms < 0 or offset_ms < 0:
        raise VisualSpikeError("SOURCE/offset milliseconds must be >= 0")
    return int(start_source_ms) + int(offset_ms)


def sample_times_ms(*, duration_ms: int, fps: float) -> tuple[int, ...]:
    """Return deterministic sample offsets including 0 and the last in-range tick."""
    count = expected_sample_count(duration_ms=duration_ms, fps=fps)
    interval_ms = 1000.0 / fps
    times = [int(round(index * interval_ms)) for index in range(count)]
    return tuple(min(duration_ms, t) for t in times)


def resolve_clip_path(manifest: CaptureManifest, capture_dir: Path) -> Path:
    """Return the on-disk clip for a complete R.10 manifest. Does not copy media."""
    if not manifest.artifacts:
        raise ArtifactMissing("manifest has no artifacts")
    clip = _primary_clip(manifest)
    path = Path(capture_dir) / clip.relative_path
    if not path.is_file():
        raise ArtifactMissing(f"media artifact missing: {clip.relative_path}")
    if path.stat().st_size <= 0:
        raise EmptyClip(f"media artifact is empty: {clip.relative_path}")
    return path


def sample_clip(
    path: Path,
    *,
    manifest: CaptureManifest,
    fps: float,
    max_frames: int | None = None,
) -> tuple[SampledFrame, ...]:
    """Decode ``path`` at ``fps`` and stamp each sample with GAME/SOURCE time.

    Sampling is nearest-forward: the first decoded frame at or after each
    target offset is kept. Gaps are left to the caller (missing targets).
    """
    if fps <= 0:
        raise VisualSpikeError("fps must be > 0")
    clip = _primary_clip(manifest)
    start_game = int(manifest.requested_start_game_ms)
    start_source = clip.source_t_ms if clip.source_t_ms is not None else manifest.start_source_ms
    duration_ms = max(0, int(manifest.requested_end_game_ms) - start_game)
    targets = list(sample_times_ms(duration_ms=duration_ms, fps=fps))
    if max_frames is not None:
        targets = targets[: max(1, int(max_frames))]
    frames: list[SampledFrame] = []
    target_index = 0
    try:
        import av
    except ImportError as exc:
        raise MalformedVideo("PyAV is required to sample R.10 clips") from exc
    try:
        container = av.open(str(path))
    except Exception as exc:
        raise MalformedVideo(f"cannot open video: {path.name}") from exc
    try:
        if not container.streams.video:
            raise EmptyClip("artifact has no video stream")
        stream = container.streams.video[0]
        time_base = float(stream.time_base or 0) or 0.0
        for decoded in container.decode(stream):
            if target_index >= len(targets):
                break
            position_ms = _frame_offset_ms(decoded, time_base)
            if position_ms + 1 < targets[target_index]:
                continue
            rgb = _to_rgb(decoded)
            while target_index < len(targets) and position_ms + 1 >= targets[target_index]:
                target_index += 1
            frames.append(
                SampledFrame(
                    index=len(frames),
                    offset_ms=position_ms,
                    game_t_ms=game_time_for_offset(start_game_ms=start_game, offset_ms=position_ms),
                    source_t_ms=source_time_for_offset(
                        start_source_ms=start_source, offset_ms=position_ms
                    ),
                    width=int(rgb.shape[1]),
                    height=int(rgb.shape[0]),
                    pixels=rgb,
                )
            )
    except (ArtifactMissing, EmptyClip, MalformedVideo, VisualSpikeError):
        raise
    except Exception as exc:
        raise MalformedVideo(f"cannot decode video: {path.name}") from exc
    finally:
        container.close()
    if not frames:
        raise EmptyClip("no frames could be sampled from the artifact")
    return tuple(frames)


def iter_gap_offsets(
    frames: tuple[SampledFrame, ...], *, interval_ms: int
) -> Iterator[tuple[int, int]]:
    """Yield ``(after_game_t_ms, gap_ms)`` when consecutive samples skip > 1.5 intervals."""
    if interval_ms <= 0 or len(frames) < 2:
        return
    threshold = int(interval_ms * 1.5)
    for previous, current in zip(frames, frames[1:], strict=False):
        delta = current.game_t_ms - previous.game_t_ms
        if delta > threshold:
            yield previous.game_t_ms, delta


def _primary_clip(manifest: CaptureManifest) -> CaptureArtifactSpec:
    clips = [item for item in manifest.artifacts if item.kind == "clip"]
    if clips:
        return clips[0]
    return manifest.artifacts[0]


def _frame_offset_ms(frame: object, time_base: float) -> int:
    pts = getattr(frame, "pts", None)
    if pts is None or time_base <= 0:
        return 0
    return int(round(float(pts) * time_base * 1000.0))


def _to_rgb(frame: object) -> RgbImage:
    to_ndarray = getattr(frame, "to_ndarray", None)
    if not callable(to_ndarray):
        raise MalformedVideo("decoded frame cannot convert to an array")
    ndarray = to_ndarray(format="rgb24")
    if not isinstance(ndarray, np.ndarray) or ndarray.ndim != 3:
        raise MalformedVideo("decoded frame is not an RGB array")
    return np.ascontiguousarray(ndarray, dtype=np.uint8)
