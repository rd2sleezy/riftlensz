"""V.6 visual pipeline: V.5 analyze + death-window candidate ranking."""

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
from riftlens.visual.correlate_v6 import V6CorrelationResult, refine_with_death_ranking
from riftlens.visual.errors import ArtifactMissing
from riftlens.visual.track import TeamEstimate
from riftlens.visual.v1_analyze import IdFactory
from riftlens.visual.v4_analyze import DEFAULT_V4_SAMPLE_FPS
from riftlens.visual.v5_analyze import V5AnalysisResult, analyze_manifest_v5, refine_v4_result

V6_ANALYZER_ID = "riftlens.visual.v6.death_rank"
V6_ANALYZER_VERSION = "v6.0"
DEFAULT_V6_SAMPLE_FPS = DEFAULT_V4_SAMPLE_FPS


@dataclass(frozen=True)
class V6AnalysisResult(V5AnalysisResult):
    """V.5 research output plus V.6 death-candidate ranking."""

    v6: V6CorrelationResult | None = None
    ranking_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["analyzer_id"] = V6_ANALYZER_ID
        payload["analyzer_version"] = V6_ANALYZER_VERSION
        payload["v6"] = None if self.v6 is None else self.v6.to_dict()
        payload["ranking_ms"] = self.ranking_ms
        payload["detector_source"] = "v4.spectator+v5.trajectory+v6.death_rank"
        if self.v6 is not None:
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
            payload["v5_subject_correlation"] = {
                "status": self.v6.base.status.value,
                "track_id": self.v6.base.track_id,
                "confidence": self.v6.base.confidence,
                "method": self.v6.base.method,
            }
        return payload


