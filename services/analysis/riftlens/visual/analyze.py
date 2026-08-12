from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from riftlens.domain.capture import CAPTURE_MANIFEST_NAME, CaptureManifest
from riftlens.domain.ids import new_ulid
from riftlens.domain.observation import (
    CameraControl,
    CameraProvenance,
    CorrelationMethod,
    EntityObservation,
    FrameObservation,
    HudObservation,
    KnowledgeState,
    ObservationSequence,
    SampleGap,
    SpatialObservation,
    VisibilityState,
    VisualClaimKind,
    camera_from_capture,
)
from riftlens.visual.detect import (
    MAX_PLAUSIBLE_CHAMPIONS,
    DetectedBar,
    detect_champion_like_bars,
    viewport_is_informative,
)
from riftlens.visual.errors import ArtifactMissing, VisualSpikeError
from riftlens.visual.sampling import (
    SampledFrame,
    expected_sample_count,
    iter_gap_offsets,
    resolve_clip_path,
    sample_clip,
)

ANALYZER_ID = "riftlens.visual.v0.healthbar"
ANALYZER_VERSION = "v0.1"
DEFAULT_SAMPLE_FPS = 2.0
IdFactory = Callable[[], str]


@dataclass(frozen=True)
class VisualAnalysisResult:
    """V.0 spike output: R.11 sequence plus timing/coverage diagnostics."""

    sequence: ObservationSequence
    clip_duration_ms: int
    sample_fps: float
    extract_ms: float
    analyze_ms: float
    informative_frames: int
    uninformative_frames: int
    peak_entity_count: int
    entity_count_timeline: tuple[tuple[int, int], ...]
    subject_visibility: KnowledgeState
    subject_correlation: str
    camera_note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyzer_id": ANALYZER_ID,
            "analyzer_version": ANALYZER_VERSION,
            "clip_duration_ms": self.clip_duration_ms,
            "sample_fps": self.sample_fps,
            "extract_ms": round(self.extract_ms, 1),
            "analyze_ms": round(self.analyze_ms, 1),
            "informative_frames": self.informative_frames,
            "uninformative_frames": self.uninformative_frames,
            "peak_entity_count": self.peak_entity_count,
            "entity_count_timeline": [
                {"game_t_ms": t_ms, "count": count} for t_ms, count in self.entity_count_timeline
            ],
            "subject_visibility": self.subject_visibility.value,
            "subject_correlation": self.subject_correlation,
            "camera_note": self.camera_note,
            "sequence": self.sequence.to_dict(),
        }


def analyze_capture_dir(
    capture_dir: Path,
    *,
    fps: float = DEFAULT_SAMPLE_FPS,
    max_frames: int | None = None,
    id_factory: IdFactory | None = None,
) -> VisualAnalysisResult:
    """Load ``manifest.json`` from an R.10 capture directory and analyze the clip."""
    manifest_path = Path(capture_dir) / CAPTURE_MANIFEST_NAME
    if not manifest_path.is_file():
        raise ArtifactMissing(f"missing {CAPTURE_MANIFEST_NAME}")
    return analyze_manifest(
        manifest_path,
        fps=fps,
        max_frames=max_frames,
        id_factory=id_factory,
    )


def analyze_manifest(
    manifest_path: Path,
    *,
    fps: float = DEFAULT_SAMPLE_FPS,
    max_frames: int | None = None,
    id_factory: IdFactory | None = None,
) -> VisualAnalysisResult:
    """Analyze the R.10 clip described by ``manifest_path`` into an ObservationSequence."""
    if fps <= 0:
        raise VisualSpikeError("fps must be > 0")
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    manifest = CaptureManifest.from_dict(payload)
    capture_dir = Path(manifest_path).parent
    clip_path = resolve_clip_path(manifest, capture_dir)
    make_id = id_factory or new_ulid
    started = time.perf_counter()
    samples = sample_clip(clip_path, manifest=manifest, fps=fps, max_frames=max_frames)
    extract_ms = (time.perf_counter() - started) * 1000.0
    detect_started = time.perf_counter()
    camera = camera_from_capture(camera_controlled=manifest.camera_controlled)
    frames: list[FrameObservation] = []
    timeline: list[tuple[int, int]] = []
    informative = 0
    uninformative = 0
    clip = manifest.artifacts[0]
    for sample in samples:
        observation, count, useful = _observe_sample(
            sample,
            manifest=manifest,
            camera=camera,
            relative_path=clip.relative_path,
            sha256=clip.sha256,
            make_id=make_id,
        )
        frames.append(observation)
        timeline.append((sample.game_t_ms, count))
        if useful:
            informative += 1
        else:
            uninformative += 1
    analyze_ms = (time.perf_counter() - detect_started) * 1000.0
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
    sequence = ObservationSequence(
        sequence_id=make_id(),
        capture_interval_id=manifest.capture_id,
        media_artifact_id=clip.id,
        match_id=manifest.match_id,
        gameplay_source_id=manifest.source_id,
        start_game_ms=int(manifest.requested_start_game_ms),
        end_game_ms=int(manifest.requested_end_game_ms),
        frames=tuple(frames),
        detector_id=ANALYZER_ID,
        detector_version=ANALYZER_VERSION,
        sample_count=len(frames),
        expected_sample_count=expected,
        gaps=gaps,
        sampling_interval_ms=interval_ms,
        clock_map_id=manifest.clock_map_id,
        confidence=_sequence_confidence(frames, informative=informative),
        artifact_relative_path=clip.relative_path,
        artifact_sha256=clip.sha256,
    )
    return VisualAnalysisResult(
        sequence=sequence,
        clip_duration_ms=duration_ms,
        sample_fps=fps,
        extract_ms=extract_ms,
        analyze_ms=analyze_ms,
        informative_frames=informative,
        uninformative_frames=uninformative,
        peak_entity_count=max((count for _, count in timeline), default=0),
        entity_count_timeline=tuple(timeline),
        subject_visibility=KnowledgeState.UNKNOWN,
        subject_correlation=("unresolved: camera uncontrolled and V.0 does not identify champions"),
        camera_note=_camera_note(camera, informative=informative, total=len(frames)),
    )


