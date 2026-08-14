"""V.5 visual pipeline: V.4 analyze + trajectory/continuity subject refinement."""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from riftlens.domain.capture import CAPTURE_MANIFEST_NAME
from riftlens.domain.enums import Team
from riftlens.domain.ids import new_ulid
from riftlens.domain.observation import (
    CameraProvenance,
    FrameObservation,
    HudObservation,
    KnowledgeState,
    SpatialObservation,
    VisualClaimKind,
    camera_from_capture,
)
from riftlens.domain.timeline import GameStateTimeline
from riftlens.visual.correlate import CorrelationStatus
from riftlens.visual.correlate_v5 import V5CorrelationResult, refine_subject_correlation
from riftlens.visual.errors import ArtifactMissing
from riftlens.visual.track import TeamEstimate
from riftlens.visual.v1_analyze import IdFactory
from riftlens.visual.v4_analyze import (
    DEFAULT_V4_SAMPLE_FPS,
    V4AnalysisResult,
    analyze_capture_dir_v4,
    analyze_manifest_v4,
)

V5_ANALYZER_ID = "riftlens.visual.v5.trajectory"
V5_ANALYZER_VERSION = "v5.0"
DEFAULT_V5_SAMPLE_FPS = DEFAULT_V4_SAMPLE_FPS


@dataclass(frozen=True)
class V5AnalysisResult(V4AnalysisResult):
    """V.4 research output plus V.5 continuity refinement."""

    v5: V5CorrelationResult | None = None
    continuity_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["analyzer_id"] = V5_ANALYZER_ID
        payload["analyzer_version"] = V5_ANALYZER_VERSION
        payload["v5"] = None if self.v5 is None else self.v5.to_dict()
        payload["continuity_ms"] = self.continuity_ms
        payload["detector_source"] = "v4.spectator+v5.trajectory"
        # Surface refined correlation as the primary subject_correlation.
        if self.v5 is not None:
            payload["subject_correlation"] = {
                "status": self.correlation.status.value,
                "track_id": self.correlation.track_id,
                "participant_id": self.correlation.participant_id,
                "champion_id": self.correlation.champion_id,
                "confidence": self.correlation.confidence,
                "method": self.correlation.method,
                "claim_kind": self.correlation.claim_kind.value,
                "reasons": list(self.correlation.reasons),
                "conflicts": list(self.correlation.conflicts),
            }
            payload["v4_subject_correlation"] = {
                "status": self.v5.base.status.value,
                "track_id": self.v5.base.track_id,
                "confidence": self.v5.base.confidence,
                "method": self.v5.base.method,
            }
        return payload


def analyze_capture_dir_v5(
    capture_dir: Path,
    *,
    fps: float = DEFAULT_V5_SAMPLE_FPS,
    max_frames: int | None = None,
    id_factory: IdFactory | None = None,
    gst: GameStateTimeline | None = None,
    subject_pid: int | None = None,
    subject_champion: str | None = None,
    capture_review_pid: int | None = None,
    subject_team: Team | None = None,
) -> V5AnalysisResult:
    """Load an R.10 capture directory and run V.4 + V.5 refinement."""
    manifest_path = Path(capture_dir) / CAPTURE_MANIFEST_NAME
    if not manifest_path.is_file():
        raise ArtifactMissing(f"missing {CAPTURE_MANIFEST_NAME}")
    return analyze_manifest_v5(
        manifest_path,
        fps=fps,
        max_frames=max_frames,
        id_factory=id_factory,
        gst=gst,
        subject_pid=subject_pid,
        subject_champion=subject_champion,
        capture_review_pid=capture_review_pid,
        subject_team=subject_team,
    )


def analyze_manifest_v5(
    manifest_path: Path,
    *,
    fps: float = DEFAULT_V5_SAMPLE_FPS,
    max_frames: int | None = None,
    id_factory: IdFactory | None = None,
    gst: GameStateTimeline | None = None,
    subject_pid: int | None = None,
    subject_champion: str | None = None,
    capture_review_pid: int | None = None,
    subject_team: Team | None = None,
) -> V5AnalysisResult:
    """Run V.4 then apply V.5 continuity cues. Does not mutate GST."""
    v4 = analyze_manifest_v4(
        manifest_path,
        fps=fps,
        max_frames=max_frames,
        id_factory=id_factory,
        gst=gst,
        subject_pid=subject_pid,
        subject_champion=subject_champion,
        capture_review_pid=capture_review_pid,
        subject_team=subject_team,
    )
    return refine_v4_result(v4, id_factory=id_factory)


