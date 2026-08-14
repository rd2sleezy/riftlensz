"""Parse ``GET /replay/render`` fields relevant to subject attachment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Identity-like keys that would strengthen CONTROLLED_SUBJECT if present.
IDENTITY_FIELD_CANDIDATES = (
    "selectionName",
    "selectionOffset",
    "selectedObject",
    "selectedObjectName",
    "objectName",
    "targetName",
    "targetId",
    "entityId",
    "netId",
    "networkId",
    "participantId",
    "participant_id",
    "championId",
    "championName",
    "characterName",
    "cameraTarget",
    "followedChampion",
    "attachedObject",
)

CAMERA_FIELDS = (
    "cameraMode",
    "cameraAttached",
    "cameraPosition",
    "cameraRotation",
    "fieldOfView",
    "fogOfWar",
    "selectionName",
    "selectionOffset",
    "cameraLockX",
    "cameraLockY",
    "cameraLockZ",
    "cameraMoveSpeed",
    "cameraLookSpeed",
)


@dataclass(frozen=True)
class RenderAttachment:
    """Attachment-relevant subset of a render payload."""

    camera_mode: str | None
    camera_attached: bool | None
    selection_name: str
    camera_position: dict[str, float] | None
    camera_rotation: dict[str, float] | None
    selection_offset: dict[str, float] | None
    identity_fields: dict[str, Any]
    extra_keys: tuple[str, ...]

    @property
    def has_participant_id(self) -> bool:
        for key, value in self.identity_fields.items():
            if "participant" in key.lower() and value not in (None, "", False):
                return True
        return False


def as_float_map(value: Any) -> dict[str, float] | None:
    """Return a 3-vector map when ``value`` has numeric x/y/z (or similar)."""
    if not isinstance(value, Mapping):
        return None
    try:
        return {str(k): float(v) for k, v in value.items()}
    except (TypeError, ValueError):
        return None


def camera_ground_xz(position: Mapping[str, Any] | None) -> tuple[float, float] | None:
    """Map Replay cameraPosition to Riot ground ``(x, y)`` using x/z."""
    if not isinstance(position, Mapping):
        return None
    try:
        return float(position["x"]), float(position["z"])
    except (KeyError, TypeError, ValueError):
        return None


def ground_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Euclidean distance on the Riot ground plane."""
    return float(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5)


def parse_render(payload: Mapping[str, Any]) -> RenderAttachment:
    """Extract attachment fields. Unknown keys are listed, not invented."""
    identity: dict[str, Any] = {}
    for key in IDENTITY_FIELD_CANDIDATES:
        if key in payload:
            identity[key] = payload[key]
    extras = tuple(sorted(k for k in payload if k not in CAMERA_FIELDS and k not in identity))
    selection = payload.get("selectionName")
    attached = payload.get("cameraAttached")
    return RenderAttachment(
        camera_mode=None if payload.get("cameraMode") is None else str(payload["cameraMode"]),
        camera_attached=None if attached is None else bool(attached),
        selection_name="" if selection is None else str(selection),
        camera_position=as_float_map(payload.get("cameraPosition")),
        camera_rotation=as_float_map(payload.get("cameraRotation")),
        selection_offset=as_float_map(payload.get("selectionOffset")),
        identity_fields=identity,
        extra_keys=extras,
    )


def interesting_render(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a compact render snapshot for reports."""
    parsed = parse_render(payload)
    out: dict[str, Any] = {
        "cameraMode": parsed.camera_mode,
        "cameraAttached": parsed.camera_attached,
        "selectionName": parsed.selection_name,
        "cameraPosition": parsed.camera_position,
        "cameraRotation": parsed.camera_rotation,
        "selectionOffset": parsed.selection_offset,
    }
    return out
