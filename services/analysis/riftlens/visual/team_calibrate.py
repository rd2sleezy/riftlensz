"""Spectator team-color calibration. Maps observed bar hues to Riot teams.

League free-spectator health bars are team-absolute (blue side ≈ blue hue,
red side ≈ red hue), not green=ally / red=enemy from live play. Calibration
is VISUAL_INFERRED and must not overwrite GST team truth.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from riftlens.domain.enums import Team
from riftlens.visual.color_sample import (
    BarColorSample,
    hue_is_blue_like,
    hue_is_green_like,
    hue_is_red_like,
)
from riftlens.visual.correlate import CorrelationStatus, SubjectCorrelation
from riftlens.visual.track import CandidateKind, EntityTrack, TeamEstimate, TrackObservation

CALIBRATION_VERSION = "v4.0"
TEAM_COLOR_CONFIDENCE_CAP = 0.7


class CalibrationConfidence(StrEnum):
    UNAVAILABLE = "UNAVAILABLE"
    WEAK = "WEAK"
    GOOD = "GOOD"
    VERIFIED = "VERIFIED"


class SpectatorColorClass(StrEnum):
    """Observed bar color cluster before relative ALLY/ENEMY mapping."""

    RED_LIKE = "RED_LIKE"
    BLUE_LIKE = "BLUE_LIKE"
    GREEN_LIKE = "GREEN_LIKE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TeamColorAnchor:
    """One evidence link from a visual color sample to a Riot team id."""

    track_id: str
    riot_team: Team
    color: SpectatorColorClass
    confidence: float
    reason: str


@dataclass(frozen=True)
class TeamCalibration:
    """Mapping from spectator color clusters to Riot teams."""

    version: str
    confidence: CalibrationConfidence
    subject_team: Team | None
    red_like_team: Team | None
    blue_like_team: Team | None
    green_like_team: Team | None
    anchors: tuple[TeamColorAnchor, ...]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "confidence": self.confidence.value,
            "subject_team": None if self.subject_team is None else int(self.subject_team),
            "red_like_team": None if self.red_like_team is None else int(self.red_like_team),
            "blue_like_team": None if self.blue_like_team is None else int(self.blue_like_team),
            "green_like_team": None if self.green_like_team is None else int(self.green_like_team),
            "anchor_count": len(self.anchors),
            "anchors": [
                {
                    "track_id": item.track_id,
                    "riot_team": int(item.riot_team),
                    "color": item.color.value,
                    "confidence": item.confidence,
                    "reason": item.reason,
                }
                for item in self.anchors
            ],
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class TrackTeamLabel:
    team_class: TeamEstimate
    riot_team: Team | None
    color_class: SpectatorColorClass
    confidence: float
    evidence_count: int
    calibration_version: str


def classify_color_sample(sample: BarColorSample) -> SpectatorColorClass:
    """Map a bar HSV sample to a spectator color cluster."""
    if not sample.usable or sample.sat_median < 80 or sample.val_median < 80:
        return SpectatorColorClass.UNKNOWN
    hue = sample.hue_median
    if hue_is_red_like(hue):
        return SpectatorColorClass.RED_LIKE
    if hue_is_blue_like(hue):
        return SpectatorColorClass.BLUE_LIKE
    if hue_is_green_like(hue):
        return SpectatorColorClass.GREEN_LIKE
    return SpectatorColorClass.UNKNOWN


def build_calibration(
    *,
    subject_team: Team | None,
    correlation: SubjectCorrelation | None,
    track_colors: dict[str, SpectatorColorClass],
    extra_anchors: Sequence[TeamColorAnchor] = (),
) -> TeamCalibration:
    """Infer color→Riot-team mapping. Weak/single LIKELY anchors stay WEAK."""
    reasons: list[str] = []
    anchors: list[TeamColorAnchor] = list(extra_anchors)
    if subject_team is None:
        reasons.append("no subject Riot team")
        return TeamCalibration(
            version=CALIBRATION_VERSION,
            confidence=CalibrationConfidence.UNAVAILABLE,
            subject_team=None,
            red_like_team=None,
            blue_like_team=None,
            green_like_team=None,
            anchors=tuple(anchors),
            reasons=tuple(reasons),
        )
    if correlation is not None and correlation.status is not CorrelationStatus.UNKNOWN:
        if correlation.track_id and correlation.track_id in track_colors:
            color = track_colors[correlation.track_id]
            if color is not SpectatorColorClass.UNKNOWN:
                anchors.append(
                    TeamColorAnchor(
                        track_id=correlation.track_id,
                        riot_team=subject_team,
                        color=color,
                        confidence=min(float(correlation.confidence), 0.55),
                        reason=f"subject_{correlation.status.value.lower()}_track_color",
                    )
                )
                reasons.append(
                    f"subject anchor {correlation.track_id} color={color.value} "
                    f"-> team {int(subject_team)}"
                )
            else:
                reasons.append("subject track color unusable")
        else:
            reasons.append("subject correlation track missing color sample")
    if not anchors:
        # Spectator default prior: blue hue → team 100, red hue → team 200.
        # Marked WEAK — empirical default, not a verified match-specific map.
        reasons.append("no anchors; using spectator team-absolute prior (WEAK)")
        return TeamCalibration(
            version=CALIBRATION_VERSION,
            confidence=CalibrationConfidence.WEAK,
            subject_team=subject_team,
            red_like_team=Team.RED,
            blue_like_team=Team.BLUE,
            green_like_team=None,
            anchors=(),
            reasons=tuple(reasons),
        )
    red_votes = [
        item.riot_team for item in anchors if item.color is SpectatorColorClass.RED_LIKE
    ]
    blue_votes = [
        item.riot_team for item in anchors if item.color is SpectatorColorClass.BLUE_LIKE
    ]
    green_votes = [
        item.riot_team for item in anchors if item.color is SpectatorColorClass.GREEN_LIKE
    ]
    red_team = _consensus_team(red_votes)
    blue_team = _consensus_team(blue_votes)
    green_team = _consensus_team(green_votes)
    if red_team is None and blue_team is None and green_team is None:
        reasons.append("anchors conflict or empty after consensus")
        return TeamCalibration(
            version=CALIBRATION_VERSION,
            confidence=CalibrationConfidence.UNAVAILABLE,
            subject_team=subject_team,
            red_like_team=None,
            blue_like_team=None,
            green_like_team=None,
            anchors=tuple(anchors),
            reasons=tuple(reasons),
        )
    # Fill the opposite team when only one cluster is anchored.
    if red_team is not None and blue_team is None:
        blue_team = Team.BLUE if red_team is Team.RED else Team.RED
        reasons.append(f"inferred opposite blue_like -> team {int(blue_team)}")
    if blue_team is not None and red_team is None:
        red_team = Team.RED if blue_team is Team.BLUE else Team.BLUE
        reasons.append(f"inferred opposite red_like -> team {int(red_team)}")
    if red_team is not None and blue_team is not None and red_team is blue_team:
        reasons.append("red/blue map conflict")
        return TeamCalibration(
            version=CALIBRATION_VERSION,
            confidence=CalibrationConfidence.UNAVAILABLE,
            subject_team=subject_team,
            red_like_team=None,
            blue_like_team=None,
            green_like_team=green_team,
            anchors=tuple(anchors),
            reasons=tuple(reasons),
        )
    max_anchor = max(item.confidence for item in anchors)
    distinct_colors = {item.color for item in anchors}
    if (
        len(anchors) >= 2
        and len(distinct_colors) >= 2
        and max_anchor >= 0.75
        and all(item.confidence >= 0.7 for item in anchors)
    ):
        confidence = CalibrationConfidence.VERIFIED
    elif len(anchors) >= 2 and len(distinct_colors) >= 2 and max_anchor >= 0.55:
        confidence = CalibrationConfidence.GOOD
    elif len(anchors) >= 2 and max_anchor >= 0.7:
        confidence = CalibrationConfidence.GOOD
    elif max_anchor <= 0.55 and len(anchors) == 1:
        # Single LIKELY subject anchor — useful but not VERIFIED.
        confidence = CalibrationConfidence.WEAK
        # Still apply spectator prior for the unanchored opposite color.
        if red_team is None:
            red_team = Team.RED
        if blue_team is None:
            blue_team = Team.BLUE
    else:
        confidence = CalibrationConfidence.WEAK
    return TeamCalibration(
        version=CALIBRATION_VERSION,
        confidence=confidence,
        subject_team=subject_team,
        red_like_team=red_team,
        blue_like_team=blue_team,
        green_like_team=green_team,
        anchors=tuple(anchors),
        reasons=tuple(reasons),
    )


def relative_team(
    riot_team: Team | None,
    *,
    subject_team: Team | None,
) -> TeamEstimate:
    """ALLY/ENEMY relative to the reviewed subject. Never invents a team."""
    if riot_team is None or subject_team is None:
        return TeamEstimate.UNKNOWN
    if riot_team is subject_team:
        return TeamEstimate.ALLY
    return TeamEstimate.ENEMY


def label_track(
    track: EntityTrack,
    samples: Sequence[BarColorSample],
    calibration: TeamCalibration,
) -> TrackTeamLabel:
    """Aggregate per-observation colors into one track team label."""
    colors = [classify_color_sample(item) for item in samples if item.usable]
    usable = [item for item in colors if item is not SpectatorColorClass.UNKNOWN]
    if not usable or calibration.confidence is CalibrationConfidence.UNAVAILABLE:
        return TrackTeamLabel(
            team_class=TeamEstimate.UNKNOWN,
            riot_team=None,
            color_class=SpectatorColorClass.UNKNOWN,
            confidence=0.0,
            evidence_count=len(usable),
            calibration_version=calibration.version,
        )
    # Majority color; ties → UNKNOWN.
    counts = {
        SpectatorColorClass.RED_LIKE: usable.count(SpectatorColorClass.RED_LIKE),
        SpectatorColorClass.BLUE_LIKE: usable.count(SpectatorColorClass.BLUE_LIKE),
        SpectatorColorClass.GREEN_LIKE: usable.count(SpectatorColorClass.GREEN_LIKE),
    }
    top = max(counts.values())
    leaders = [key for key, value in counts.items() if value == top and value > 0]
    if len(leaders) != 1:
        return TrackTeamLabel(
            team_class=TeamEstimate.UNKNOWN,
            riot_team=None,
            color_class=SpectatorColorClass.UNKNOWN,
            confidence=0.0,
            evidence_count=len(usable),
            calibration_version=calibration.version,
        )
    color = leaders[0]
    # Conflict: substantial minority of the opposite primary color.
    if color is SpectatorColorClass.RED_LIKE and counts[SpectatorColorClass.BLUE_LIKE] >= max(
        1, top // 2
    ):
        return TrackTeamLabel(
            team_class=TeamEstimate.UNKNOWN,
            riot_team=None,
            color_class=SpectatorColorClass.UNKNOWN,
            confidence=0.0,
            evidence_count=len(usable),
            calibration_version=calibration.version,
        )
    if color is SpectatorColorClass.BLUE_LIKE and counts[SpectatorColorClass.RED_LIKE] >= max(
        1, top // 2
    ):
        return TrackTeamLabel(
            team_class=TeamEstimate.UNKNOWN,
            riot_team=None,
            color_class=SpectatorColorClass.UNKNOWN,
            confidence=0.0,
            evidence_count=len(usable),
            calibration_version=calibration.version,
        )
    riot = _riot_for_color(color, calibration)
    team_class = relative_team(riot, subject_team=calibration.subject_team)
    base = 0.35 + 0.08 * min(len(usable), 6)
    if calibration.confidence is CalibrationConfidence.GOOD:
        base += 0.15
    elif calibration.confidence is CalibrationConfidence.VERIFIED:
        base += 0.2
    elif calibration.confidence is CalibrationConfidence.WEAK:
        base += 0.05
    if track.observation_count <= 1:
        base = min(base, 0.4)
    # Downstream team confidence cannot exceed weak-anchor evidence alone.
    if calibration.confidence is CalibrationConfidence.WEAK:
        max_anchor = max((item.confidence for item in calibration.anchors), default=0.55)
        base = min(base, max_anchor, 0.55)
    confidence = round(min(TEAM_COLOR_CONFIDENCE_CAP, base), 3)
    if team_class is TeamEstimate.UNKNOWN:
        confidence = 0.0
    return TrackTeamLabel(
        team_class=team_class,
        riot_team=riot,
        color_class=color,
        confidence=confidence,
        evidence_count=len(usable),
        calibration_version=calibration.version,
    )


def apply_labels_to_tracks(
    tracks: Sequence[EntityTrack],
    labels: dict[str, TrackTeamLabel],
) -> tuple[EntityTrack, ...]:
    """Return tracks with calibrated team fields. Does not mutate inputs."""
    out: list[EntityTrack] = []
    for track in tracks:
        label = labels.get(track.track_id)
        if label is None or track.kind is not CandidateKind.CHAMPION_LIKE:
            out.append(track)
            continue
        observations = tuple(
            TrackObservation(
                frame_index=item.frame_index,
                game_t_ms=item.game_t_ms,
                region=item.region,
                confidence=item.confidence,
                lifecycle=item.lifecycle,
                team_estimate=label.team_class,
                team_confidence=label.confidence,
            )
            for item in track.observations
        )
        out.append(
            replace(
                track,
                observations=observations,
                team_estimate=label.team_class,
                team_confidence=label.confidence,
            )
        )
    return tuple(out)


def majority_track_color(
    samples: Sequence[BarColorSample],
) -> SpectatorColorClass:
    """Majority usable color for a track, or UNKNOWN."""
    colors = [classify_color_sample(item) for item in samples if item.usable]
    usable = [item for item in colors if item is not SpectatorColorClass.UNKNOWN]
    if not usable:
        return SpectatorColorClass.UNKNOWN
    return max(set(usable), key=usable.count)


def _consensus_team(votes: Sequence[Team]) -> Team | None:
    if not votes:
        return None
    if any(item is not votes[0] for item in votes):
        return None
    return votes[0]


def _riot_for_color(
    color: SpectatorColorClass, calibration: TeamCalibration
) -> Team | None:
    if color is SpectatorColorClass.RED_LIKE:
        return calibration.red_like_team
    if color is SpectatorColorClass.BLUE_LIKE:
        return calibration.blue_like_team
    if color is SpectatorColorClass.GREEN_LIKE:
        return calibration.green_like_team
    return None