def refine_v4_result(
    v4: V4AnalysisResult,
    *,
    id_factory: IdFactory | None = None,
) -> V5AnalysisResult:
    """Apply V.5 cues to an existing V.4 result (cheap; no re-detect)."""
    make_id = id_factory or new_ulid
    camera = (
        v4.sequence.frames[0].camera
        if v4.sequence.frames
        else camera_from_capture(camera_controlled=False)
    )
    subject_label = _subject_track_label(v4)
    started = time.perf_counter()
    v5 = refine_subject_correlation(
        v4.correlation,
        v4.tracks,
        alignment=v4.alignment,
        camera_control=camera.control,
        subject_team_label=subject_label,
    )
    continuity_ms = (time.perf_counter() - started) * 1000.0
    cue_frames = _cue_inferred_frames(
        v4,
        v5=v5,
        camera=camera,
        make_id=make_id,
    )
    inferred = [_stamp_v5(item) for item in (*v4.inferred_frames, *cue_frames)]
    # Replace subject_track_correlation frames with refined status.
    inferred = _replace_subject_correlation_frames(inferred, v5=v5, make_id=make_id, v4=v4)
    subject_visibility = (
        KnowledgeState.KNOWN
        if v5.refined.status is not CorrelationStatus.UNKNOWN and v5.refined.track_id
        else KnowledgeState.UNKNOWN
    )
    sequence = replace(
        v4.sequence,
        detector_id=V5_ANALYZER_ID,
        detector_version=V5_ANALYZER_VERSION,
        frames=tuple(_stamp_v5(item) for item in v4.sequence.frames),
    )
    return V5AnalysisResult(
        sequence=sequence,
        inferred_frames=tuple(inferred),
        tracks=v4.tracks,
        events=v4.events,
        correlation=v5.refined,
        alignment=v4.alignment,
        sample_fps=v4.sample_fps,
        timing=v4.timing,
        informative_frames=v4.informative_frames,
        uninformative_frames=v4.uninformative_frames,
        peak_stable_tracks=v4.peak_stable_tracks,
        subject_visibility=subject_visibility,
        camera_note=v4.camera_note,
        clip_duration_ms=v4.clip_duration_ms,
        metrics=v4.metrics,
        raw_bar_detections=v4.raw_bar_detections,
        confirmed_detections=v4.confirmed_detections,
        calibration=v4.calibration,
        color_sample_ms=v4.color_sample_ms,
        calibrate_ms=v4.calibrate_ms,
        track_labels=v4.track_labels,
        v5=v5,
        continuity_ms=continuity_ms,
    )


def analyze_capture_dir_v4_baseline(
    capture_dir: Path,
    **kwargs: Any,
) -> V4AnalysisResult:
    """Expose V.4 baseline entry for research scripts."""
    return analyze_capture_dir_v4(capture_dir, **kwargs)


def _subject_track_label(v4: V4AnalysisResult) -> TeamEstimate | None:
    """Expected subject-relative label is ALLY when calibration knows the subject team."""
    if v4.calibration is None or v4.calibration.subject_team is None:
        return None
    # Relative to subject, the subject track should be ALLY after calibration.
    return TeamEstimate.ALLY


def _stamp_v5(frame: FrameObservation) -> FrameObservation:
    return replace(
        frame,
        detector_id=V5_ANALYZER_ID,
        detector_version=V5_ANALYZER_VERSION,
    )


