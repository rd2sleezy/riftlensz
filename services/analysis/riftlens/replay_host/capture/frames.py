"""Turn recorder output into timestamped artifacts. Demux only — never computer vision."""

from __future__ import annotations

from pathlib import Path

from riftlens.domain.capture import (
    ARTIFACT_KIND_CLIP,
    ARTIFACT_KIND_IMAGE,
    CaptureArtifactSpec,
    artifact_filename,
    frame_game_times,
)
from riftlens.domain.clock_map import ClockMap
from riftlens.domain.ids import new_ulid
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.capture import artifact_store
from riftlens.replay_host.capture.artifact_store import (
    CLIP_FILENAME,
    IMAGE_SUFFIXES,
)


def collect_artifacts(
    *,
    output_path: Path,
    destination: Path,
    kind: str,
    clock: ClockMap,
    start_game_ms: int,
    end_game_ms: int,
    max_artifacts: int,
    fps: float,
) -> tuple[CaptureArtifactSpec, ...]:
    """Rename recorder output into ``destination`` with game timestamps in every filename."""
    produced = artifact_store.list_output_files(output_path)
    if not produced:
        raise ReplayError(
            ReplayErrorCode.CAPTURE_OUTPUT_MISSING,
            details={"reason": "no_recorder_output", "path": str(output_path)},
        )
    if kind == ARTIFACT_KIND_CLIP:
        return _clip_artifacts(
            produced,
            destination=destination,
            clock=clock,
            start_game_ms=start_game_ms,
            end_game_ms=end_game_ms,
        )
    images = tuple(item for item in produced if item.suffix.lower() in IMAGE_SUFFIXES)
    if not images:
        images = _extract_from_clips(
            produced,
            destination=destination,
            fps=fps,
            max_artifacts=max_artifacts,
        )
    if not images:
        raise ReplayError(
            ReplayErrorCode.CAPTURE_OUTPUT_EMPTY,
            details={"reason": "no_frames_written", "path": str(output_path)},
        )
    kept, discarded = _thin(images, max_artifacts)
    artifact_store.delete_files(discarded)
    return _image_artifacts(
        kept,
        destination=destination,
        clock=clock,
        start_game_ms=start_game_ms,
        end_game_ms=end_game_ms,
    )


def _clip_artifacts(
    produced: tuple[Path, ...],
    *,
    destination: Path,
    clock: ClockMap,
    start_game_ms: int,
    end_game_ms: int,
) -> tuple[CaptureArtifactSpec, ...]:
    largest = max(produced, key=artifact_store.file_size)
    if artifact_store.file_size(largest) <= 0:
        raise ReplayError(
            ReplayErrorCode.CAPTURE_OUTPUT_EMPTY,
            details={"reason": "empty_clip", "path": str(largest)},
        )
    artifact_store.delete_files(item for item in produced if item != largest)
    suffix = largest.suffix or Path(CLIP_FILENAME).suffix
    target = Path(destination) / f"clip_g{int(start_game_ms)}{suffix}"
    if largest.resolve() != target.resolve():
        largest = artifact_store.move_into(largest, target)
    return (
        CaptureArtifactSpec(
            id=new_ulid(),
            kind=ARTIFACT_KIND_CLIP,
            relative_path=largest.name,
            game_t_ms=int(start_game_ms),
            source_t_ms=clock.game_to_source(int(start_game_ms)),
            sha256=artifact_store.sha256_file(largest),
            bytes=artifact_store.file_size(largest),
            frame_index=0,
        ),
    )


def _image_artifacts(
    images: tuple[Path, ...],
    *,
    destination: Path,
    clock: ClockMap,
    start_game_ms: int,
    end_game_ms: int,
) -> tuple[CaptureArtifactSpec, ...]:
    times = frame_game_times(
        start_game_ms=start_game_ms, end_game_ms=end_game_ms, count=len(images)
    )
    specs: list[CaptureArtifactSpec] = []
    for index, (source, game_t_ms) in enumerate(zip(images, times, strict=True)):
        name = artifact_filename(
            frame_index=index, game_t_ms=game_t_ms, suffix=source.suffix.lower()
        )
        target = Path(destination) / name
        moved = source if source.resolve() == target.resolve() else artifact_store.move_into(
            source, target
        )
        size = artifact_store.file_size(moved)
        if size <= 0:
            continue
        specs.append(
            CaptureArtifactSpec(
                id=new_ulid(),
                kind=ARTIFACT_KIND_IMAGE,
                relative_path=moved.name,
                game_t_ms=game_t_ms,
                source_t_ms=clock.game_to_source(game_t_ms),
                sha256=artifact_store.sha256_file(moved),
                bytes=size,
                frame_index=index,
            )
        )
    if not specs:
        raise ReplayError(
            ReplayErrorCode.CAPTURE_OUTPUT_EMPTY,
            details={"reason": "all_frames_empty", "count": len(images)},
        )
    return tuple(specs)


def _thin(images: tuple[Path, ...], max_artifacts: int) -> tuple[tuple[Path, ...], list[Path]]:
    limit = max(1, int(max_artifacts))
    if len(images) <= limit:
        return images, []
    step = len(images) / float(limit)
    picked_indexes = {min(len(images) - 1, int(round(index * step))) for index in range(limit)}
    kept = tuple(item for pos, item in enumerate(images) if pos in picked_indexes)
    discarded = [item for pos, item in enumerate(images) if pos not in picked_indexes]
    return kept, discarded


def _extract_from_clips(
    produced: tuple[Path, ...],
    *,
    destination: Path,
    fps: float,
    max_artifacts: int,
) -> tuple[Path, ...]:
    """Demux a recorder clip into PNGs when only a clip was produced. Returns () on failure."""
    clips = [item for item in produced if item.suffix.lower() not in IMAGE_SUFFIXES]
    if not clips:
        return ()
    try:
        import av
    except ImportError:
        return ()
    source = max(clips, key=artifact_store.file_size)
    staging = Path(destination) / "extracted"
    staging.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    try:
        with av.open(str(source)) as container:
            stream = container.streams.video[0]
            time_base = float(stream.time_base or 0) or 0.0
            interval_s = 1.0 / max(fps, 0.01)
            next_at = 0.0
            for frame in container.decode(stream):
                if len(written) >= max(1, int(max_artifacts)):
                    break
                position = 0.0 if frame.pts is None else float(frame.pts) * time_base
                if written and position + 1e-6 < next_at:
                    continue
                target = staging / f"extract_{len(written):06d}.png"
                image = frame.to_image()  # type: ignore[no-untyped-call]
                image.save(str(target))
                written.append(target)
                next_at = position + interval_s
    except Exception:  # noqa: BLE001 - demux is best-effort; caller degrades to OUTPUT_EMPTY
        return tuple(sorted(written, key=lambda item: item.name))
    return tuple(sorted(written, key=lambda item: item.name))
