from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from riftlens.domain.observation.common import ScreenRect, optional_rect
from riftlens.domain.observation.enums import KnowledgeState, ObservationPayloadError

_COACHING_TERMS = frozenset(
    {
        "bad positioning",
        "overextended",
        "unsafe fight",
        "bad fight",
        "successful rotation",
        "threw",
        "inting",
        "greedy",
        "should have",
    }
)


@dataclass(frozen=True)
class SpatialObservation:
    """Bounded visual-context observations. Coaching judgments are rejected."""

    knowledge: KnowledgeState = KnowledgeState.UNKNOWN
    relative_screen_position: tuple[float, float] | None = None
    turret_presence: KnowledgeState = KnowledgeState.UNKNOWN
    objective_presence: KnowledgeState = KnowledgeState.UNKNOWN
    ward_indicators: KnowledgeState = KnowledgeState.UNKNOWN
    grouping: KnowledgeState = KnowledgeState.UNKNOWN
    movement_direction: tuple[float, float] | None = None
    minimap_visible: KnowledgeState = KnowledgeState.UNKNOWN
    region: ScreenRect | None = None
    labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "relative_screen_position", _optional_vec2(self.relative_screen_position)
        )
        object.__setattr__(self, "movement_direction", _optional_vec2(self.movement_direction))
        cleaned: list[str] = []
        for label in self.labels:
            text = str(label).strip()
            if not text:
                raise ObservationPayloadError("spatial label must be non-empty")
            if text.casefold() in _COACHING_TERMS:
                raise ObservationPayloadError(
                    f"spatial label {text!r} is a coaching judgment, not an observation"
                )
            cleaned.append(text)
        object.__setattr__(self, "labels", tuple(cleaned))
        if self.knowledge is KnowledgeState.UNOBSERVABLE:
            if self.relative_screen_position is not None or self.movement_direction is not None:
                raise ObservationPayloadError("UNOBSERVABLE spatial state cannot carry positions")

    def to_dict(self) -> dict[str, Any]:
        return {
            "knowledge": self.knowledge.value,
            "relative_screen_position": _vec_payload(self.relative_screen_position),
            "turret_presence": self.turret_presence.value,
            "objective_presence": self.objective_presence.value,
            "ward_indicators": self.ward_indicators.value,
            "grouping": self.grouping.value,
            "movement_direction": _vec_payload(self.movement_direction),
            "minimap_visible": self.minimap_visible.value,
            "region": None if self.region is None else self.region.to_dict(),
            "labels": list(self.labels),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SpatialObservation:
        try:
            knowledge = KnowledgeState(str(payload.get("knowledge", KnowledgeState.UNKNOWN.value)))
            turret = KnowledgeState(
                str(payload.get("turret_presence", KnowledgeState.UNKNOWN.value))
            )
            objective = KnowledgeState(
                str(payload.get("objective_presence", KnowledgeState.UNKNOWN.value))
            )
            wards = KnowledgeState(
                str(payload.get("ward_indicators", KnowledgeState.UNKNOWN.value))
            )
            grouping = KnowledgeState(str(payload.get("grouping", KnowledgeState.UNKNOWN.value)))
            minimap = KnowledgeState(
                str(payload.get("minimap_visible", KnowledgeState.UNKNOWN.value))
            )
        except ValueError as exc:
            raise ObservationPayloadError("spatial payload is malformed") from exc
        labels_raw = payload.get("labels", [])
        if labels_raw is None:
            labels: Sequence[str] = ()
        elif isinstance(labels_raw, Sequence) and not isinstance(labels_raw, (str, bytes)):
            labels = tuple(str(item) for item in labels_raw)
        else:
            raise ObservationPayloadError("spatial.labels must be an array")
        return cls(
            knowledge=knowledge,
            relative_screen_position=_load_vec2(payload.get("relative_screen_position")),
            turret_presence=turret,
            objective_presence=objective,
            ward_indicators=wards,
            grouping=grouping,
            movement_direction=_load_vec2(payload.get("movement_direction")),
            minimap_visible=minimap,
            region=optional_rect(payload.get("region")),
            labels=tuple(labels),
        )


def _optional_vec2(value: tuple[float, float] | None) -> tuple[float, float] | None:
    if value is None:
        return None
    if len(value) != 2:
        raise ObservationPayloadError("spatial vector must have two components")
    x, y = float(value[0]), float(value[1])
    if x != x or y != y or x in (float("inf"), float("-inf")) or y in (float("inf"), float("-inf")):
        raise ObservationPayloadError("spatial vector must be finite")
    return (x, y)


def _load_vec2(value: object) -> tuple[float, float] | None:
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        raise ObservationPayloadError("spatial vector must be a two-number array")
    return _optional_vec2((float(value[0]), float(value[1])))


def _vec_payload(value: tuple[float, float] | None) -> list[float] | None:
    if value is None:
        return None
    return [value[0], value[1]]