def _cue_inferred_frames(
    v4: V4AnalysisResult,
    *,
    v5: V5CorrelationResult,
    camera: CameraProvenance,
    make_id: IdFactory,
) -> list[FrameObservation]:
    if v5.bundle is None:
        return []
    clip = v4.sequence.media_artifact_id
    match_id = v4.sequence.match_id
    source_id = v4.sequence.gameplay_source_id
    capture_id = v4.sequence.capture_interval_id
    clock = v4.sequence.clock_map_id
    out: list[FrameObservation] = []
    # Geometry MOTION cue as VISUAL (observed centers); interpretations INFERRED.
    if v5.bundle.trajectory is not None:
        traj = v5.bundle.trajectory
        out.append(
            FrameObservation(
                observation_id=make_id(),
                match_id=match_id,
                gameplay_source_id=source_id,
                capture_interval_id=capture_id,
                media_artifact_id=clip,
                game_t_ms=traj.game_t_ms,
                clock_map_id=clock,
                observation_type="subject_trajectory_geometry",
                confidence=float(traj.confidence),
                detector_id=V5_ANALYZER_ID,
                detector_version=V5_ANALYZER_VERSION,
                camera=camera,
                claim_kind=VisualClaimKind.OBSERVED,
                entities=(),
                hud=HudObservation(hud_visible=KnowledgeState.UNKNOWN),
                spatial=SpatialObservation(
                    knowledge=KnowledgeState.UNKNOWN,
                    minimap_visible=KnowledgeState.UNKNOWN,
                    labels=("trajectory_geometry",),
                ),
                payload={
                    **traj.to_dict(),
                    "source": "VISUAL",
                },
            )
        )
    for cue in v5.bundle.cues:
        out.append(
            FrameObservation(
                observation_id=make_id(),
                match_id=match_id,
                gameplay_source_id=source_id,
                capture_interval_id=capture_id,
                media_artifact_id=clip,
                game_t_ms=cue.game_t_ms,
                clock_map_id=clock,
                observation_type="subject_continuity_cue",
                confidence=float(cue.confidence),
                detector_id=V5_ANALYZER_ID,
                detector_version=V5_ANALYZER_VERSION,
                camera=camera,
                claim_kind=VisualClaimKind.INFERRED,
                entities=(),
                hud=HudObservation(hud_visible=KnowledgeState.UNKNOWN),
                spatial=SpatialObservation(
                    knowledge=KnowledgeState.UNKNOWN,
                    minimap_visible=KnowledgeState.UNKNOWN,
                    labels=("continuity_cue", cue.cue_type.value),
                ),
                payload={
                    **cue.to_dict(),
                    "source": cue.provenance,
                },
            )
        )
    return out


def _replace_subject_correlation_frames(
    frames: Sequence[FrameObservation],
    *,
    v5: V5CorrelationResult,
    make_id: IdFactory,
    v4: V4AnalysisResult,
) -> list[FrameObservation]:
    kept = [item for item in frames if item.observation_type != "subject_track_correlation"]
    refined = v5.refined
    if refined.status is CorrelationStatus.UNKNOWN or refined.track_id is None:
        return kept
    clip = v4.sequence.media_artifact_id
    camera = (
        v4.sequence.frames[0].camera
        if v4.sequence.frames
        else camera_from_capture(camera_controlled=False)
    )
    death_t = (
        None
        if v4.alignment.subject is None or not v4.alignment.subject.deaths
        else int(v4.alignment.subject.deaths[0])
    )
    game_t = death_t if death_t is not None else (
        v4.tracks[0].last_seen_game_t_ms if v4.tracks else v4.sequence.start_game_ms
    )
    kept.append(
        FrameObservation(
            observation_id=make_id(),
            match_id=v4.sequence.match_id,
            gameplay_source_id=v4.sequence.gameplay_source_id,
            capture_interval_id=v4.sequence.capture_interval_id,
            media_artifact_id=clip,
            game_t_ms=int(game_t),
            clock_map_id=v4.sequence.clock_map_id,
            observation_type="subject_track_correlation",
            confidence=float(refined.confidence),
            detector_id=V5_ANALYZER_ID,
            detector_version=V5_ANALYZER_VERSION,
            camera=camera,
            claim_kind=VisualClaimKind.INFERRED,
            entities=(),
            hud=HudObservation(hud_visible=KnowledgeState.UNKNOWN),
            spatial=SpatialObservation(
                knowledge=KnowledgeState.UNKNOWN,
                minimap_visible=KnowledgeState.UNKNOWN,
                labels=("subject_correlation", "v5"),
            ),
            payload={
                "status": refined.status.value,
                "track_id": refined.track_id,
                "participant_id": refined.participant_id,
                "champion_id": refined.champion_id,
                "method": refined.method,
                "reasons": list(refined.reasons),
                "conflicts": list(refined.conflicts),
                "identity_change": v5.identity_change,
                "source": "VISUAL_INFERRED",
            },
        )
    )
    return kept
