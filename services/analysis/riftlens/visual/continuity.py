"""V.5 death-window continuity cues. Complements GST death alignment; never replaces it."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from riftlens.visual.gst_align import DEATH_ALIGN_MS, disappearing_near
from riftlens.visual.track import CandidateKind, EntityTrack, TeamEstimate, TrackObservation
from riftlens.visual.trajectory import MotionClass, TrajectoryCue, measure_trajectory

PRE_DEATH_WINDOW_MS = 3_000
POST_DEATH_ABSENCE_MS = 1_500
ACCEPTABLE_GAP_MS = 500  # ~2 frames @ 4 fps (miss grace)
LARGE_GAP_MS = 2_000
SUPPORT_CONFIDENCE = 0.55
WEAK_CONFIDENCE = 0.35
CONFLICT_CONFIDENCE = 0.2


class CueVerdict(StrEnum):
    SUPPORT = "SUPPORT"
    NEUTRAL = "NEUTRAL"
    CONFLICT = "CONFLICT"
    REJECTED = "REJECTED"


class CueType(StrEnum):
    PRE_DEATH_CONTINUITY = "PRE_DEATH_CONTINUITY"
    DEATH_TIME_PROXIMITY = "DEATH_TIME_PROXIMITY"
    MOTION_CONTINUITY = "MOTION_CONTINUITY"
    POST_DEATH_ABSENCE = "POST_DEATH_ABSENCE"
    TEAM_LABEL_AGREES = "TEAM_LABEL_AGREES"


@dataclass(frozen=True)
class ContinuityCue:
    """One V.5 identity-supporting or identity-conflicting cue."""

    cue_type: CueType
    track_id: str
    game_t_ms: int
    death_t_ms: int | None
    verdict: CueVerdict
    confidence: float
    claim_kind: str  # OBSERVED | INFERRED
    provenance: str  # VISUAL | VISUAL_INFERRED
    raw: dict[str, object]
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "cue_type": self.cue_type.value,
            "track_id": self.track_id,
            "game_t_ms": self.game_t_ms,
            "death_t_ms": self.death_t_ms,
            "verdict": self.verdict.value,
            "confidence": self.confidence,
            "claim_kind": self.claim_kind,
            "provenance": self.provenance,
            "raw": dict(self.raw),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ContinuityBundle:
    """All cues evaluated for one candidate subject track."""

    track_id: str
    death_t_ms: int | None
    trajectory: TrajectoryCue | None
    cues: tuple[ContinuityCue, ...]
    support_count: int
    conflict_count: int
    continuity_duration_ms: int
    longest_gap_ms: int

    def to_dict(self) -> dict[str, object]:
        return {
            "track_id": self.track_id,
            "death_t_ms": self.death_t_ms,
            "trajectory": None if self.trajectory is None else self.trajectory.to_dict(),
            "cues": [item.to_dict() for item in self.cues],
            "support_count": self.support_count,
            "conflict_count": self.conflict_count,
            "continuity_duration_ms": self.continuity_duration_ms,
            "longest_gap_ms": self.longest_gap_ms,
        }


def evaluate_continuity(
    track: EntityTrack,
    *,
    death_t_ms: int | None,
    all_tracks: Sequence[EntityTrack] = (),
    subject_team_label: TeamEstimate | None = None,
) -> ContinuityBundle:
    """Evaluate V.5 cues for ``track`` around optional GST death."""
    trajectory = measure_trajectory(track)
    cues: list[ContinuityCue] = []
    pre = _pre_death_continuity(track, death_t_ms=death_t_ms)
    cues.append(pre)
    cues.append(_death_proximity(track, death_t_ms=death_t_ms, all_tracks=all_tracks))
    cues.append(_motion_cue(track, trajectory, death_t_ms=death_t_ms))
    cues.append(_post_death_absence(track, death_t_ms=death_t_ms))
    team_cue = _team_label_cue(track, subject_team_label=subject_team_label, death_t_ms=death_t_ms)
    if team_cue is not None:
        cues.append(team_cue)
    support = sum(1 for item in cues if item.verdict is CueVerdict.SUPPORT)
    conflict = sum(1 for item in cues if item.verdict is CueVerdict.CONFLICT)
    duration_raw = pre.raw.get("continuous_presence_ms", 0)
    gap_raw = pre.raw.get("longest_gap_ms", 0)
    continuity_duration_ms = int(duration_raw) if isinstance(duration_raw, int) else 0
    longest_gap_ms = int(gap_raw) if isinstance(gap_raw, int) else 0
    return ContinuityBundle(
        track_id=track.track_id,
        death_t_ms=death_t_ms,
        trajectory=trajectory,
        cues=tuple(cues),
        support_count=support,
        conflict_count=conflict,
        continuity_duration_ms=continuity_duration_ms,
        longest_gap_ms=longest_gap_ms,
    )


def _observations_before(
    track: EntityTrack, *, death_t_ms: int, window_ms: int
) -> tuple[TrackObservation, ...]:
    start = death_t_ms - window_ms
    return tuple(
        obs
        for obs in track.observations
        if start <= obs.game_t_ms <= death_t_ms
    )


def _gap_stats(observations: Sequence[TrackObservation]) -> tuple[int, int]:
    """Return (longest_gap_ms, observation_count)."""
    if len(observations) < 2:
        return 0, len(observations)
    gaps = [
        observations[i].game_t_ms - observations[i - 1].game_t_ms
        for i in range(1, len(observations))
    ]
    return max(gaps), len(observations)


def _pre_death_continuity(track: EntityTrack, *, death_t_ms: int | None) -> ContinuityCue:
    stamp = track.last_seen_game_t_ms
    if death_t_ms is None:
        return ContinuityCue(
            cue_type=CueType.PRE_DEATH_CONTINUITY,
            track_id=track.track_id,
            game_t_ms=stamp,
            death_t_ms=None,
            verdict=CueVerdict.REJECTED,
            confidence=0.0,
            claim_kind="INFERRED",
            provenance="VISUAL_INFERRED",
            raw={},
            reason="no_gst_death",
        )
    window = _observations_before(track, death_t_ms=death_t_ms, window_ms=PRE_DEATH_WINDOW_MS)
    longest_gap, count = _gap_stats(window)
    if count == 0:
        duration = 0
    else:
        duration = int(window[-1].game_t_ms - window[0].game_t_ms)
    raw: dict[str, object] = {
        "pre_death_observation_count": count,
        "continuous_presence_ms": duration,
        "longest_gap_ms": longest_gap,
        "window_ms": PRE_DEATH_WINDOW_MS,
        "mean_track_confidence": (
            0.0
            if not window
            else round(sum(o.confidence for o in window) / float(len(window)), 3)
        ),
    }
    if count < 2:
        return ContinuityCue(
            cue_type=CueType.PRE_DEATH_CONTINUITY,
            track_id=track.track_id,
            game_t_ms=stamp,
            death_t_ms=death_t_ms,
            verdict=CueVerdict.NEUTRAL,
            confidence=WEAK_CONFIDENCE,
            claim_kind="INFERRED",
            provenance="VISUAL_INFERRED",
            raw=raw,
            reason="sparse_pre_death_observations",
        )
    if longest_gap > LARGE_GAP_MS:
        return ContinuityCue(
            cue_type=CueType.PRE_DEATH_CONTINUITY,
            track_id=track.track_id,
            game_t_ms=stamp,
            death_t_ms=death_t_ms,
            verdict=CueVerdict.CONFLICT,
            confidence=CONFLICT_CONFIDENCE,
            claim_kind="INFERRED",
            provenance="VISUAL_INFERRED",
            raw=raw,
            reason="large_pre_death_gap",
        )
    if longest_gap <= ACCEPTABLE_GAP_MS and duration >= 500:
        return ContinuityCue(
            cue_type=CueType.PRE_DEATH_CONTINUITY,
            track_id=track.track_id,
            game_t_ms=stamp,
            death_t_ms=death_t_ms,
            verdict=CueVerdict.SUPPORT,
            confidence=SUPPORT_CONFIDENCE,
            claim_kind="INFERRED",
            provenance="VISUAL_INFERRED",
            raw=raw,
            reason="continuous_pre_death_presence",
        )
    if longest_gap <= LARGE_GAP_MS:
        return ContinuityCue(
            cue_type=CueType.PRE_DEATH_CONTINUITY,
            track_id=track.track_id,
            game_t_ms=stamp,
            death_t_ms=death_t_ms,
            verdict=CueVerdict.NEUTRAL,
            confidence=WEAK_CONFIDENCE,
            claim_kind="INFERRED",
            provenance="VISUAL_INFERRED",
            raw=raw,
            reason="fragmented_but_acceptable_gaps",
        )
    return ContinuityCue(
        cue_type=CueType.PRE_DEATH_CONTINUITY,
        track_id=track.track_id,
        game_t_ms=stamp,
        death_t_ms=death_t_ms,
        verdict=CueVerdict.NEUTRAL,
        confidence=WEAK_CONFIDENCE,
        claim_kind="INFERRED",
        provenance="VISUAL_INFERRED",
        raw=raw,
        reason="weak_pre_death_continuity",
    )


def _death_proximity(
    track: EntityTrack,
    *,
    death_t_ms: int | None,
    all_tracks: Sequence[EntityTrack],
) -> ContinuityCue:
    stamp = track.last_seen_game_t_ms
    if death_t_ms is None:
        return ContinuityCue(
            cue_type=CueType.DEATH_TIME_PROXIMITY,
            track_id=track.track_id,
            game_t_ms=stamp,
            death_t_ms=None,
            verdict=CueVerdict.REJECTED,
            confidence=0.0,
            claim_kind="INFERRED",
            provenance="VISUAL_INFERRED",
            raw={},
            reason="no_gst_death",
        )
    delta = abs(track.last_seen_game_t_ms - death_t_ms)
    nearby = disappearing_near(all_tracks or (track,), death_t_ms, window_ms=DEATH_ALIGN_MS)
    champ = [
        item
        for item in nearby
        if item.kind is CandidateKind.CHAMPION_LIKE and not item.ambiguous
    ]
    raw: dict[str, object] = {
        "delta_ms": delta,
        "align_window_ms": DEATH_ALIGN_MS,
        "disappearing_track_ids": [item.track_id for item in champ],
        "unique_disappearance": len(champ) == 1 and champ[0].track_id == track.track_id,
    }
    if len(champ) > 1 and track.track_id in {item.track_id for item in champ}:
        return ContinuityCue(
            cue_type=CueType.DEATH_TIME_PROXIMITY,
            track_id=track.track_id,
            game_t_ms=stamp,
            death_t_ms=death_t_ms,
            verdict=CueVerdict.CONFLICT,
            confidence=CONFLICT_CONFIDENCE,
            claim_kind="INFERRED",
            provenance="VISUAL_INFERRED",
            raw=raw,
            reason="competing_disappearances_near_death",
        )
    if delta <= DEATH_ALIGN_MS and track.first_seen_game_t_ms <= death_t_ms:
        verdict = CueVerdict.SUPPORT
        reason = "last_observation_near_gst_death"
        conf = SUPPORT_CONFIDENCE
    elif delta <= DEATH_ALIGN_MS * 2:
        verdict = CueVerdict.NEUTRAL
        reason = "loose_death_proximity"
        conf = WEAK_CONFIDENCE
    else:
        verdict = CueVerdict.CONFLICT
        reason = "last_observation_far_from_death"
        conf = CONFLICT_CONFIDENCE
    return ContinuityCue(
        cue_type=CueType.DEATH_TIME_PROXIMITY,
        track_id=track.track_id,
        game_t_ms=stamp,
        death_t_ms=death_t_ms,
        verdict=verdict,
        confidence=conf,
        claim_kind="INFERRED",
        provenance="VISUAL_INFERRED",
        raw=raw,
        reason=reason,
    )


def _motion_cue(
    track: EntityTrack, trajectory: TrajectoryCue, *, death_t_ms: int | None
) -> ContinuityCue:
    motion = trajectory.motion_class
    raw: dict[str, object] = {
        "motion_class": motion.value,
        "mean_step_px": trajectory.mean_step_px,
        "max_step_px": trajectory.max_step_px,
        "direction_consistency": trajectory.direction_consistency,
        "observation_count": trajectory.observation_count,
    }
    if motion is MotionClass.JUMPY:
        verdict = CueVerdict.CONFLICT
        reason = "impossible_screen_jump"
        conf = CONFLICT_CONFIDENCE
    elif motion is MotionClass.CAMERA_LIKE:
        verdict = CueVerdict.NEUTRAL
        reason = "camera_like_displacement_not_overinterpreted"
        conf = WEAK_CONFIDENCE
    elif motion is MotionClass.SPARSE:
        verdict = CueVerdict.NEUTRAL
        reason = "sparse_motion_evidence"
        conf = WEAK_CONFIDENCE
    elif motion in {MotionClass.STATIONARY, MotionClass.SMOOTH_MOVING}:
        verdict = CueVerdict.SUPPORT
        reason = f"motion_{motion.value.lower()}"
        conf = min(SUPPORT_CONFIDENCE, trajectory.confidence)
    else:
        verdict = CueVerdict.NEUTRAL
        reason = "uncertain_motion"
        conf = WEAK_CONFIDENCE
    return ContinuityCue(
        cue_type=CueType.MOTION_CONTINUITY,
        track_id=track.track_id,
        game_t_ms=trajectory.game_t_ms,
        death_t_ms=death_t_ms,
        verdict=verdict,
        confidence=conf,
        claim_kind="INFERRED",
        provenance="VISUAL_INFERRED",
        raw=raw,
        reason=reason,
    )


def _post_death_absence(track: EntityTrack, *, death_t_ms: int | None) -> ContinuityCue:
    stamp = track.last_seen_game_t_ms
    if death_t_ms is None:
        return ContinuityCue(
            cue_type=CueType.POST_DEATH_ABSENCE,
            track_id=track.track_id,
            game_t_ms=stamp,
            death_t_ms=None,
            verdict=CueVerdict.REJECTED,
            confidence=0.0,
            claim_kind="INFERRED",
            provenance="VISUAL_INFERRED",
            raw={},
            reason="no_gst_death",
        )
    after = tuple(obs for obs in track.observations if obs.game_t_ms > death_t_ms + 250)
    late = tuple(
        obs
        for obs in after
        if obs.game_t_ms <= death_t_ms + POST_DEATH_ABSENCE_MS
    )
    raw: dict[str, object] = {
        "observations_after_death": len(after),
        "observations_in_absence_window": len(late),
        "absence_window_ms": POST_DEATH_ABSENCE_MS,
        "last_seen_game_t_ms": track.last_seen_game_t_ms,
    }
    # Clearly still observed well after death → conflict (likely wrong identity).
    if any(obs.game_t_ms > death_t_ms + POST_DEATH_ABSENCE_MS for obs in track.observations):
        return ContinuityCue(
            cue_type=CueType.POST_DEATH_ABSENCE,
            track_id=track.track_id,
            game_t_ms=stamp,
            death_t_ms=death_t_ms,
            verdict=CueVerdict.CONFLICT,
            confidence=CONFLICT_CONFIDENCE,
            claim_kind="INFERRED",
            provenance="VISUAL_INFERRED",
            raw=raw,
            reason="track_remains_alive_after_death",
        )
    if track.last_seen_game_t_ms <= death_t_ms + 250:
        return ContinuityCue(
            cue_type=CueType.POST_DEATH_ABSENCE,
            track_id=track.track_id,
            game_t_ms=stamp,
            death_t_ms=death_t_ms,
            verdict=CueVerdict.SUPPORT,
            confidence=SUPPORT_CONFIDENCE,
            claim_kind="INFERRED",
            provenance="VISUAL_INFERRED",
            raw=raw,
            reason="disappears_near_death_no_reappear",
        )
    # Brief post-death flash (detector lag) — neutral, camera/dropout confounder.
    return ContinuityCue(
        cue_type=CueType.POST_DEATH_ABSENCE,
        track_id=track.track_id,
        game_t_ms=stamp,
        death_t_ms=death_t_ms,
        verdict=CueVerdict.NEUTRAL,
        confidence=WEAK_CONFIDENCE,
        claim_kind="INFERRED",
        provenance="VISUAL_INFERRED",
        raw=raw,
        reason="brief_post_death_flash_or_dropout",
    )


def _team_label_cue(
    track: EntityTrack,
    *,
    subject_team_label: TeamEstimate | None,
    death_t_ms: int | None,
) -> ContinuityCue | None:
    """Optional second independent cue: calibrated ALLY vs subject.

    Independence: color→team calibration uses bar hue + Riot team mapping;
    death alignment uses temporal disappearance. Not two views of the same signal.
    """
    if subject_team_label is None:
        return None
    stamp = track.last_seen_game_t_ms
    raw: dict[str, object] = {
        "track_team_estimate": track.team_estimate.value,
        "expected_subject_label": subject_team_label.value,
        "independence": "color_calibration_vs_death_timing",
    }
    if track.team_estimate is TeamEstimate.UNKNOWN or subject_team_label is TeamEstimate.UNKNOWN:
        return ContinuityCue(
            cue_type=CueType.TEAM_LABEL_AGREES,
            track_id=track.track_id,
            game_t_ms=stamp,
            death_t_ms=death_t_ms,
            verdict=CueVerdict.NEUTRAL,
            confidence=WEAK_CONFIDENCE,
            claim_kind="INFERRED",
            provenance="VISUAL_INFERRED",
            raw=raw,
            reason="team_label_unavailable",
        )
    if track.team_estimate is subject_team_label:
        return ContinuityCue(
            cue_type=CueType.TEAM_LABEL_AGREES,
            track_id=track.track_id,
            game_t_ms=stamp,
            death_t_ms=death_t_ms,
            verdict=CueVerdict.SUPPORT,
            confidence=SUPPORT_CONFIDENCE,
            claim_kind="INFERRED",
            provenance="VISUAL_INFERRED",
            raw=raw,
            reason="calibrated_team_agrees_with_subject",
        )
    return ContinuityCue(
        cue_type=CueType.TEAM_LABEL_AGREES,
        track_id=track.track_id,
        game_t_ms=stamp,
        death_t_ms=death_t_ms,
        verdict=CueVerdict.CONFLICT,
        confidence=CONFLICT_CONFIDENCE,
        claim_kind="INFERRED",
        provenance="VISUAL_INFERRED",
        raw=raw,
        reason="calibrated_team_conflicts_with_subject",
    )
