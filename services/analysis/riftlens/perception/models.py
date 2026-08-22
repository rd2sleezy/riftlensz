"""RP.1 rich replay perception schemas.

Visual observations are not GST facts. Preserve source, confidence, provenance,
and UNKNOWN. Identity stays unset unless an external evidence source provides it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from riftlens.domain.enums import Source
from riftlens.domain.observation.common import ScreenRect

PERCEPTION_SCHEMA_VERSION = "rp1.0"
PERCEPTION_PRODUCER = "rp1_rich_replay_perception"
PERCEPTION_PRODUCER_VERSION = 1


class ObservationStatus(StrEnum):
    """How a visual field was established."""

    OBSERVED = "OBSERVED"
    DERIVED_VISUAL = "DERIVED_VISUAL"
    INFERRED_VISUAL = "INFERRED_VISUAL"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


class TeamClass(StrEnum):
    ALLY_LIKE = "ALLY_LIKE"
    ENEMY_LIKE = "ENEMY_LIKE"
    UNKNOWN = "UNKNOWN"


class CandidateKind(StrEnum):
    CHAMPION_CANDIDATE = "CHAMPION_CANDIDATE"
    MINION_CANDIDATE = "MINION_CANDIDATE"


class TrackState(StrEnum):
    ACTIVE = "ACTIVE"
    LOST = "LOST"
    AMBIGUOUS = "AMBIGUOUS"


class SlotAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class PerceptionCapabilityStatus(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class NormalizedPoint:
    x: float
    y: float

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y}


@dataclass(frozen=True)
class NormalizedRect:
    x: float
    y: float
    width: float
    height: float

    def to_dict(self) -> dict[str, float]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class VisualClaim:
    """One visual field with mandatory uncertainty."""

    status: ObservationStatus
    value: Any = None
    confidence: float | None = None
    source: Source = Source.VISUAL
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "value": self.value,
            "confidence": self.confidence,
            "source": self.source.value,
            "notes": self.notes,
        }


def unknown_claim(*, notes: str = "", source: Source = Source.VISUAL) -> VisualClaim:
    return VisualClaim(status=ObservationStatus.UNKNOWN, notes=notes, source=source)


def unavailable_claim(*, notes: str = "") -> VisualClaim:
    return VisualClaim(status=ObservationStatus.UNAVAILABLE, notes=notes)


@dataclass(frozen=True)
class FrameCaptureMeta:
    requested_game_t_ms: int
    actual_game_t_ms: int | None
    source_t_ms: int | None
    frame_id: str
    width: int
    height: int
    timing_error_ms: int | None
    provenance: str
    sync_uncertainty_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_game_t_ms": self.requested_game_t_ms,
            "actual_game_t_ms": self.actual_game_t_ms,
            "source_t_ms": self.source_t_ms,
            "frame_id": self.frame_id,
            "width": self.width,
            "height": self.height,
            "timing_error_ms": self.timing_error_ms,
            "sync_uncertainty_ms": self.sync_uncertainty_ms,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class BarCandidate:
    """Champion or minion health-bar-like candidate. Not a participant identity."""

    candidate_id: str
    kind: CandidateKind
    region: ScreenRect
    region_norm: NormalizedRect
    confidence: float
    team_class: TeamClass
    health_fraction: VisualClaim
    participant_id: None = None
    champion_id: None = None
    status: ObservationStatus = ObservationStatus.OBSERVED
    source: Source = Source.VISUAL
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "kind": self.kind.value,
            "region": self.region.to_dict(),
            "region_norm": self.region_norm.to_dict(),
            "confidence": self.confidence,
            "team_class": self.team_class.value,
            "health_fraction": self.health_fraction.to_dict(),
            "participant_id": self.participant_id,
            "champion_id": self.champion_id,
            "status": self.status.value,
            "source": self.source.value,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class PlayerHudState:
    usable: VisualClaim
    hp_fraction: VisualClaim
    resource_fraction: VisualClaim
    layout_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "usable": self.usable.to_dict(),
            "hp_fraction": self.hp_fraction.to_dict(),
            "resource_fraction": self.resource_fraction.to_dict(),
            "layout_notes": self.layout_notes,
        }


@dataclass(frozen=True)
class AbilitySlotRoi:
    slot_id: str
    region: ScreenRect
    region_norm: NormalizedRect
    availability: SlotAvailability
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "region": self.region.to_dict(),
            "region_norm": self.region_norm.to_dict(),
            "availability": self.availability.value,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class MinimapObservation:
    roi: ScreenRect
    roi_norm: NormalizedRect
    extracted: bool
    pip_candidates: tuple[NormalizedPoint, ...] = ()
    notes: str = "Minimap ROI only. No fog/jungle/identity claims."

    def to_dict(self) -> dict[str, Any]:
        return {
            "roi": self.roi.to_dict(),
            "roi_norm": self.roi_norm.to_dict(),
            "extracted": self.extracted,
            "pip_candidates": [item.to_dict() for item in self.pip_candidates],
            "notes": self.notes,
        }


@dataclass(frozen=True)
class VisualTrack:
    track_id: str
    kind: CandidateKind
    state: TrackState
    first_game_t_ms: int
    last_game_t_ms: int
    observation_count: int
    confidence: float
    team_class: TeamClass
    participant_id: None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "kind": self.kind.value,
            "state": self.state.value,
            "first_game_t_ms": self.first_game_t_ms,
            "last_game_t_ms": self.last_game_t_ms,
            "observation_count": self.observation_count,
            "confidence": self.confidence,
            "team_class": self.team_class.value,
            "participant_id": self.participant_id,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class PerceptionCapability:
    capability_id: str
    status: PerceptionCapabilityStatus
    evidence: str

    def to_dict(self) -> dict[str, str]:
        return {
            "capability_id": self.capability_id,
            "status": self.status.value,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class RichFrameObservation:
    """One frame of RP.1 perception. Parallel to R.11; does not mutate GST."""

    schema_version: str
    frame: FrameCaptureMeta
    champion_candidates: tuple[BarCandidate, ...]
    minion_candidates: tuple[BarCandidate, ...]
    player_hud: PlayerHudState
    ability_slots: tuple[AbilitySlotRoi, ...]
    minimap: MinimapObservation
    gaps: tuple[str, ...]
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "frame": self.frame.to_dict(),
            "champion_candidates": [item.to_dict() for item in self.champion_candidates],
            "minion_candidates": [item.to_dict() for item in self.minion_candidates],
            "player_hud": self.player_hud.to_dict(),
            "ability_slots": [item.to_dict() for item in self.ability_slots],
            "minimap": self.minimap.to_dict(),
            "gaps": list(self.gaps),
            "notes": list(self.notes),
            "gst_fact": False,
        }


@dataclass(frozen=True)
class RichReplayState:
    """Short-window aggregate for RP.2/RP.3 consumption."""

    schema_version: str
    requested_game_t_ms: int
    window_start_ms: int
    window_end_ms: int
    frames: tuple[RichFrameObservation, ...]
    tracks: tuple[VisualTrack, ...]
    capability_status: tuple[PerceptionCapability, ...]
    confidence_summary: dict[str, float] = field(default_factory=dict)
    gaps: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "requested_game_t_ms": self.requested_game_t_ms,
            "window_start_ms": self.window_start_ms,
            "window_end_ms": self.window_end_ms,
            "frames": [item.to_dict() for item in self.frames],
            "tracks": [item.to_dict() for item in self.tracks],
            "capability_status": [item.to_dict() for item in self.capability_status],
            "confidence_summary": dict(sorted(self.confidence_summary.items())),
            "gaps": list(self.gaps),
            "notes": list(self.notes),
            "gst_fact": False,
            "producer": PERCEPTION_PRODUCER,
            "producer_version": PERCEPTION_PRODUCER_VERSION,
        }
