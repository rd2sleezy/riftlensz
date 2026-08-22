"""Frame acquisition for RP.1 — prefers existing R.10 capture + visual sampling."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from riftlens.domain.capture import CAPTURE_MANIFEST_NAME, CaptureManifest
from riftlens.perception.models import FrameCaptureMeta
from riftlens.visual.sampling import SampledFrame, resolve_clip_path, sample_clip

RgbImage = NDArray[np.uint8]


@dataclass(frozen=True)
class CapturedFrame:
    """One RGB frame with honest timing metadata."""

    pixels: RgbImage
    meta: FrameCaptureMeta


def load_rgb_image(path: Path) -> RgbImage:
    """Load a local PNG/JPEG as RGB uint8. Raises FileNotFoundError / ValueError."""
    import cv2

    if not path.is_file():
        raise FileNotFoundError(str(path))
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"failed to decode image: {path}")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return np.asarray(rgb, dtype=np.uint8)


def frame_from_pixels(
    pixels: RgbImage,
    *,
    requested_game_t_ms: int,
    actual_game_t_ms: int | None = None,
    source_t_ms: int | None = None,
    frame_id: str = "frame_0",
    provenance: str = "synthetic_or_direct_pixels",
    sync_uncertainty_ms: int | None = None,
) -> CapturedFrame:
    """Wrap an in-memory RGB frame. Timing error is explicit when actual differs."""
    if pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError("pixels must be HxWx3 RGB")
    height, width = int(pixels.shape[0]), int(pixels.shape[1])
    actual = requested_game_t_ms if actual_game_t_ms is None else actual_game_t_ms
    error = abs(int(actual) - int(requested_game_t_ms))
    return CapturedFrame(
        pixels=np.asarray(pixels, dtype=np.uint8),
        meta=FrameCaptureMeta(
            requested_game_t_ms=int(requested_game_t_ms),
            actual_game_t_ms=int(actual),
            source_t_ms=source_t_ms,
            frame_id=frame_id,
            width=width,
            height=height,
            timing_error_ms=error,
            provenance=provenance,
            sync_uncertainty_ms=sync_uncertainty_ms,
        ),
    )


def frame_from_image_path(
    path: Path,
    *,
    requested_game_t_ms: int,
    actual_game_t_ms: int | None = None,
    provenance: str | None = None,
) -> CapturedFrame:
    """Load a still image as a CapturedFrame."""
    pixels = load_rgb_image(path)
    return frame_from_pixels(
        pixels,
        requested_game_t_ms=requested_game_t_ms,
        actual_game_t_ms=actual_game_t_ms,
        frame_id=path.name,
        provenance=provenance or f"image:{path.name}",
    )


def load_capture_manifest(capture_dir: Path) -> CaptureManifest:
    """Load an R.10 CaptureManifest from a capture directory."""
    path = Path(capture_dir) / CAPTURE_MANIFEST_NAME
    if not path.is_file():
        raise FileNotFoundError(f"missing {CAPTURE_MANIFEST_NAME} in {capture_dir}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CaptureManifest.from_dict(payload)


def sample_capture_dir(
    capture_dir: Path,
    *,
    fps: float = 2.0,
    max_frames: int | None = None,
) -> tuple[SampledFrame, ...]:
    """Sample an existing R.10 capture using visual.sampling (no live replay seek)."""
    capture_dir = Path(capture_dir)
    manifest = load_capture_manifest(capture_dir)
    clip = resolve_clip_path(manifest, capture_dir)
    return sample_clip(clip, manifest=manifest, fps=fps, max_frames=max_frames)


def nearest_sampled_frame(
    frames: tuple[SampledFrame, ...] | list[SampledFrame],
    *,
    requested_game_t_ms: int,
) -> CapturedFrame:
    """Pick the sample closest to ``requested_game_t_ms``. Exposes timing error."""
    if not frames:
        raise ValueError("no sampled frames")
    best = min(frames, key=lambda item: abs(item.game_t_ms - requested_game_t_ms))
    return frame_from_pixels(
        best.pixels,
        requested_game_t_ms=requested_game_t_ms,
        actual_game_t_ms=best.game_t_ms,
        source_t_ms=best.source_t_ms,
        frame_id=f"sample_{best.index}",
        provenance="r10_capture_sample",
        sync_uncertainty_ms=None,
    )


def sequence_around(
    frames: tuple[SampledFrame, ...] | list[SampledFrame],
    *,
    requested_game_t_ms: int,
    pre_ms: int,
    post_ms: int,
) -> tuple[CapturedFrame, ...]:
    """Return sampled frames in [requested-pre, requested+post]."""
    start = max(0, int(requested_game_t_ms) - int(pre_ms))
    end = int(requested_game_t_ms) + int(post_ms)
    selected = [item for item in frames if start <= item.game_t_ms <= end]
    if not selected:
        return (nearest_sampled_frame(frames, requested_game_t_ms=requested_game_t_ms),)
    return tuple(
        frame_from_pixels(
            item.pixels,
            requested_game_t_ms=requested_game_t_ms,
            actual_game_t_ms=item.game_t_ms,
            source_t_ms=item.source_t_ms,
            frame_id=f"sample_{item.index}",
            provenance="r10_capture_sample",
        )
        for item in selected
    )