def analyze_capture_dir_v6(
    capture_dir: Path,
    *,
    fps: float = DEFAULT_V6_SAMPLE_FPS,
    max_frames: int | None = None,
    id_factory: IdFactory | None = None,
    gst: GameStateTimeline | None = None,
    subject_pid: int | None = None,
    subject_champion: str | None = None,
    capture_review_pid: int | None = None,
    subject_team: Team | None = None,
) -> V6AnalysisResult:
    """Load an R.10 capture directory and run V.5 + V.6 ranking."""
    manifest_path = Path(capture_dir) / CAPTURE_MANIFEST_NAME
    if not manifest_path.is_file():
        raise ArtifactMissing(f"missing {CAPTURE_MANIFEST_NAME}")
    return analyze_manifest_v6(
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


def analyze_manifest_v6(
    manifest_path: Path,
    *,
    fps: float = DEFAULT_V6_SAMPLE_FPS,
    max_frames: int | None = None,
    id_factory: IdFactory | None = None,
    gst: GameStateTimeline | None = None,
    subject_pid: int | None = None,
    subject_champion: str | None = None,
    capture_review_pid: int | None = None,
    subject_team: Team | None = None,
) -> V6AnalysisResult:
    """Run V.5 then apply V.6 ranking. Does not mutate GST."""
    v5 = analyze_manifest_v5(
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
    return refine_v5_result(
        v5,
        id_factory=id_factory,
        subject_pid=subject_pid,
        subject_champion=subject_champion,
    )


def refine_v5_result(
    v5: V5AnalysisResult,
    *,
    id_factory: IdFactory | None = None,
    subject_pid: int | None = None,
    subject_champion: str | None = None,
) -> V6AnalysisResult:
    """Apply V.6 ranking to an existing V.5 result (cheap; no re-detect)."""
    make_id = id_factory or new_ulid
    camera = (
        v5.sequence.frames[0].camera
        if v5.sequence.frames
        else camera_from_capture(camera_controlled=False)
    )
    subject_label = _subject_track_label(v5)
    pid = (
        subject_pid
        if subject_pid is not None
        else (None if v5.alignment.subject is None else v5.alignment.subject.participant_id)
    )
    champion = subject_champion
    if champion is None and v5.alignment.subject is not None:
        champion = v5.alignment.subject.champion
    started = time.perf_counter()
    v6 = refine_with_death_ranking(
        v5.correlation,
        v5.tracks,
        alignment=v5.alignment,
        subject_pid=pid,
        subject_champion=champion,
        camera_control=camera.control,
        subject_team_label=subject_label,
    )
    ranking_ms = (time.perf_counter() - started) * 1000.0
    inferred = _replace_subject_correlation_frames(
        v5.inferred_frames,
        v6=v6,
        make_id=make_id,
        v5=v5,
        camera=camera,
    )
    subject_visibility = (
        KnowledgeState.KNOWN
        if v6.refined.status is not CorrelationStatus.UNKNOWN and v6.refined.track_id
        else KnowledgeState.UNKNOWN
    )
    sequence = replace(
        v5.sequence,
        detector_id=V6_ANALYZER_ID,
        detector_version=V6_ANALYZER_VERSION,
        frames=tuple(_stamp_v6(item) for item in v5.sequence.frames),
    )
    return V6AnalysisResult(
        sequence=sequence,
        inferred_frames=tuple(inferred),
        tracks=v5.tracks,
        events=v5.events,
        correlation=v6.refined,
        alignment=v5.alignment,
        sample_fps=v5.sample_fps,
        timing=v5.timing,
        informative_frames=v5.informative_frames,
        uninformative_frames=v5.uninformative_frames,
        peak_stable_tracks=v5.peak_stable_tracks,
        subject_visibility=subject_visibility,
        camera_note=v5.camera_note,
        clip_duration_ms=v5.clip_duration_ms,
        metrics=v5.metrics,
        raw_bar_detections=v5.raw_bar_detections,
        confirmed_detections=v5.confirmed_detections,
        calibration=v5.calibration,
        color_sample_ms=v5.color_sample_ms,
        calibrate_ms=v5.calibrate_ms,
        track_labels=v5.track_labels,
        v5=v5.v5,
        continuity_ms=v5.continuity_ms,
        v6=v6,
        ranking_ms=ranking_ms,
    )


def refine_v4_then_v6(
    v4_result: Any,
    *,
    id_factory: IdFactory | None = None,
    subject_pid: int | None = None,
    subject_champion: str | None = None,
) -> V6AnalysisResult:
    """Convenience: V.4 → V.5 → V.6 without re-detect."""
    v5 = refine_v4_result(v4_result, id_factory=id_factory)
    return refine_v5_result(
        v5,
        id_factory=id_factory,
        subject_pid=subject_pid,
        subject_champion=subject_champion,
    )


def _subject_track_label(v5: V5AnalysisResult) -> TeamEstimate | None:
    if v5.calibration is None or v5.calibration.subject_team is None:
        return None
    return TeamEstimate.ALLY


def _stamp_v6(frame: FrameObservation) -> FrameObservation:
    return replace(
        frame,
        detector_id=V6_ANALYZER_ID,
        detector_version=V6_ANALYZER_VERSION,
    )


def _replace_subject_correlation_frames(
    frames: Sequence[FrameObservation],
    *,
    v6: V6CorrelationResult,
    make_id: IdFactory,
    v5: V5AnalysisResult,
    camera: CameraProvenance,
) -> list[FrameObservation]:
    kept = [item for item in frames if item.observation_type != "subject_track_correlation"]
    refined = v6.refined
    if refined.status is CorrelationStatus.UNKNOWN or refined.track_id is None:
        # Keep ranking provenance even when UNKNOWN.
        if v6.ranking is not None:
            death_t = v6.ranking.death_t_ms
            kept.append(
                FrameObservation(
                    observation_id=make_id(),
                    match_id=v5.sequence.match_id,
                    gameplay_source_id=v5.sequence.gameplay_source_id,
                    capture_interval_id=v5.sequence.capture_interval_id,
                    media_artifact_id=v5.sequence.media_artifact_id,
                    game_t_ms=int(death_t),
                    clock_map_id=v5.sequence.clock_map_id,
                    observation_type="subject_death_candidate_ranking",
                    confidence=0.0,
                    detector_id=V6_ANALYZER_ID,
                    detector_version=V6_ANALYZER_VERSION,
                    camera=camera,
                    claim_kind=VisualClaimKind.INFERRED,
                    entities=(),
                    hud=HudObservation(hud_visible=KnowledgeState.UNKNOWN),
                    spatial=SpatialObservation(
                        knowledge=KnowledgeState.UNKNOWN,
                        minimap_visible=KnowledgeState.UNKNOWN,
                        labels=("death_candidate_ranking", "v6"),
                    ),
                    payload={
                        **v6.ranking.to_dict(),
                        "source": "VISUAL_INFERRED",
                        "reject_reason": v6.ranking.reject_reason,
                    },
                )
            )
        return kept
    correlation_death_t: int | None = (
        None
        if v5.alignment.subject is None or not v5.alignment.subject.deaths
        else int(v5.alignment.subject.deaths[0])
    )
    game_t: int = (
        correlation_death_t
        if correlation_death_t is not None
        else (v5.tracks[0].last_seen_game_t_ms if v5.tracks else v5.sequence.start_game_ms)
    )
    kept.append(
        FrameObservation(
            observation_id=make_id(),
            match_id=v5.sequence.match_id,
            gameplay_source_id=v5.sequence.gameplay_source_id,
            capture_interval_id=v5.sequence.capture_interval_id,
            media_artifact_id=v5.sequence.media_artifact_id,
            game_t_ms=int(game_t),
            clock_map_id=v5.sequence.clock_map_id,
            observation_type="subject_track_correlation",
            confidence=float(refined.confidence),
            detector_id=V6_ANALYZER_ID,
            detector_version=V6_ANALYZER_VERSION,
            camera=camera,
            claim_kind=VisualClaimKind.INFERRED,
            entities=(),
            hud=HudObservation(hud_visible=KnowledgeState.UNKNOWN),
            spatial=SpatialObservation(
                knowledge=KnowledgeState.UNKNOWN,
                minimap_visible=KnowledgeState.UNKNOWN,
                labels=("subject_correlation", "v6"),
            ),
            payload={
                "status": refined.status.value,
                "track_id": refined.track_id,
                "participant_id": refined.participant_id,
                "champion_id": refined.champion_id,
                "method": refined.method,
                "reasons": list(refined.reasons),
                "conflicts": list(refined.conflicts),
                "identity_change": v6.identity_change,
                "winner_margin": v6.winner_margin,
                "ranking": None if v6.ranking is None else v6.ranking.to_dict(),
                "source": "VISUAL_INFERRED",
            },
        )
    )
    return kept
