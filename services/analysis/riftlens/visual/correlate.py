"""Optional reviewed-player correlation. UNKNOWN is the honest default.

Capture ownership and team color never imply participant identity.
Death-time alignment can support LIKELY. CORRELATED requires multiple
independent agreeing signals and no conflicts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from riftlens.domain.observation.enums import CameraControl, VisualClaimKind
from riftlens.visual.gst_align import DEATH_ALIGN_MS, GstAlignment, disappearing_near
from riftlens.visual.track import CandidateKind, EntityTrack, TeamEstimate

LIKELY_CONFIDENCE_CAP = 0.55
CORRELATED_CONFIDENCE_CAP = 0.75


class CorrelationStatus(StrEnum):
    CORRELATED = "CORRELATED"
    LIKELY = "LIKELY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SubjectCorrelation:
    """Inferred binding of a visual track to the reviewed participant."""

    status: CorrelationStatus
    track_id: str | None
    participant_id: int | None
    champion_id: str | None
    confidence: float
    method: str
    claim_kind: VisualClaimKind
    reasons: tuple[str, ...]
    conflicts: tuple[str, ...]

    @property
    def is_inferred(self) -> bool:
        return self.status is not CorrelationStatus.UNKNOWN


def correlate_subject(
    tracks: Sequence[EntityTrack],
    *,
    subject_pid: int | None,
    subject_champion: str | None = None,
    alignment: GstAlignment | None = None,
    camera_control: CameraControl = CameraControl.UNCONTROLLED,
    capture_review_pid: int | None = None,
    team_implies_identity: bool = False,
    subject_team_estimate: TeamEstimate | None = None,
    assume_subject_perspective_hud: bool = False,
) -> SubjectCorrelation:
    """Attempt subject binding. Weak or conflicting evidence stays UNKNOWN."""
    if capture_review_pid is not None and subject_pid is None:
        return _unknown("capture ownership never implies participant identity")
    if team_implies_identity:
        return _unknown("team classification alone never implies participant identity")
    if subject_pid is None:
        return _unknown("no subject participant id supplied")
    champion_like = [
        item for item in tracks if item.kind is CandidateKind.CHAMPION_LIKE and not item.ambiguous
    ]
    if not champion_like:
        return _unknown("no stable champion-like tracks")
    conflicts: list[str] = []
    reasons: list[str] = []
    if capture_review_pid is not None:
        reasons.append("capture_review_pid_ignored_for_identity")
    death_track, death_reasons, death_conflicts = _death_alignment(
        champion_like, alignment=alignment, subject_pid=subject_pid
    )
    reasons.extend(death_reasons)
    conflicts.extend(death_conflicts)
    if conflicts:
        return _unknown("conflicting evidence", conflicts=tuple(conflicts), reasons=tuple(reasons))
    if death_track is None:
        return _unknown(
            "death-time alignment insufficient; capture ownership ignored",
            reasons=tuple(reasons),
        )
    team_ok = _team_agrees(
        death_track,
        subject_team_estimate=subject_team_estimate,
        assume_subject_perspective_hud=assume_subject_perspective_hud,
    )
    if team_ok is False:
        return _unknown(
            "team estimate conflicts with subject team",
            conflicts=("team_mismatch",),
            reasons=tuple(reasons),
        )
    gst_conf = _gst_confidence(alignment, subject_pid)
    track_conf = death_track.confidence
    camera_locked = camera_control is CameraControl.CONTROLLED_SUBJECT
    if camera_locked and team_ok is True and gst_conf >= 0.9:
        reasons.append("camera_controlled_subject")
        reasons.append("subject_perspective_team_agrees")
        confidence = min(CORRELATED_CONFIDENCE_CAP, track_conf, gst_conf)
        return SubjectCorrelation(
            status=CorrelationStatus.CORRELATED,
            track_id=death_track.track_id,
            participant_id=subject_pid,
            champion_id=subject_champion,
            confidence=round(confidence, 3),
            method="death_alignment+team+controlled_camera",
            claim_kind=VisualClaimKind.INFERRED,
            reasons=tuple(reasons),
            conflicts=(),
        )
    confidence = min(LIKELY_CONFIDENCE_CAP, track_conf, gst_conf if gst_conf > 0 else 0.5)
    if subject_champion:
        reasons.append(f"subject_champion_metadata={subject_champion}")
    return SubjectCorrelation(
        status=CorrelationStatus.LIKELY,
        track_id=death_track.track_id,
        participant_id=subject_pid,
        champion_id=subject_champion,
        confidence=round(confidence, 3),
        method="gst_death_alignment",
        claim_kind=VisualClaimKind.INFERRED,
        reasons=tuple(reasons),
        conflicts=(),
    )


def _death_alignment(
    tracks: Sequence[EntityTrack],
    *,
    alignment: GstAlignment | None,
    subject_pid: int,
) -> tuple[EntityTrack | None, list[str], list[str]]:
    if alignment is None or alignment.subject is None:
        return None, ["no GST subject state"], []
    deaths = alignment.subject.deaths
    if not deaths:
        return None, ["no subject death in capture window"], []
    death_t = deaths[0]
    nearby = disappearing_near(tracks, death_t, window_ms=DEATH_ALIGN_MS)
    reasons = [f"subject_death_game_t_ms={death_t}", f"disappearing_tracks={len(nearby)}"]
    if not nearby:
        return None, reasons + ["no champion-like track disappeared near subject death"], []
    if len(nearby) > 1:
        return (
            None,
            reasons,
            [
                "multiple_tracks_disappeared_near_death:"
                + ",".join(item.track_id for item in nearby)
            ],
        )
    track = nearby[0]
    delta = abs(track.last_seen_game_t_ms - death_t)
    reasons.append(f"aligned_track={track.track_id} delta_ms={delta}")
    reasons.append("death alignment supports but does not prove identity")
    _ = subject_pid
    return track, reasons, []


def _team_agrees(
    track: EntityTrack,
    *,
    subject_team_estimate: TeamEstimate | None,
    assume_subject_perspective_hud: bool,
) -> bool | None:
    """Ally/enemy color is HUD-relative. Do not use it unless that is established."""
    if not assume_subject_perspective_hud:
        return None
    if subject_team_estimate is None or subject_team_estimate is TeamEstimate.UNKNOWN:
        return None
    if track.team_estimate is TeamEstimate.UNKNOWN:
        return None
    return track.team_estimate is subject_team_estimate


def _gst_confidence(alignment: GstAlignment | None, subject_pid: int) -> float:
    if alignment is None or alignment.subject is None:
        return 0.0
    if alignment.subject.participant_id != subject_pid:
        return 0.0
    if not alignment.subject.deaths:
        return 0.0
    if not alignment.kills:
        return 0.5
    death = next((item for item in alignment.kills if item.victim_id == subject_pid), None)
    if death is None:
        return 0.5
    return min(1.0, float(death.confidence))


def _unknown(
    reason: str,
    *,
    conflicts: tuple[str, ...] = (),
    reasons: tuple[str, ...] = (),
) -> SubjectCorrelation:
    notes = reasons if reasons else (reason,)
    if reason not in notes:
        notes = (*notes, reason)
    return SubjectCorrelation(
        status=CorrelationStatus.UNKNOWN,
        track_id=None,
        participant_id=None,
        champion_id=None,
        confidence=0.0,
        method="none",
        claim_kind=VisualClaimKind.INFERRED,
        reasons=notes,
        conflicts=conflicts,
    )
