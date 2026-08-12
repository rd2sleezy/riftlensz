from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from riftlens.domain.ids import is_ulid
from riftlens.domain.observation.enums import (
    SUPPORTED_SCHEMA_VERSIONS,
    ConfidenceBand,
    ObservationPayloadError,
    UnsupportedObservationSchema,
)


def require_non_empty(name: str, value: str) -> str:
    text = str(value).strip()
    if not text:
        raise ObservationPayloadError(f"{name} must be a non-empty string")
    return text


def require_ulid(name: str, value: str) -> str:
    text = require_non_empty(name, value)
    if not is_ulid(text):
        raise ObservationPayloadError(f"{name} must be a ULID")
    return text


def require_game_ms(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ObservationPayloadError(f"{name} must be an integer millisecond value")
    if value < 0:
        raise ObservationPayloadError(f"{name} must be >= 0")
    return value


def optional_game_ms(name: str, value: object) -> int | None:
    if value is None:
        return None
    return require_game_ms(name, value)


def require_confidence(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ObservationPayloadError(f"{name} must be a finite float in 0..1")
    confidence = float(value)
    if confidence != confidence or confidence in (float("inf"), float("-inf")):
        raise ObservationPayloadError(f"{name} must be a finite float in 0..1")
    if not 0.0 <= confidence <= 1.0:
        raise ObservationPayloadError(f"{name} must be in 0..1")
    return confidence


def optional_confidence(name: str, value: object) -> float | None:
    if value is None:
        return None
    return require_confidence(name, value)


def confidence_band(confidence: float) -> ConfidenceBand:
    """Return the descriptive band for a validated 0..1 confidence."""
    if confidence >= 0.8:
        return ConfidenceBand.HIGH
    if confidence >= 0.5:
        return ConfidenceBand.MEDIUM
    if confidence >= 0.2:
        return ConfidenceBand.LOW
    return ConfidenceBand.NONE


def never_increase_confidence(original: float, proposed: float) -> float:
    """Return proposed confidence, rejecting any increase during transformation."""
    kept = require_confidence("original_confidence", original)
    next_value = require_confidence("proposed_confidence", proposed)
    if next_value > kept:
        raise ObservationPayloadError("confidence cannot increase during transformation")
    return next_value


def require_schema_version(value: object) -> str:
    version = require_non_empty("schema_version", str(value) if value is not None else "")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedObservationSchema(f"unsupported observation schema version {version!r}")
    return version


def mapping_or_error(payload: object, *, what: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ObservationPayloadError(f"{what} must be a JSON object")
    return payload


@dataclass(frozen=True)
class ScreenRect:
    """Inclusive-origin axis-aligned region in artifact pixel space."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        for name, value in (
            ("x", self.x),
            ("y", self.y),
            ("width", self.width),
            ("height", self.height),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ObservationPayloadError(f"ScreenRect.{name} must be an int")
        if self.width < 0 or self.height < 0:
            raise ObservationPayloadError("ScreenRect width and height must be >= 0")

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ScreenRect:
        return cls(
            x=int(payload["x"]),
            y=int(payload["y"]),
            width=int(payload["width"]),
            height=int(payload["height"]),
        )


def optional_rect(payload: object) -> ScreenRect | None:
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise ObservationPayloadError("screen region must be an object or null")
    return ScreenRect.from_dict(payload)