def _observe_sample(
    sample: SampledFrame,
    *,
    manifest: CaptureManifest,
    camera: CameraProvenance,
    relative_path: str,
    sha256: str,
    make_id: IdFactory,
) -> tuple[FrameObservation, int, bool]:
    useful = viewport_is_informative(sample.pixels)
    bars = detect_champion_like_bars(sample.pixels) if useful else ()
    noisy = len(bars) > MAX_PLAUSIBLE_CHAMPIONS
    entities = () if noisy else tuple(_entity_from_bar(bar, make_id=make_id) for bar in bars)
    count = len(entities)
    frame_conf = 0.15 if noisy else _frame_confidence(bars, useful=useful)
    hud = HudObservation(hud_visible=KnowledgeState.UNKNOWN)
    spatial = SpatialObservation(
        knowledge=KnowledgeState.KNOWN if useful else KnowledgeState.UNOBSERVABLE,
        minimap_visible=KnowledgeState.UNKNOWN,
        labels=("champion_like_healthbar",) if count else (),
    )
    stamped_camera = CameraProvenance(
        control=camera.control,
        confidence=camera.confidence,
        target_participant_id=camera.target_participant_id,
        target_knowledge=camera.target_knowledge,
        viewport_width=sample.width,
        viewport_height=sample.height,
        mode=camera.mode,
    )
    observation = FrameObservation(
        observation_id=make_id(),
        match_id=manifest.match_id,
        gameplay_source_id=manifest.source_id,
        capture_interval_id=manifest.capture_id,
        media_artifact_id=manifest.artifacts[0].id,
        game_t_ms=sample.game_t_ms,
        clock_map_id=manifest.clock_map_id,
        observation_type="champion_like_healthbar",
        confidence=frame_conf,
        detector_id=ANALYZER_ID,
        detector_version=ANALYZER_VERSION,
        camera=stamped_camera,
        claim_kind=VisualClaimKind.OBSERVED,
        source_t_ms=sample.source_t_ms,
        artifact_relative_path=relative_path,
        artifact_sha256=sha256,
        entities=entities,
        hud=hud,
        spatial=spatial,
        payload={
            "sample_index": sample.index,
            "offset_ms": sample.offset_ms,
            "viewport_informative": useful,
            "champion_like_count": count,
            "raw_bar_count": len(bars),
            "detector_noisy": noisy,
            "count_knowledge": (
                KnowledgeState.UNKNOWN.value if noisy or not useful else KnowledgeState.KNOWN.value
            ),
            "ally_like_count": (None if noisy else sum(1 for bar in bars if bar.ally_like is True)),
            "enemy_like_count": (
                None if noisy else sum(1 for bar in bars if bar.ally_like is False)
            ),
        },
    )
    return observation, count, useful


def _entity_from_bar(bar: DetectedBar, *, make_id: IdFactory) -> EntityObservation:
    return EntityObservation(
        entity_observation_id=make_id(),
        visibility=VisibilityState.VISIBLE,
        confidence=bar.confidence,
        participant_id=None,
        champion_id=None,
        team=None,
        screen_region=bar.region,
        occluded=None,
        correlation_method=CorrelationMethod.NONE,
        identity_knowledge=KnowledgeState.UNKNOWN,
        participant_knowledge=KnowledgeState.UNKNOWN,
    )


def _frame_confidence(bars: tuple[DetectedBar, ...], *, useful: bool) -> float:
    if not useful:
        return 0.0
    if not bars:
        return 0.35
    return min(item.confidence for item in bars)


def _sequence_confidence(frames: list[FrameObservation], *, informative: int) -> float:
    if not frames:
        return 0.0
    ratio = informative / float(len(frames))
    mean = sum(item.confidence for item in frames) / float(len(frames))
    return round(min(mean, ratio), 3)


def _camera_note(camera: CameraProvenance, *, informative: int, total: int) -> str:
    if total <= 0:
        return "no sampled frames"
    if informative == 0:
        return "insufficient visual coverage: sampled frames lack gameplay texture"
    if camera.control is CameraControl.UNCONTROLLED:
        return (
            "camera uncontrolled; reviewed-player visibility cannot be inferred "
            "from capture ownership"
        )
    return f"camera control={camera.control.value}; subject target unresolved"
