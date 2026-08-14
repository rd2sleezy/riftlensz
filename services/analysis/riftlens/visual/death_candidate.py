"""V.6 death-window candidate evidence and ranking.

Broader candidate *pooling* is scored with conflict penalties and a uniqueness
margin. This does not widen ``DEATH_ALIGN_MS`` as a binary V.4 gate.

Camera ownership / subject attachment never contribute score.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from riftlens.visual.continuity import (
    POST_DEATH_ABSENCE_MS,
    CueType,
    CueVerdict,
    evaluate_continuity,
)
from riftlens.visual.gst_align import DEATH_ALIGN_MS, disappearing_near
from riftlens.visual.track import CandidateKind, EntityTrack, TeamEstimate
from riftlens.visual.trajectory import MotionClass

# Pooling window for who enters ranking (not a V.4 binary widen of DEATH_ALIGN_MS).
CANDIDATE_POOL_MS = 5_000
# Required score gap between rank-1 and rank-2 eligible candidates.
MIN_WINNER_MARGIN = 0.12
# Soft temporal join: last_seen within pool before death (or brief post-death flash).
POST_DEATH_FLASH_MS = 250
# Unique disappearance alone is too weak with a single sparse hit.
MIN_OBS_FOR_UNIQUE_SUPPORT = 3

# Score terms (documented; sum capped later at LIKELY confidence policy).
W_TEMPORAL = 0.40
W_UNIQUE_DISAPPEAR = 0.20
W_CONTINUITY = 0.15
W_TRAJECTORY = 0.10
W_TEAM = 0.10


class EvidenceFamily(StrEnum):
    GST_DEATH = "gst_death"
    TRACK_SPAN = "track_span"
    UNIQUE_DISAPPEARANCE = "unique_disappearance"
    PRE_DEATH_CONTINUITY = "pre_death_continuity"
    TRAJECTORY = "trajectory"
    TEAM_LABEL = "team_label"
    ALIVE_AFTER_DEATH = "alive_after_death"
    COMPETITION = "competition"
    FRAGMENTATION = "fragmentation"
    REAPPEARANCE = "reappearance"
    CAMERA_OWNERSHIP = "camera_ownership"
    SUBJECT_ATTACHMENT = "subject_attachment"


@dataclass(frozen=True)
class DeathCandidateEvidence:
    """Raw + scored evidence for one champion-like track near GST death."""

    track_id: str
    team_label: TeamEstimate
    first_seen_ms: int
    last_seen_ms: int
    duration_ms: int
    death_t_ms: int
    death_delta_ms: int
    abs_death_delta_ms: int
    temporal_join: bool
    temporal_score: float
    unique_disappearance: bool
    continuity_duration_ms: int
    longest_gap_ms: int
    continuity_support: bool
    trajectory_class: str
    trajectory_support: bool
    team_agrees: bool | None
    alive_after_death: bool
    reappearance_after_death: bool
    fragmented: bool
    competing_near_death: int
    supports: tuple[str, ...]
    conflicts: tuple[str, ...]
    eligible: bool
    score: float
    rank: int
    raw: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "track_id": self.track_id,
            "team_label": self.team_label.value,
            "first_seen_ms": self.first_seen_ms,
            "last_seen_ms": self.last_seen_ms,
            "duration_ms": self.duration_ms,
            "death_t_ms": self.death_t_ms,
            "death_delta_ms": self.death_delta_ms,
            "abs_death_delta_ms": self.abs_death_delta_ms,
            "temporal_join": self.temporal_join,
            "temporal_score": self.temporal_score,
            "unique_disappearance": self.unique_disappearance,
            "continuity_duration_ms": self.continuity_duration_ms,
            "longest_gap_ms": self.longest_gap_ms,
            "continuity_support": self.continuity_support,
            "trajectory_class": self.trajectory_class,
            "trajectory_support": self.trajectory_support,
            "team_agrees": self.team_agrees,
            "alive_after_death": self.alive_after_death,
            "reappearance_after_death": self.reappearance_after_death,
            "fragmented": self.fragmented,
            "competing_near_death": self.competing_near_death,
            "supports": list(self.supports),
            "conflicts": list(self.conflicts),
            "eligible": self.eligible,
            "score": self.score,
            "rank": self.rank,
            "raw": dict(self.raw),
        }


@dataclass(frozen=True)
class DeathCandidateRanking:
    """Full ranking board for one GST death."""

    death_t_ms: int
    candidates: tuple[DeathCandidateEvidence, ...]
    winner_track_id: str | None
    winner_margin: float
    reject_reason: str | None
    pool_ms: int = CANDIDATE_POOL_MS
    death_align_ms: int = DEATH_ALIGN_MS
    min_winner_margin: float = MIN_WINNER_MARGIN

    def to_dict(self) -> dict[str, object]:
        return {
            "death_t_ms": self.death_t_ms,
            "pool_ms": self.pool_ms,
            "death_align_ms": self.death_align_ms,
            "min_winner_margin": self.min_winner_margin,
            "winner_track_id": self.winner_track_id,
            "winner_margin": self.winner_margin,
            "reject_reason": self.reject_reason,
            "candidates": [item.to_dict() for item in self.candidates],
        }


def rank_death_candidates(
    tracks: Sequence[EntityTrack],
    *,
    death_t_ms: int,
    subject_team_label: TeamEstimate | None = None,
    camera_implies_identity: bool = False,
    subject_attachment_implies_identity: bool = False,
) -> DeathCandidateRanking:
    """Score champion-like tracks near ``death_t_ms``. Fail closed on ambiguity."""
    if camera_implies_identity or subject_attachment_implies_identity:
        return DeathCandidateRanking(
            death_t_ms=death_t_ms,
            candidates=(),
            winner_track_id=None,
            winner_margin=0.0,
            reject_reason=("camera_ownership_or_subject_attachment_alone_never_implies_identity"),
        )
    champ = [
        item for item in tracks if item.kind is CandidateKind.CHAMPION_LIKE and not item.ambiguous
    ]
    disappear = disappearing_near(champ, death_t_ms, window_ms=DEATH_ALIGN_MS)
    disappear_ids = {item.track_id for item in disappear}
    unique_disappear = len(disappear) == 1

    pooled = [item for item in champ if _in_candidate_pool(item, death_t_ms=death_t_ms)]
    built: list[DeathCandidateEvidence] = []
    for track in pooled:
        built.append(
            _score_track(
                track,
                death_t_ms=death_t_ms,
                disappear_ids=disappear_ids,
                unique_disappear=unique_disappear,
                subject_team_label=subject_team_label,
                competing_near_death=len(disappear),
            )
        )
    built.sort(key=lambda item: (-item.score, item.track_id))
    ranked = [replace(item, rank=index) for index, item in enumerate(built, start=1)]

    eligible = [item for item in ranked if item.eligible and item.temporal_join]
    if not eligible:
        reason = "no_eligible_candidates"
        if ranked and all(item.alive_after_death for item in ranked):
            reason = "all_pooled_candidates_alive_after_death"
        elif ranked and any(item.temporal_join for item in ranked):
            reason = "temporal_candidates_conflicted_or_weak"
        elif ranked and not any(item.temporal_join for item in ranked):
            reason = "no_candidate_passes_gst_temporal_gate"
        elif not ranked:
            reason = "no_candidates_in_death_pool"
        return DeathCandidateRanking(
            death_t_ms=death_t_ms,
            candidates=tuple(ranked),
            winner_track_id=None,
            winner_margin=0.0,
            reject_reason=reason,
        )

    winner = eligible[0]
    runner = eligible[1] if len(eligible) > 1 else None
    margin = winner.score - (runner.score if runner is not None else 0.0)
    if runner is not None and margin < MIN_WINNER_MARGIN:
        return DeathCandidateRanking(
            death_t_ms=death_t_ms,
            candidates=tuple(ranked),
            winner_track_id=None,
            winner_margin=round(margin, 4),
            reject_reason="top_candidates_too_close",
        )
    # Require ≥1 independent support beyond temporal (trajectory alone does not count).
    # Unique disappearance counts only when the track has enough observations.
    independent = [
        name
        for name in winner.supports
        if name
        not in {
            EvidenceFamily.GST_DEATH.value,
            EvidenceFamily.TRACK_SPAN.value,
            EvidenceFamily.TRAJECTORY.value,
        }
    ]
    raw_obs = winner.raw.get("observation_count", 0)
    obs_count = raw_obs if isinstance(raw_obs, int) else 0
    if (
        EvidenceFamily.UNIQUE_DISAPPEARANCE.value in independent
        and obs_count < MIN_OBS_FOR_UNIQUE_SUPPORT
    ):
        independent = [
            name for name in independent if name != EvidenceFamily.UNIQUE_DISAPPEARANCE.value
        ]
    if not independent:
        return DeathCandidateRanking(
            death_t_ms=death_t_ms,
            candidates=tuple(ranked),
            winner_track_id=None,
            winner_margin=round(margin, 4),
            reject_reason="temporal_join_without_independent_support",
        )
    if winner.conflicts:
        return DeathCandidateRanking(
            death_t_ms=death_t_ms,
            candidates=tuple(ranked),
            winner_track_id=None,
            winner_margin=round(margin, 4),
            reject_reason="winner_has_conflicts:" + ",".join(winner.conflicts),
        )
    return DeathCandidateRanking(
        death_t_ms=death_t_ms,
        candidates=tuple(ranked),
        winner_track_id=winner.track_id,
        winner_margin=round(margin, 4),
        reject_reason=None,
    )


def _in_candidate_pool(track: EntityTrack, *, death_t_ms: int) -> bool:
    if track.first_seen_game_t_ms > death_t_ms:
        return False
    # Any observation in the death neighborhood, or last_seen near death.
    if abs(track.last_seen_game_t_ms - death_t_ms) <= CANDIDATE_POOL_MS:
        return True
    return any(abs(obs.game_t_ms - death_t_ms) <= CANDIDATE_POOL_MS for obs in track.observations)


def _score_track(
    track: EntityTrack,
    *,
    death_t_ms: int,
    disappear_ids: set[str],
    unique_disappear: bool,
    subject_team_label: TeamEstimate | None,
    competing_near_death: int,
) -> DeathCandidateEvidence:
    bundle = evaluate_continuity(
        track,
        death_t_ms=death_t_ms,
        all_tracks=(track,),
        subject_team_label=subject_team_label,
    )
    death_delta = track.last_seen_game_t_ms - death_t_ms
    abs_delta = abs(death_delta)
    duration = max(0, track.last_seen_game_t_ms - track.first_seen_game_t_ms)

    alive_after = any(
        obs.game_t_ms > death_t_ms + POST_DEATH_ABSENCE_MS for obs in track.observations
    )
    reappear = _reappearance_after_gap(track, death_t_ms=death_t_ms)
    unique = bool(unique_disappear and track.track_id in disappear_ids)

    temporal_join, temporal_score = _temporal_terms(track, death_t_ms=death_t_ms)
    continuity_support = any(
        cue.cue_type is CueType.PRE_DEATH_CONTINUITY and cue.verdict is CueVerdict.SUPPORT
        for cue in bundle.cues
    )
    continuity_conflict = any(
        cue.cue_type is CueType.PRE_DEATH_CONTINUITY and cue.verdict is CueVerdict.CONFLICT
        for cue in bundle.cues
    )
    traj = bundle.trajectory
    traj_class = MotionClass.SPARSE.value if traj is None else traj.motion_class.value
    trajectory_support = any(
        cue.cue_type is CueType.MOTION_CONTINUITY and cue.verdict is CueVerdict.SUPPORT
        for cue in bundle.cues
    )
    trajectory_conflict = any(
        cue.cue_type is CueType.MOTION_CONTINUITY and cue.verdict is CueVerdict.CONFLICT
        for cue in bundle.cues
    )
    team_agrees = _team_agrees(track, subject_team_label=subject_team_label)

    supports: list[str] = []
    conflicts: list[str] = []
    score = 0.0

    if temporal_join:
        score += temporal_score
        supports.append(EvidenceFamily.GST_DEATH.value)
        supports.append(EvidenceFamily.TRACK_SPAN.value)

    if unique:
        score += W_UNIQUE_DISAPPEAR
        supports.append(EvidenceFamily.UNIQUE_DISAPPEARANCE.value)
    # Competing disappearances reduce uniqueness; scored via missing unique bonus
    # and board-level margin — not a per-track hard conflict that zeros the board.

    if continuity_support:
        score += W_CONTINUITY
        supports.append(EvidenceFamily.PRE_DEATH_CONTINUITY.value)
    if continuity_conflict:
        conflicts.append("weak_or_gappy_continuity")

    # Trajectory strengthens score only when temporal join already holds.
    if temporal_join and trajectory_support:
        score += W_TRAJECTORY
        supports.append(EvidenceFamily.TRAJECTORY.value)
    if trajectory_conflict:
        conflicts.append("jumpy_trajectory")

    if team_agrees is True:
        score += W_TEAM
        supports.append(EvidenceFamily.TEAM_LABEL.value)
    elif team_agrees is False:
        conflicts.append("team_mismatch")

    if alive_after:
        conflicts.append("alive_after_death")
    if reappear:
        conflicts.append("reappearance_after_death")

    # Deduplicate support labels while preserving order.
    seen: set[str] = set()
    support_u: list[str] = []
    for name in supports:
        if name not in seen:
            seen.add(name)
            support_u.append(name)

    eligible = temporal_join and not conflicts and not track.ambiguous
    raw: dict[str, object] = {
        "score_terms": {
            "temporal": round(temporal_score if temporal_join else 0.0, 4),
            "unique_disappear": W_UNIQUE_DISAPPEAR if unique else 0.0,
            "continuity": W_CONTINUITY if continuity_support else 0.0,
            "trajectory": W_TRAJECTORY if (temporal_join and trajectory_support) else 0.0,
            "team": W_TEAM if team_agrees is True else 0.0,
        },
        "weights": {
            "W_TEMPORAL": W_TEMPORAL,
            "W_UNIQUE_DISAPPEAR": W_UNIQUE_DISAPPEAR,
            "W_CONTINUITY": W_CONTINUITY,
            "W_TRAJECTORY": W_TRAJECTORY,
            "W_TEAM": W_TEAM,
        },
        "pool_ms": CANDIDATE_POOL_MS,
        "death_align_ms": DEATH_ALIGN_MS,
        "observation_count": track.observation_count,
        "continuity_bundle": bundle.to_dict(),
    }
    return DeathCandidateEvidence(
        track_id=track.track_id,
        team_label=track.team_estimate,
        first_seen_ms=track.first_seen_game_t_ms,
        last_seen_ms=track.last_seen_game_t_ms,
        duration_ms=duration,
        death_t_ms=death_t_ms,
        death_delta_ms=death_delta,
        abs_death_delta_ms=abs_delta,
        temporal_join=temporal_join,
        temporal_score=round(temporal_score if temporal_join else 0.0, 4),
        unique_disappearance=unique,
        continuity_duration_ms=bundle.continuity_duration_ms,
        longest_gap_ms=bundle.longest_gap_ms,
        continuity_support=continuity_support,
        trajectory_class=traj_class,
        trajectory_support=trajectory_support,
        team_agrees=team_agrees,
        alive_after_death=alive_after,
        reappearance_after_death=reappear,
        fragmented=bool(track.fragmented) or continuity_conflict,
        competing_near_death=competing_near_death,
        supports=tuple(support_u),
        conflicts=tuple(conflicts),
        eligible=eligible,
        score=round(score, 4),
        rank=0,
        raw=raw,
    )


def _temporal_terms(track: EntityTrack, *, death_t_ms: int) -> tuple[bool, float]:
    """Soft temporal join with proximity score. Does not mutate DEATH_ALIGN_MS."""
    last_seen = track.last_seen_game_t_ms
    # Must have been present at/before death (not only after).
    if track.first_seen_game_t_ms > death_t_ms:
        return False, 0.0
    # Alive well after death is handled as conflict; still may be in pool.
    if last_seen > death_t_ms + POST_DEATH_FLASH_MS:
        # Soft join only if last_seen still within pool and we treat proximity to death.
        # Presence continuing past death is not a valid death-disappearance join.
        if last_seen <= death_t_ms + CANDIDATE_POOL_MS:
            # Weak proximity for ranking diagnostics, but temporal_join=False for promotion.
            return False, 0.0
        return False, 0.0
    delta = abs(last_seen - death_t_ms)
    if delta > CANDIDATE_POOL_MS:
        return False, 0.0
    # Linear decay: 0 at pool edge → W_TEMPORAL at exact death.
    score = W_TEMPORAL * (1.0 - (delta / float(CANDIDATE_POOL_MS)))
    return True, score


def _team_agrees(track: EntityTrack, *, subject_team_label: TeamEstimate | None) -> bool | None:
    if subject_team_label is None or subject_team_label is TeamEstimate.UNKNOWN:
        return None
    if track.team_estimate is TeamEstimate.UNKNOWN:
        return None
    return track.team_estimate is subject_team_label


def _reappearance_after_gap(track: EntityTrack, *, death_t_ms: int) -> bool:
    """True if the track vanishes near death then reappears later."""
    before = [obs for obs in track.observations if obs.game_t_ms <= death_t_ms]
    after = [
        obs for obs in track.observations if obs.game_t_ms > death_t_ms + POST_DEATH_ABSENCE_MS
    ]
    if not before or not after:
        return False
    last_before = before[-1].game_t_ms
    first_after = after[0].game_t_ms
    return first_after - last_before >= POST_DEATH_ABSENCE_MS
