"""V.6 subject correlation via death-window candidate ranking.

Can promote UNKNOWN → LIKELY when a unique scored winner has a GST temporal
join plus ≥1 independent support. Never invents CORRELATED. Never treats
camera ownership or subject attachment as identity.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from riftlens.domain.observation.enums import CameraControl, VisualClaimKind
from riftlens.visual.correlate import (
    CORRELATED_CONFIDENCE_CAP,
    LIKELY_CONFIDENCE_CAP,
    CorrelationStatus,
    SubjectCorrelation,
)
from riftlens.visual.correlate_v5 import V5CorrelationResult
from riftlens.visual.death_candidate import DeathCandidateRanking, rank_death_candidates
from riftlens.visual.gst_align import GstAlignment
from riftlens.visual.track import CandidateKind, EntityTrack, TeamEstimate


@dataclass(frozen=True)
class V6CorrelationResult:
    """V.5 (or V.4) base plus optional V.6 ranking promotion."""

    base: SubjectCorrelation
    refined: SubjectCorrelation
    ranking: DeathCandidateRanking | None
    identity_change: str  # stronger | weaker | unchanged | cleared | promoted
    winner_margin: float
    reasons: tuple[str, ...]
    conflicts: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "base": {
                "status": self.base.status.value,
                "track_id": self.base.track_id,
                "confidence": self.base.confidence,
                "method": self.base.method,
            },
            "refined": {
                "status": self.refined.status.value,
                "track_id": self.refined.track_id,
                "confidence": self.refined.confidence,
                "method": self.refined.method,
                "reasons": list(self.refined.reasons),
                "conflicts": list(self.refined.conflicts),
            },
            "ranking": None if self.ranking is None else self.ranking.to_dict(),
            "identity_change": self.identity_change,
            "winner_margin": self.winner_margin,
            "reasons": list(self.reasons),
            "conflicts": list(self.conflicts),
        }


def refine_with_death_ranking(
    base: SubjectCorrelation,
    tracks: Sequence[EntityTrack],
    *,
    alignment: GstAlignment | None,
    subject_pid: int | None,
    subject_champion: str | None = None,
    camera_control: CameraControl = CameraControl.UNCONTROLLED,
    subject_team_label: TeamEstimate | None = None,
    camera_implies_identity: bool = False,
    subject_attachment_implies_identity: bool = False,
) -> V6CorrelationResult:
    """Apply V.6 ranking. CORRELATED remains blocked unless already present and valid."""
    _ = CORRELATED_CONFIDENCE_CAP  # documented ceiling; V.6 never upgrades to it
    death_t = _subject_death_ms(alignment)
    if death_t is None or subject_pid is None:
        return V6CorrelationResult(
            base=base,
            refined=base,
            ranking=None,
            identity_change="unchanged",
            winner_margin=0.0,
            reasons=("no_gst_death_or_subject",),
            conflicts=(),
        )

    ranking = rank_death_candidates(
        tracks,
        death_t_ms=death_t,
        subject_team_label=subject_team_label,
        camera_implies_identity=camera_implies_identity,
        subject_attachment_implies_identity=subject_attachment_implies_identity,
    )

    ownership_reject = "camera_ownership_or_subject_attachment_alone_never_implies_identity"
    if ranking.reject_reason == ownership_reject:
        cleared = base.status is not CorrelationStatus.UNKNOWN
        return V6CorrelationResult(
            base=base,
            refined=_unknown(base, reason=ownership_reject, conflicts=(ownership_reject,)),
            ranking=ranking,
            identity_change="cleared" if cleared else "unchanged",
            winner_margin=0.0,
            reasons=(ownership_reject,),
            conflicts=(ownership_reject,),
        )

    # Preserve existing CORRELATED only; V.6 never creates it.
    if base.status is CorrelationStatus.CORRELATED:
        if camera_control is not CameraControl.CONTROLLED_SUBJECT:
            return V6CorrelationResult(
                base=base,
                refined=_unknown(base, reason="v6_correlated_requires_controlled_subject"),
                ranking=ranking,
                identity_change="cleared",
                winner_margin=ranking.winner_margin,
                reasons=("v6_correlated_requires_controlled_subject",),
                conflicts=("uncontrolled_camera",),
            )
        return V6CorrelationResult(
            base=base,
            refined=base,
            ranking=ranking,
            identity_change="unchanged",
            winner_margin=ranking.winner_margin,
            reasons=("preserved_existing_correlated",),
            conflicts=(),
        )

    # Existing LIKELY: confirm if ranking agrees; clear on hard disagreement.
    if base.status is CorrelationStatus.LIKELY and base.track_id is not None:
        if ranking.winner_track_id is None:
            return V6CorrelationResult(
                base=base,
                refined=base,
                ranking=ranking,
                identity_change="unchanged",
                winner_margin=ranking.winner_margin,
                reasons=("kept_base_likely_ranking_no_unique_winner",),
                conflicts=(),
            )
        if ranking.winner_track_id != base.track_id:
            return V6CorrelationResult(
                base=base,
                refined=_unknown(
                    base,
                    reason="v6_ranking_disagrees_with_base_likely",
                    conflicts=(f"base={base.track_id}", f"v6={ranking.winner_track_id}"),
                ),
                ranking=ranking,
                identity_change="cleared",
                winner_margin=ranking.winner_margin,
                reasons=("v6_ranking_disagrees_with_base_likely",),
                conflicts=(f"base={base.track_id}", f"v6={ranking.winner_track_id}"),
            )
        return V6CorrelationResult(
            base=base,
            refined=base,
            ranking=ranking,
            identity_change="unchanged",
            winner_margin=ranking.winner_margin,
            reasons=("confirmed_base_likely",),
            conflicts=(),
        )

    # UNKNOWN → maybe LIKELY
    if ranking.winner_track_id is None:
        return V6CorrelationResult(
            base=base,
            refined=base,
            ranking=ranking,
            identity_change="unchanged",
            winner_margin=ranking.winner_margin,
            reasons=(ranking.reject_reason or "no_v6_winner",),
            conflicts=(),
        )

    winner = next(
        (item for item in ranking.candidates if item.track_id == ranking.winner_track_id),
        None,
    )
    if winner is None:
        return V6CorrelationResult(
            base=base,
            refined=base,
            ranking=ranking,
            identity_change="unchanged",
            winner_margin=ranking.winner_margin,
            reasons=("winner_missing_from_board",),
            conflicts=(),
        )

    track = _find_track(tracks, ranking.winner_track_id)
    if track is None:
        return V6CorrelationResult(
            base=base,
            refined=base,
            ranking=ranking,
            identity_change="unchanged",
            winner_margin=ranking.winner_margin,
            reasons=("winner_track_missing",),
            conflicts=(),
        )

    conf = min(LIKELY_CONFIDENCE_CAP, float(track.confidence), max(0.35, winner.score))
    reasons = [
        f"subject_death_game_t_ms={death_t}",
        f"v6_winner={winner.track_id}",
        f"v6_score={winner.score}",
        f"v6_margin={ranking.winner_margin}",
        f"v6_supports={','.join(winner.supports)}",
        "v6_death_candidate_ranking",
        "death ranking supports but does not prove identity",
    ]
    if subject_champion:
        reasons.append(f"subject_champion_metadata={subject_champion}")
    if camera_control is not CameraControl.CONTROLLED_SUBJECT:
        reasons.append("uncontrolled_or_unproven_camera_caps_at_likely")

    refined = SubjectCorrelation(
        status=CorrelationStatus.LIKELY,
        track_id=winner.track_id,
        participant_id=subject_pid,
        champion_id=subject_champion,
        confidence=round(min(LIKELY_CONFIDENCE_CAP, conf), 3),
        method="v6_death_candidate_ranking",
        claim_kind=VisualClaimKind.INFERRED,
        reasons=tuple(reasons),
        conflicts=(),
    )
    if refined.confidence > LIKELY_CONFIDENCE_CAP:
        refined = replace(refined, confidence=LIKELY_CONFIDENCE_CAP)

    return V6CorrelationResult(
        base=base,
        refined=refined,
        ranking=ranking,
        identity_change="promoted",
        winner_margin=ranking.winner_margin,
        reasons=tuple(reasons),
        conflicts=(),
    )


def apply_v6_to_v5(
    v5: V5CorrelationResult,
    tracks: Sequence[EntityTrack],
    *,
    alignment: GstAlignment | None,
    subject_pid: int | None,
    subject_champion: str | None = None,
    camera_control: CameraControl = CameraControl.UNCONTROLLED,
    subject_team_label: TeamEstimate | None = None,
    camera_implies_identity: bool = False,
    subject_attachment_implies_identity: bool = False,
) -> V6CorrelationResult:
    """Rank on top of V.5 refined correlation."""
    return refine_with_death_ranking(
        v5.refined,
        tracks,
        alignment=alignment,
        subject_pid=subject_pid,
        subject_champion=subject_champion,
        camera_control=camera_control,
        subject_team_label=subject_team_label,
        camera_implies_identity=camera_implies_identity,
        subject_attachment_implies_identity=subject_attachment_implies_identity,
    )


def _subject_death_ms(alignment: GstAlignment | None) -> int | None:
    if alignment is None or alignment.subject is None or not alignment.subject.deaths:
        return None
    return int(alignment.subject.deaths[0])


def _find_track(tracks: Sequence[EntityTrack], track_id: str) -> EntityTrack | None:
    for track in tracks:
        if track.track_id == track_id and track.kind is CandidateKind.CHAMPION_LIKE:
            return track
    return None


def _unknown(
    base: SubjectCorrelation,
    *,
    reason: str,
    conflicts: tuple[str, ...] = (),
) -> SubjectCorrelation:
    return SubjectCorrelation(
        status=CorrelationStatus.UNKNOWN,
        track_id=None,
        participant_id=None,
        champion_id=None,
        confidence=0.0,
        method="v6_fail_closed",
        claim_kind=VisualClaimKind.INFERRED,
        reasons=(*base.reasons, reason),
        conflicts=conflicts if conflicts else (reason,),
    )
