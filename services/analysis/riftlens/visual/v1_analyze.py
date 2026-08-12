"""V.1 visual pipeline: sample → detect → track → optional GST correlate → R.11."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
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
from riftlens.domain.timeline import GameStateTimeline
from riftlens.visual.correlate import CorrelationStatus, SubjectCorrelation, correlate_subject
from riftlens.visual.detect import (
    MAX_PLAUSIBLE_CHAMPIONS,
    ViewportCoverage,
    classify_viewport,
    detect_champion_like_bars,
)
from riftlens.visual.errors import ArtifactMissing, VisualSpikeError
from riftlens.visual.gst_align import GstAlignment, align_gst
from riftlens.visual.sampling import (
    SampledFrame,
    expected_sample_count,
    iter_gap_offsets,
    resolve_clip_path,
    sample_clip,
)
from riftlens.visual.track import (
    CandidateKind,
    EntityTrack,
    FrameDetections,
    TeamEstimate,
    TrackEvent,
    TrackLifecycle,
    candidates_from_bars,
    derive_timeline_events,
    finalize_tracks,
    fragmented_track_count,
    stable_track_count,
    track_candidates,
)

V1_ANALYZER_ID = "riftlens.visual.v1.tracker"
V1_ANALYZER_VERSION = "v1.0"
DEFAULT_V1_SAMPLE_FPS = 4.0
IdFactory = Callable[[], str]


@dataclass(frozen=True)
class V1Timing:
    extract_ms: float
    detect_ms: float
    track_ms: float
    align_ms: float
    total_ms: float
    decoded_frames: int
    analyzed_frames: int


@dataclass(frozen=True)
class V1AnalysisResult:
    """V.1 research output. Does not mutate findings or GST."""

    sequence: ObservationSequence
    inferred_frames: tuple[FrameObservation, ...]
    tracks: tuple[EntityTrack, ...]
    events: tuple[TrackEvent, ...]
    correlation: SubjectCorrelation
    alignment: GstAlignment
    sample_fps: float
    timing: V1Timing
    informative_frames: int
    uninformative_frames: int
    peak_stable_tracks: int
    subject_visibility: KnowledgeState
    camera_note: str
    clip_duration_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyzer_id": V1_ANALYZER_ID,
            "analyzer_version": V1_ANALYZER_VERSION,
            "sample_fps": self.sample_fps,
            "clip_duration_ms": self.clip_duration_ms,
            "timing": {
                "extract_ms": round(self.timing.extract_ms, 1),
                "detect_ms": round(self.timing.detect_ms, 1),
                "track_ms": round(self.timing.track_ms, 1),
                "align_ms": round(self.timing.align_ms, 1),
                "total_ms": round(self.timing.total_ms, 1),
                "decoded_frames": self.timing.decoded_frames,
                "analyzed_frames": self.timing.analyzed_frames,
            },
            "informative_frames": self.informative_frames,
            "uninformative_frames": self.uninformative_frames,
            "peak_stable_tracks": self.peak_stable_tracks,
            "stable_track_count": stable_track_count(self.tracks),
            "fragmented_track_count": fragmented_track_count(self.tracks),
            "candidate_observation_count": sum(item.observation_count for item in self.tracks),
            "subject_visibility": self.subject_visibility.value,
            "subject_correlation": {
                "status": self.correlation.status.value,
                "track_id": self.correlation.track_id,
                "participant_id": self.correlation.participant_id,
                "champion_id": self.correlation.champion_id,
                "confidence": self.correlation.confidence,
                "method": self.correlation.method,
                "claim_kind": self.correlation.claim_kind.value,
                "reasons": list(self.correlation.reasons),
                "conflicts": list(self.correlation.conflicts),
            },
            "camera_note": self.camera_note,
            "tracks": [_track_dict(item) for item in self.tracks],
            "events": [
                {
                    "track_id": item.track_id,
                    "game_t_ms": item.game_t_ms,
                    "kind": item.kind.value,
                }
                for item in self.events
            ],
            "gst_alignment": {
                "match_id": self.alignment.match_id,
                "mutated_gst": self.alignment.mutated_gst,
                "kills": [
                    {
                        "game_t_ms": item.game_t_ms,
                        "killer_id": item.killer_id,
                        "victim_id": item.victim_id,
                        "assist_ids": list(item.assist_ids),
                        "subject_role": item.subject_role,
                        "nearby_track_ids": list(item.nearby_track_ids),
                    }
                    for item in self.alignment.kills
                ],
                "subject_deaths": (
                    [] if self.alignment.subject is None else list(self.alignment.subject.deaths)
                ),
            },
            "inferred_frames": [item.to_dict() for item in self.inferred_frames],
            "sequence": self.sequence.to_dict(),
        }


def analyze_capture_dir_v1(
    capture_dir: Path,
    *,
    fps: float = DEFAULT_V1_SAMPLE_FPS,
    max_frames: int | None = None,
    id_factory: IdFactory | None = None,
    gst: GameStateTimeline | None = None,
    subject_pid: int | None = None,
    subject_champion: str | None = None,
    capture_review_pid: int | None = None,
) -> V1AnalysisResult:
    """Load ``manifest.json`` from an R.10 capture directory and run V.1."""
    manifest_path = Path(capture_dir) / CAPTURE_MANIFEST_NAME
    if not manifest_path.is_file():
        raise ArtifactMissing(f"missing {CAPTURE_MANIFEST_NAME}")
    return analyze_manifest_v1(
        manifest_path,
        fps=fps,
        max_frames=max_frames,
        id_factory=id_factory,
        gst=gst,
        subject_pid=subject_pid,
        subject_champion=subject_champion,
        capture_review_pid=capture_review_pid,
    )


def analyze_manifest_v1(
    manifest_path: Path,
    *,
    fps: float = DEFAULT_V1_SAMPLE_FPS,
    max_frames: int | None = None,
    id_factory: IdFactory | None = None,
    gst: GameStateTimeline | None = None,
    subject_pid: int | None = None,
    subject_champion: str | None = None,
    capture_review_pid: int | None = None,
) -> V1AnalysisResult:
    """Analyze an R.10 clip into tracked R.11 observations."""
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
    detections = _detect_frames(samples)
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
        detector_id=V1_ANALYZER_ID,
        detector_version=V1_ANALYZER_VERSION,
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
    return V1AnalysisResult(
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
    )


def _detect_frames(samples: Sequence[SampledFrame]) -> tuple[FrameDetections, ...]:
    out: list[FrameDetections] = []
    for sample in samples:
        coverage = classify_viewport(sample.pixels)
        bars = (
            detect_champion_like_bars(sample.pixels)
            if coverage is ViewportCoverage.USEFUL
            else ()
        )
        noisy = len(bars) > MAX_PLAUSIBLE_CHAMPIONS
        candidates = () if noisy else candidates_from_bars(bars)
        out.append(
            FrameDetections(
                frame_index=sample.index,
                game_t_ms=sample.game_t_ms,
                candidates=candidates,
                coverage=coverage,
            )
        )
    return tuple(out)


def _observations(
    samples: Sequence[SampledFrame],
    *,
    detections: Sequence[FrameDetections],
    tracks: Sequence[EntityTrack],
    manifest: CaptureManifest,
    camera: CameraProvenance,
    correlation: SubjectCorrelation,
    make_id: IdFactory,
) -> tuple[list[FrameObservation], list[FrameObservation]]:
    clip = manifest.artifacts[0]
    by_frame: dict[int, list[EntityTrack]] = {}
    for track in tracks:
        if track.kind is CandidateKind.NOISE:
            continue
        for observation in track.observations:
            by_frame.setdefault(observation.frame_index, []).append(track)
    frames: list[FrameObservation] = []
    for sample, detected in zip(samples, detections, strict=False):
        present = by_frame.get(sample.index, [])
        entities = tuple(
            _entity_for_track(track, frame_index=sample.index, make_id=make_id)
            for track in present
        )
        stamped = CameraProvenance(
            control=camera.control,
            confidence=camera.confidence,
            target_participant_id=camera.target_participant_id,
            target_knowledge=camera.target_knowledge,
            viewport_width=sample.width,
            viewport_height=sample.height,
            mode=camera.mode,
        )
        useful = detected.coverage is ViewportCoverage.USEFUL
        spatial = SpatialObservation(
            knowledge=KnowledgeState.KNOWN if useful else KnowledgeState.UNOBSERVABLE,
            minimap_visible=KnowledgeState.UNKNOWN,
            labels=("champion_like_track",) if entities else (),
        )
        frames.append(
            FrameObservation(
                observation_id=make_id(),
                match_id=manifest.match_id,
                gameplay_source_id=manifest.source_id,
                capture_interval_id=manifest.capture_id,
                media_artifact_id=clip.id,
                game_t_ms=sample.game_t_ms,
                clock_map_id=manifest.clock_map_id,
                observation_type="champion_like_track",
                confidence=_frame_confidence(detected, entities),
                detector_id=V1_ANALYZER_ID,
                detector_version=V1_ANALYZER_VERSION,
                camera=stamped,
                claim_kind=VisualClaimKind.OBSERVED,
                source_t_ms=sample.source_t_ms,
                artifact_relative_path=clip.relative_path,
                artifact_sha256=clip.sha256,
                entities=entities,
                hud=HudObservation(hud_visible=KnowledgeState.UNKNOWN),
                spatial=spatial,
                payload={
                    "sample_index": sample.index,
                    "offset_ms": sample.offset_ms,
                    "viewport_coverage": detected.coverage.value,
                    "viewport_informative": useful,
                    "raw_candidate_count": len(detected.candidates),
                    "stable_track_count": sum(
                        1
                        for track in present
                        if track.kind is CandidateKind.CHAMPION_LIKE and not track.ambiguous
                    ),
                    "tracks": [
                        {
                            "track_id": track.track_id,
                            "kind": track.kind.value,
                            "lifecycle": _lifecycle_at(track, sample.index).value,
                            "team_estimate": track.team_estimate.value,
                            "team_confidence": track.team_confidence,
                            "ambiguous": track.ambiguous,
                        }
                        for track in present
                    ],
                    "count_knowledge": (
                        KnowledgeState.KNOWN.value if useful else KnowledgeState.UNOBSERVABLE.value
                    ),
                },
            )
        )
    inferred: list[FrameObservation] = []
    if correlation.is_inferred and correlation.track_id is not None:
        matched = next((item for item in tracks if item.track_id == correlation.track_id), None)
        if matched is not None:
            inferred.append(
                _inferred_correlation_frame(
                    matched,
                    correlation=correlation,
                    manifest=manifest,
                    camera=camera,
                    make_id=make_id,
                    clip_id=clip.id,
                    relative_path=clip.relative_path,
                    sha256=clip.sha256,
                    width=samples[0].width if samples else None,
                    height=samples[0].height if samples else None,
                )
            )
    return frames, inferred


def _entity_for_track(
    track: EntityTrack,
    *,
    frame_index: int,
    make_id: IdFactory,
) -> EntityObservation:
    observation = next(item for item in track.observations if item.frame_index == frame_index)
    return EntityObservation(
        entity_observation_id=make_id(),
        visibility=VisibilityState.VISIBLE,
        confidence=observation.confidence,
        participant_id=None,
        champion_id=None,
        team=None,
        screen_region=observation.region,
        occluded=None,
        correlation_method=CorrelationMethod.NONE,
        identity_knowledge=KnowledgeState.UNKNOWN,
        participant_knowledge=KnowledgeState.UNKNOWN,
    )


def _inferred_correlation_frame(
    track: EntityTrack,
    *,
    correlation: SubjectCorrelation,
    manifest: CaptureManifest,
    camera: CameraProvenance,
    make_id: IdFactory,
    clip_id: str,
    relative_path: str,
    sha256: str,
    width: int | None,
    height: int | None,
) -> FrameObservation:
    last = track.observations[-1]
    entity = EntityObservation(
        entity_observation_id=make_id(),
        visibility=VisibilityState.VISIBLE,
        confidence=min(track.confidence, correlation.confidence),
        participant_id=correlation.participant_id,
        champion_id=correlation.champion_id,
        team=None,
        screen_region=last.region,
        occluded=None,
        correlation_method=CorrelationMethod.DETECTOR,
        identity_knowledge=(
            KnowledgeState.KNOWN if correlation.champion_id else KnowledgeState.UNKNOWN
        ),
        participant_knowledge=(
            KnowledgeState.KNOWN if correlation.participant_id else KnowledgeState.UNKNOWN
        ),
    )
    stamped = CameraProvenance(
        control=camera.control,
        confidence=camera.confidence,
        target_participant_id=camera.target_participant_id,
        target_knowledge=camera.target_knowledge,
        viewport_width=width,
        viewport_height=height,
        mode=camera.mode,
    )
    return FrameObservation(
        observation_id=make_id(),
        match_id=manifest.match_id,
        gameplay_source_id=manifest.source_id,
        capture_interval_id=manifest.capture_id,
        media_artifact_id=clip_id,
        game_t_ms=last.game_t_ms,
        clock_map_id=manifest.clock_map_id,
        observation_type="subject_track_correlation",
        confidence=correlation.confidence,
        detector_id=V1_ANALYZER_ID,
        detector_version=V1_ANALYZER_VERSION,
        camera=stamped,
        claim_kind=VisualClaimKind.INFERRED,
        source_t_ms=None,
        artifact_relative_path=relative_path,
        artifact_sha256=sha256,
        entities=(entity,),
        hud=HudObservation(hud_visible=KnowledgeState.UNKNOWN),
        spatial=SpatialObservation(
            knowledge=KnowledgeState.UNKNOWN,
            minimap_visible=KnowledgeState.UNKNOWN,
            labels=("subject_correlation",),
        ),
        payload={
            "track_id": track.track_id,
            "correlation_status": correlation.status.value,
            "correlation_method": correlation.method,
            "reasons": list(correlation.reasons),
            "conflicts": list(correlation.conflicts),
        },
    )


def _lifecycle_at(track: EntityTrack, frame_index: int) -> TrackLifecycle:
    for item in track.observations:
        if item.frame_index == frame_index:
            return item.lifecycle
    return TrackLifecycle.LOST_TRACK


def _frame_confidence(
    detected: FrameDetections, entities: tuple[EntityObservation, ...]
) -> float:
    if detected.coverage is not ViewportCoverage.USEFUL:
        return 0.0
    if not entities:
        return 0.35
    return min(item.confidence for item in entities)


def _sequence_confidence(frames: Sequence[FrameObservation], *, informative: int) -> float:
    if not frames:
        return 0.0
    ratio = informative / float(len(frames))
    mean = sum(item.confidence for item in frames) / float(len(frames))
    return round(min(mean, ratio), 3)


def _peak_stable(detections: Sequence[FrameDetections], tracks: Sequence[EntityTrack]) -> int:
    peak = 0
    for detected in detections:
        count = 0
        for track in tracks:
            if track.kind is not CandidateKind.CHAMPION_LIKE or track.ambiguous:
                continue
            if any(item.frame_index == detected.frame_index for item in track.observations):
                count += 1
        peak = max(peak, count)
    return peak


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


def _track_dict(track: EntityTrack) -> dict[str, Any]:
    return {
        "track_id": track.track_id,
        "first_seen_game_t_ms": track.first_seen_game_t_ms,
        "last_seen_game_t_ms": track.last_seen_game_t_ms,
        "observation_count": track.observation_count,
        "confidence": track.confidence,
        "kind": track.kind.value,
        "team_estimate": track.team_estimate.value,
        "team_confidence": track.team_confidence,
        "ambiguous": track.ambiguous,
        "fragmented": track.fragmented,
        "closed_reason": None if track.closed_reason is None else track.closed_reason.value,
        "events": [
            {"game_t_ms": item.game_t_ms, "kind": item.kind.value} for item in track.events
        ],
    }


def occupancy_from_tracks(
    tracks: Sequence[EntityTrack], game_t_ms: int
) -> tuple[int, int, int]:
    """Return (champion_like, ally_like, enemy_like) present at ``game_t_ms``."""
    present = [
        track
        for track in tracks
        if track.kind is CandidateKind.CHAMPION_LIKE
        and track.first_seen_game_t_ms <= game_t_ms <= track.last_seen_game_t_ms
        and not track.ambiguous
    ]
    ally = sum(1 for item in present if item.team_estimate is TeamEstimate.ALLY)
    enemy = sum(1 for item in present if item.team_estimate is TeamEstimate.ENEMY)
    return len(present), ally, enemy
