from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from riftlens.domain.enums import Team
from riftlens.domain.observation.common import (
    ScreenRect,
    optional_rect,
    require_confidence,
    require_ulid,
)
from riftlens.domain.observation.enums import (
    CorrelationMethod,
    KnowledgeState,
    ObservationPayloadError,
    VisibilityState,
)


@dataclass(frozen=True)
class EntityObservation:
    """One champion-like (or other) entity seen or not seen in a frame.

    Participant identity and champion identity are independently optional.
    A detector may know a champion-like entity is visible without knowing
    which participant or which champion it is.
    """

    entity_observation_id: str
    visibility: VisibilityState
    confidence: float
    participant_id: int | None = None
    champion_id: str | None = None
    team: Team | None = None
    screen_region: ScreenRect | None = None
    occluded: bool | None = None
    correlation_method: CorrelationMethod = CorrelationMethod.NONE
    identity_knowledge: KnowledgeState = KnowledgeState.UNKNOWN
    participant_knowledge: KnowledgeState = KnowledgeState.UNKNOWN

    def __post_init__(self) -> None:
        require_ulid("entity_observation_id", self.entity_observation_id)
        require_confidence("entity.confidence", self.confidence)
        if self.participant_id is not None:
            if isinstance(self.participant_id, bool) or not isinstance(self.participant_id, int):
                raise ObservationPayloadError("entity.participant_id must be an int")
            if self.participant_id < 1:
                raise ObservationPayloadError("entity.participant_id must be >= 1")
        if self.champion_id is not None and not str(self.champion_id).strip():
            raise ObservationPayloadError("entity.champion_id must be non-empty when set")
        if self.champion_id is not None:
            object.__setattr__(self, "champion_id", str(self.champion_id).strip())
        if self.identity_knowledge is KnowledgeState.ABSENT and self.champion_id is not None:
            raise ObservationPayloadError("absent champion identity cannot carry champion_id")
        if self.participant_knowledge is KnowledgeState.ABSENT and self.participant_id is not None:
            raise ObservationPayloadError("absent participant cannot carry participant_id")
        if self.participant_id is not None and self.participant_knowledge is KnowledgeState.UNKNOWN:
            object.__setattr__(self, "participant_knowledge", KnowledgeState.KNOWN)
        if self.champion_id is not None and self.identity_knowledge is KnowledgeState.UNKNOWN:
            object.__setattr__(self, "identity_knowledge", KnowledgeState.KNOWN)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_observation_id": self.entity_observation_id,
            "visibility": self.visibility.value,
            "confidence": self.confidence,
            "participant_id": self.participant_id,
            "champion_id": self.champion_id,
            "team": None if self.team is None else int(self.team),
            "screen_region": None if self.screen_region is None else self.screen_region.to_dict(),
            "occluded": self.occluded,
            "correlation_method": self.correlation_method.value,
            "identity_knowledge": self.identity_knowledge.value,
            "participant_knowledge": self.participant_knowledge.value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EntityObservation:
        try:
            visibility = VisibilityState(str(payload["visibility"]))
            correlation = CorrelationMethod(
                str(payload.get("correlation_method", CorrelationMethod.NONE.value))
            )
            identity = KnowledgeState(
                str(payload.get("identity_knowledge", KnowledgeState.UNKNOWN.value))
            )
            participant_knowledge = KnowledgeState(
                str(payload.get("participant_knowledge", KnowledgeState.UNKNOWN.value))
            )
        except (KeyError, ValueError) as exc:
            raise ObservationPayloadError("entity payload is malformed") from exc
        team_raw = payload.get("team")
        team: Team | None
        if team_raw is None:
            team = None
        else:
            try:
                team = Team(int(team_raw))
            except ValueError as exc:
                raise ObservationPayloadError("entity.team is not a valid Team") from exc
        champion = payload.get("champion_id")
        return cls(
            entity_observation_id=str(payload.get("entity_observation_id", "")),
            visibility=visibility,
            confidence=require_confidence("entity.confidence", payload.get("confidence")),
            participant_id=_optional_pid(payload.get("participant_id")),
            champion_id=None if champion is None else str(champion),
            team=team,
            screen_region=optional_rect(payload.get("screen_region")),
            occluded=_optional_bool(payload.get("occluded")),
            correlation_method=correlation,
            identity_knowledge=identity,
            participant_knowledge=participant_knowledge,
        )


def _optional_pid(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ObservationPayloadError("entity.participant_id must be an int")
    return value


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ObservationPayloadError("entity.occluded must be a bool or null")
    return value
