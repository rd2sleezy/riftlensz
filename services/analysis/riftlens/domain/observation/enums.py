from __future__ import annotations

from enum import StrEnum


class KnowledgeState(StrEnum):
    """Whether a property was established, not merely undetected.

    UNKNOWN — the analyzer did not determine the value (missing, unreadable, or unobserved).
    ABSENT — the analyzer established that the thing is not present.
    UNOBSERVABLE — the relevant region/camera/HUD was not available, so absence cannot be claimed.
    KNOWN — a positive value was established (use with a concrete field value).
    """

    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    ABSENT = "ABSENT"
    UNOBSERVABLE = "UNOBSERVABLE"


class CameraControl(StrEnum):
    """Who, if anyone, the replay camera was locked to.

    CONTROLLED_SUBJECT — camera was locked to the reviewed participant.
    CONTROLLED_OTHER — camera was locked to some other participant.
    UNCONTROLLED — camera was not locked (R.10 ``camera_controlled=false``).
    UNKNOWN — camera lock state was not established.
    """

    CONTROLLED_SUBJECT = "CONTROLLED_SUBJECT"
    CONTROLLED_OTHER = "CONTROLLED_OTHER"
    UNCONTROLLED = "UNCONTROLLED"
    UNKNOWN = "UNKNOWN"


class VisibilityState(StrEnum):
    """Viewport visibility of an entity. NOT_VISIBLE is not implied by UNKNOWN."""

    VISIBLE = "VISIBLE"
    PARTIAL = "PARTIAL"
    OCCLUDED = "OCCLUDED"
    NOT_VISIBLE = "NOT_VISIBLE"
    UNKNOWN = "UNKNOWN"


class CorrelationMethod(StrEnum):
    """How an entity observation was (or was not) bound to a participant."""

    NONE = "NONE"
    MANUAL = "MANUAL"
    DETECTOR = "DETECTOR"
    UNKNOWN = "UNKNOWN"


class VisualClaimKind(StrEnum):
    """Direct pixel observation vs inference over observations. Never Riot/GST."""

    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"


class ConfidenceBand(StrEnum):
    """Descriptive bucket derived from a 0..1 confidence. Not a second confidence system."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


FRAME_OBSERVATION_SCHEMA_VERSION = "r11.1"
SUPPORTED_SCHEMA_VERSIONS = frozenset({FRAME_OBSERVATION_SCHEMA_VERSION})


class ObservationPayloadError(ValueError):
    """Raised when a visual-observation payload is malformed."""


class UnsupportedObservationSchema(ValueError):
    """Raised when a payload declares a schema version this contract cannot read."""
