"""V.2 visual pipeline: hybrid detect → temporal confirm → V.1 tracker → R.11."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from riftlens.domain.capture import CAPTURE_MANIFEST_NAME, CaptureManifest
from riftlens.domain.ids import new_ulid
from riftlens.domain.observation import (
    KnowledgeState,
    ObservationSequence,
    SampleGap,
    camera_from_capture,
)
from riftlens.domain.timeline import GameStateTimeline
from riftlens.visual.correlate import CorrelationStatus, correlate_subject
from riftlens.visual.detect import ViewportCoverage, classify_viewport, detect_champion_like_bars
from riftlens.visual.detect_v2 import confirm_temporal, detect_sample_entities
from riftlens.visual.errors import ArtifactMissing, VisualSpikeError
from riftlens.visual.gst_align import align_gst
from riftlens.visual.metrics import TrackMetrics, measure_tracks
from riftlens.visual.sampling import (
    expected_sample_count,
    iter_gap_offsets,
    resolve_clip_path,
    sample_clip,
)
from riftlens.visual.track import (
    FrameDetections,
    candidates_from_bars,
    derive_timeline_events,
    finalize_tracks,
    track_candidates,
)
from riftlens.visual.v1_analyze import (
    DEFAULT_V1_SAMPLE_FPS,
    IdFactory,
    V1AnalysisResult,
    V1Timing,
    _camera_note,
    _observations,
    _peak_stable,
    _sequence_confidence,
)

V2_ANALYZER_ID = "riftlens.visual.v2.entity"
V2_ANALYZER_VERSION = "v2.0"
DEFAULT_V2_SAMPLE_FPS = DEFAULT_V1_SAMPLE_FPS


@dataclass(frozen=True)
class V2AnalysisResult(V1AnalysisResult):
    """V.2 research output. Same R.11 contract as V.1 plus detector metrics."""

    metrics: TrackMetrics | None = None
    raw_bar_detections: int = 0
    confirmed_detections: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["analyzer_id"] = V2_ANALYZER_ID
        payload["analyzer_version"] = V2_ANALYZER_VERSION
        payload["metrics"] = None if self.metrics is None else self.metrics.to_dict()
        payload["raw_bar_detections"] = self.raw_bar_detections
        payload["confirmed_detections"] = self.confirmed_detections
        payload["detector_source"] = "v2.hybrid"
        return payload


def analyze_capture_dir_v2(
    capture_dir: Path,
    *,
    fps: float = DEFAULT_V2_SAMPLE_FPS,
    max_frames: int | None = None,
    id_factory: IdFactory | None = None,
    gst: GameStateTimeline | None = None,
    subject_pid: int | None = None,
    subject_champion: str | None = None,
    capture_review_pid: int | None = None,
) -> V2AnalysisResult:
    """Load ``manifest.json`` from an R.10 capture directory and run V.2."""
    manifest_path = Path(capture_dir) / CAPTURE_MANIFEST_NAME
    if not manifest_path.is_file():
        raise ArtifactMissing(f"missing {CAPTURE_MANIFEST_NAME}")
    return analyze_manifest_v2(
        manifest_path,
        fps=fps,
        max_frames=max_frames,
        id_factory=id_factory,
        gst=gst,
        subject_pid=subject_pid,
        subject_champion=subject_champion,
        capture_review_pid=capture_review_pid,
    )


def analyze_manifest_v2(
    manifest_path: Path,
    *,
    fps: float = DEFAULT_V2_SAMPLE_FPS,
    max_frames: int | None = None,
    id_factory: IdFactory | None = None,
    gst: GameStateTimeline | None = None,
    subject_pid: int | None = None,
    subject_champion: str | None = None,
    capture_review_pid: int | None = None,
) -> V2AnalysisResult:
    """Analyze an R.10 clip with the V.2 detector and the V.1 tracker."""
    if fps <= 0:
        raise VisualSpikeError("fps must be > 0")
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    manifest = CaptureManifest.from_dict(payload)
    capture_dir = Path(manifest_path).parent
    clip_path = resolve_clip_path(manifest, capture_dir)
    make_id = id_factory or new_ulid
    total_started = time.perf_counter()
    started = time.perf_counter()
    samples = sample_clip(clip_path, manifest=manifest, fps=fps, max_frames=max_frames)
    extract_ms = (time.perf_counter() - started) * 1000.0
    detect_started = time.perf_counter()
    raw_frames = tuple(
        detect_sample_entities(sample.pixels, frame_index=sample.index, game_t_ms=sample.game_t_ms)
        for sample in samples
    )
    raw_bar_count = sum(len(item.candidates) for item in raw_frames)
    detections = confirm_temporal(raw_frames)
    confirmed_count = sum(len(item.candidates) for item in detections)
    detect_ms = (time.perf_counter() - detect_started) * 1000.0
    track_started = time.perf_counter()
    tracks = finalize_tracks(track_candidates(detections))
    events = derive_timeline_events(tracks)
    track_ms = (time.perf_counter() - track_started) * 1000.0
    align_started = time.perf_counter()
    camera = camera_from_capture(camera_controlled=manifest.camera_controlled)
    alignment = align_gst(
        gst,
        start_game_ms=int(manifest.requested_start_game_ms),
        end_game_ms=int(manifest.requested_end_game_ms),
        subject_pid=subject_pid,
        tracks=tracks,
    )
    correlation = correlate_subject(
        tracks,
        subject_pid=subject_pid,
        subject_champion=subject_champion,
        alignment=alignment,
        camera_control=camera.control,
        capture_review_pid=capture_review_pid,
    )
    align_ms = (time.perf_counter() - align_started) * 1000.0
    frames, inferred = _observations(
        samples,
        detections=detections,
        tracks=tracks,
        manifest=manifest,
        camera=camera,
        correlation=correlation,
        make_id=make_id,
    )
    informative = sum(1 for item in detections if item.coverage is ViewportCoverage.USEFUL)
    uninformative = len(detections) - informative
    interval_ms = int(round(1000.0 / fps))
    gaps = tuple(
        SampleGap(after_game_t_ms=after, gap_ms=gap, reason="sample_skip")
        for after, gap in iter_gap_offsets(samples, interval_ms=interval_ms)
    )
    duration_ms = max(
        0, int(manifest.requested_end_game_ms) - int(manifest.requested_start_game_ms)
    )
    expected = expected_sample_count(duration_ms=duration_ms, fps=fps)
    if max_frames is not None:
        expected = min(expected, max(1, int(max_frames)))
    clip = manifest.artifacts[0]
    sequence = ObservationSequence(
        sequence_id=make_id(),
        capture_interval_id=manifest.capture_id,
        media_artifact_id=clip.id,
        match_id=manifest.match_id,
        gameplay_source_id=manifest.source_id,
        start_game_ms=int(manifest.requested_start_game_ms),
        end_game_ms=int(manifest.requested_end_game_ms),
        frames=tuple(frames),
        detector_id=V2_ANALYZER_ID,
        detector_version=V2_ANALYZER_VERSION,
        sample_count=len(frames),
        expected_sample_count=expected,
        gaps=gaps,
        sampling_interval_ms=interval_ms,
        clock_map_id=manifest.clock_map_id,
        confidence=_sequence_confidence(frames, informative=informative),
        artifact_relative_path=clip.relative_path,
        artifact_sha256=clip.sha256,
    )
    total_ms = (time.perf_counter() - total_started) * 1000.0
    subject_visibility = (
        KnowledgeState.KNOWN
        if correlation.status is not CorrelationStatus.UNKNOWN and correlation.track_id
        else KnowledgeState.UNKNOWN
    )
    metrics = measure_tracks(tracks, sample_count=len(frames), interval_ms=interval_ms)
    return V2AnalysisResult(
        sequence=sequence,
        inferred_frames=tuple(inferred),
        tracks=tracks,
        events=events,
        correlation=correlation,
        alignment=alignment,
        sample_fps=fps,
        timing=V1Timing(
            extract_ms=extract_ms,
            detect_ms=detect_ms,
            track_ms=track_ms,
            align_ms=align_ms,
            total_ms=total_ms,
            decoded_frames=len(samples),
            analyzed_frames=len(frames),
        ),
        informative_frames=informative,
        uninformative_frames=uninformative,
        peak_stable_tracks=_peak_stable(detections, tracks),
        subject_visibility=subject_visibility,
        camera_note=_camera_note(camera, informative=informative, total=len(frames)),
        clip_duration_ms=duration_ms,
        metrics=metrics,
        raw_bar_detections=raw_bar_count,
        confirmed_detections=confirmed_count,
    )


def v1_baseline_detections(samples: Sequence[object]) -> tuple[FrameDetections, ...]:
    """V.1 per-frame bar detections for A/B metrics. Does not run V.2."""
    from riftlens.visual.sampling import SampledFrame

    out: list[FrameDetections] = []
    for sample in samples:
        if not isinstance(sample, SampledFrame):
            continue
        coverage = classify_viewport(sample.pixels)
        bars = (
            detect_champion_like_bars(sample.pixels)
            if coverage is ViewportCoverage.USEFUL
            else ()
        )
        out.append(
            FrameDetections(
                frame_index=sample.index,
                game_t_ms=sample.game_t_ms,
                candidates=candidates_from_bars(bars),
                coverage=coverage,
            )
        )
    return tuple(out)
