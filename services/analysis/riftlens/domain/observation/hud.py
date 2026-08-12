from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from riftlens.domain.observation.common import (
    ScreenRect,
    optional_confidence,
    optional_rect,
    require_confidence,
)
from riftlens.domain.observation.enums import KnowledgeState, ObservationPayloadError

HudScalar = float | int | str | bool

KNOWN_HUD_FIELDS = (
    "health",
    "resource",
    "level",
    "cs",
    "gold",
    "items",
    "abilities",
    "ability_cooldowns",
    "summoner_spells",
    "death_state",
    "scoreboard",
)


@dataclass(frozen=True)
class HudValue:
    """One HUD readout. Missing/unknown stays missing; no fabricated defaults."""

    knowledge: KnowledgeState
    value: HudScalar | None = None
    confidence: float | None = None
    region: ScreenRect | None = None

    def __post_init__(self) -> None:
        if self.confidence is not None:
            require_confidence("hud.confidence", self.confidence)
        if self.knowledge is KnowledgeState.UNKNOWN and self.value is not None:
            raise ObservationPayloadError("UNKNOWN HUD value cannot carry an observed value")
        if self.knowledge is KnowledgeState.UNOBSERVABLE and self.value is not None:
            raise ObservationPayloadError("UNOBSERVABLE HUD value cannot carry an observed value")
        if self.knowledge is KnowledgeState.ABSENT and self.value is not None:
            raise ObservationPayloadError("ABSENT HUD value cannot carry an observed value")
        if self.knowledge is KnowledgeState.KNOWN and self.value is None:
            raise ObservationPayloadError("KNOWN HUD value requires an observed value")
        if self.value is not None and not isinstance(self.value, (int, float, str, bool)):
            raise ObservationPayloadError("HUD value must be a JSON scalar")
        if isinstance(self.value, float) and (
            self.value != self.value or self.value in (float("inf"), float("-inf"))
        ):
            raise ObservationPayloadError("HUD numeric value must be finite")

    def to_dict(self) -> dict[str, Any]:
        return {
            "knowledge": self.knowledge.value,
            "value": self.value,
            "confidence": self.confidence,
            "region": None if self.region is None else self.region.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> HudValue:
        try:
            knowledge = KnowledgeState(str(payload["knowledge"]))
        except (KeyError, ValueError) as exc:
            raise ObservationPayloadError("hud value is malformed") from exc
        raw = payload.get("value")
        if raw is not None and not isinstance(raw, (int, float, str, bool)):
            raise ObservationPayloadError("HUD value must be a JSON scalar")
        return cls(
            knowledge=knowledge,
            value=raw,
            confidence=optional_confidence("hud.confidence", payload.get("confidence")),
            region=optional_rect(payload.get("region")),
        )


@dataclass(frozen=True)
class HudObservation:
    """HUD observability plus named fields. Absent keys are UNKNOWN, not false."""

    hud_visible: KnowledgeState = KnowledgeState.UNKNOWN
    fields: Mapping[str, HudValue] = MappingProxyType({})

    def __post_init__(self) -> None:
        cleaned: dict[str, HudValue] = {}
        for key, value in dict(self.fields).items():
            name = str(key).strip()
            if not name:
                raise ObservationPayloadError("HUD field name must be non-empty")
            if not isinstance(value, HudValue):
                raise ObservationPayloadError(f"HUD field {name!r} must be a HudValue")
            cleaned[name] = value
        object.__setattr__(self, "fields", MappingProxyType(cleaned))
        if self.hud_visible is KnowledgeState.UNOBSERVABLE:
            for name, value in self.fields.items():
                if value.knowledge is KnowledgeState.KNOWN:
                    raise ObservationPayloadError(
                        f"HUD field {name!r} cannot be KNOWN when HUD is UNOBSERVABLE"
                    )

    def get(self, name: str) -> HudValue:
        """Return the named field, or UNKNOWN if the field was not represented."""
        existing = self.fields.get(name)
        if existing is not None:
            return existing
        if self.hud_visible is KnowledgeState.UNOBSERVABLE:
            return HudValue(knowledge=KnowledgeState.UNOBSERVABLE)
        return HudValue(knowledge=KnowledgeState.UNKNOWN)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hud_visible": self.hud_visible.value,
            "fields": {name: value.to_dict() for name, value in sorted(self.fields.items())},
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> HudObservation:
        try:
            visible = KnowledgeState(str(payload.get("hud_visible", KnowledgeState.UNKNOWN.value)))
        except ValueError as exc:
            raise ObservationPayloadError("hud_visible is malformed") from exc
        raw_fields = payload.get("fields", {})
        if not isinstance(raw_fields, Mapping):
            raise ObservationPayloadError("hud.fields must be an object")
        fields = {str(name): HudValue.from_dict(item) for name, item in raw_fields.items()}
        return cls(hud_visible=visible, fields=fields)
