"""V.5 subject-correlation refinement via trajectory/continuity cues.

Preserves V.1/V.4 CORRELATED requirements. Trajectory alone never upgrades
UNCONTROLLED captures to CORRELATED. Capture ownership never implies identity.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from riftlens.domain.observation.enums import CameraControl, VisualClaimKind
from riftlens.visual.continuity import ContinuityBundle, CueVerdict, evaluate_continuity
from riftlens.visual.correlate import (
    CORRELATED_CONFIDENCE_CAP,
    LIKELY_CONFIDENCE_CAP,
    CorrelationStatus,
    SubjectCorrelation,
)
from riftlens.visual.gst_align import GstAlignment
from riftlens.visual.track import CandidateKind, EntityTrack, TeamEstimate

# Small bump inside the LIKELY cap when ≥2 independent SUPPORT cues agree.
SUPPORT_BUMP = 0.05


@dataclass(frozen=True)
class V5CorrelationResult:
    """Base correlation plus V.5 continuity refinement."""

    base: SubjectCorrelation
    refined: SubjectCorrelation
    bundle: ContinuityBundle | None
    identity_change: str  # stronger | weaker | unchanged | cleared
    contributing_cues: tuple[str, ...]
    rejected_cues: tuple[str, ...]

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
            "bundle": None if self.bundle is None else self.bundle.to_dict(),
            "identity_change": self.identity_change,
            "contributing_cues": list(self.contributing_cues),
            "rejected_cues": list(self.rejected_cues),
        }


def refine_subject_correlation(
    base: SubjectCorrelation,
    tracks: Sequence[EntityTrack],
    *,
    alignment: GstAlignment | None,
    camera_control: CameraControl = CameraControl.UNCONTROLLED,
    subject_team_label: TeamEstimate | None = None,
) -> V5CorrelationResult:
    """Apply V.5 cues to an existing correlation. Fail closed on conflicts."""
    death_t = _subject_death_ms(alignment)
    if base.status is CorrelationStatus.UNKNOWN or base.track_id is None:
        # Trajectory alone cannot invent subject identity.
        return V5CorrelationResult(
            base=base,
            refined=base,
            bundle=None,
            identity_change="unchanged",
            contributing_cues=(),
            rejected_cues=("no_base_likely_track",),
        )
    track = _find_track(tracks, base.track_id)
    if track is None:
        return V5CorrelationResult(
            base=base,
            refined=_unknown_from(base, reason="base_track_missing"),
            bundle=None,
            identity_change="cleared",
            contributing_cues=(),
            rejected_cues=("base_track_missing",),
        )
    bundle = evaluate_continuity(
        track,
        death_t_ms=death_t,
        all_tracks=tracks,
        subject_team_label=subject_team_label,
    )
    contributing = tuple(
        f"{cue.cue_type.value}:{cue.reason}"
        for cue in bundle.cues
        if cue.verdict is CueVerdict.SUPPORT
    )
    rejected = tuple(
        f"{cue.cue_type.value}:{cue.reason}"
        for cue in bundle.cues
        if cue.verdict in {CueVerdict.CONFLICT, CueVerdict.REJECTED, CueVerdict.NEUTRAL}
    )
    # Hard conflicts clear LIKELY; CORRELATED only survives if camera-locked path
    # remains valid and no hard conflict.
    if bundle.conflict_count > 0:
        controlled = (
            base.status is CorrelationStatus.CORRELATED
            and camera_control is CameraControl.CONTROLLED_SUBJECT
        )
        if controlled:
            # Controlled-camera CORRELATED still fails closed on hard continuity conflict.
            refined = _unknown_from(
                base,
                reason="v5_continuity_conflict",
                conflicts=tuple(
                    cue.reason for cue in bundle.cues if cue.verdict is CueVerdict.CONFLICT
                ),
            )
            return V5CorrelationResult(
                base=base,
                refined=refined,
                bundle=bundle,
                identity_change="cleared",
                contributing_cues=contributing,
                rejected_cues=rejected,
            )
        refined = _unknown_from(
            base,
            reason="v5_continuity_conflict",
            conflicts=tuple(
                cue.reason for cue in bundle.cues if cue.verdict is CueVerdict.CONFLICT
            ),
        )
        return V5CorrelationResult(
            base=base,
            refined=refined,
            bundle=bundle,
            identity_change="cleared",
            contributing_cues=contributing,
            rejected_cues=rejected,
        )

    # Never invent CORRELATED from trajectory under uncontrolled camera.
    if base.status is CorrelationStatus.CORRELATED:
        return V5CorrelationResult(
            base=base,
            refined=base,
            bundle=bundle,
            identity_change="unchanged",
            contributing_cues=contributing,
            rejected_cues=rejected,
        )

    # LIKELY path: optional small bump inside LIKELY cap when ≥2 SUPPORT cues.
    conf = float(base.confidence)
    reasons = list(base.reasons)
    if bundle.support_count >= 2:
        conf = min(LIKELY_CONFIDENCE_CAP, conf + SUPPORT_BUMP)
        reasons.append(f"v5_support_cues={bundle.support_count}")
        identity_change = "stronger" if conf > float(base.confidence) else "unchanged"
    elif bundle.support_count == 1:
        reasons.append("v5_single_support_cue_no_bump")
        identity_change = "unchanged"
    else:
        reasons.append("v5_no_supporting_cues")
        identity_change = "unchanged"
    # Uncontrolled camera remains a hard CORRELATED block.
    _ = CORRELATED_CONFIDENCE_CAP
    if camera_control is not CameraControl.CONTROLLED_SUBJECT:
        reasons.append("uncontrolled_camera_caps_at_likely")
    refined = replace(
        base,
        confidence=round(conf, 3),
        method=f"{base.method}+v5_continuity",
        reasons=tuple(reasons),
        claim_kind=VisualClaimKind.INFERRED,
    )
    return V5CorrelationResult(
        base=base,
        refined=refined,
        bundle=bundle,
        identity_change=identity_change,
        contributing_cues=contributing,
        rejected_cues=rejected,
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


def _unknown_from(
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
        method="v5_fail_closed",
        claim_kind=VisualClaimKind.INFERRED,
        reasons=(*base.reasons, reason),
        conflicts=conflicts if conflicts else (reason,),
    )
