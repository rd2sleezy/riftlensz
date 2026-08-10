"""ClockMap ↔ amendment clock_map column mapping. No SQLAlchemy."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from riftlens.domain.clock_map import ClockConfidence, ClockMap, ClockMode

CLOCK_KIND_IDENTITY = "identity"
CLOCK_KIND_LINEAR_OFFSET = "linear_offset"
CLOCK_KIND_CALIBRATED_REPLAY = "calibrated_replay"

STORE_CONFIDENCE_EXACT = "exact"
STORE_CONFIDENCE_CALIBRATED = "calibrated"
STORE_CONFIDENCE_ESTIMATED = "estimated"
STORE_CONFIDENCE_MANUAL = "manual"
STORE_CONFIDENCE_UNKNOWN = "unknown"

SOURCE_TYPE_VIDEO = "video"
SOURCE_TYPE_ROFL = "rofl"

SOURCE_STATUS_LINKED = "linked"
SOURCE_STATUS_READY = "ready"
SOURCE_STATUS_UNAVAILABLE = "unavailable"
SOURCE_STATUS_ERROR = "error"

PLATFORM_SCOPE_WINDOWS = "windows"
PLATFORM_SCOPE_ANY = "any"

CALIBRATION_METHOD_EVENT_ANCHOR_V1 = "event_anchor_v1"
CALIBRATION_METHOD_MANUAL = "manual"


def local_display_name(source_uri: str) -> str:
    """Return the basename only. Full local paths stay in ``source_uri``."""
    name = Path(source_uri).name.strip()
    return name or "source"


def source_file_present(source_uri: str) -> bool:
    """Return True when ``source_uri`` is an existing file. Does not follow persistence."""
    try:
        return Path(source_uri).is_file()
    except OSError:
        return False


def amendment_clock_kind(clock: ClockMap) -> str:
    """Return the amendment ``clock_map.kind`` for ``clock``. Payload remains authoritative."""
    if clock.mode is ClockMode.SYNC_MAP:
        return CLOCK_KIND_LINEAR_OFFSET
    if clock.mode is ClockMode.OFFSET:
        if clock.verified:
            return CLOCK_KIND_CALIBRATED_REPLAY
        return CLOCK_KIND_LINEAR_OFFSET
    return CLOCK_KIND_IDENTITY


def amendment_clock_confidence(clock: ClockMap, method: str) -> str:
    """Return the amendment confidence label. Does not change ``clock.confidence``."""
    if clock.confidence is ClockConfidence.EXACT:
        return STORE_CONFIDENCE_EXACT
    if clock.confidence is ClockConfidence.UNKNOWN or clock.confidence is ClockConfidence.FAILED:
        return STORE_CONFIDENCE_UNKNOWN
    normalized = method.strip().lower()
    if normalized == CALIBRATION_METHOD_MANUAL or normalized.startswith("manual"):
        return STORE_CONFIDENCE_MANUAL
    if clock.verified and clock.confidence is ClockConfidence.GOOD:
        return STORE_CONFIDENCE_CALIBRATED
    return STORE_CONFIDENCE_ESTIMATED


def encode_clock_payload(
    clock: ClockMap,
    *,
    stdev_ms: float | None = None,
    warning: str | None = None,
    media_asset_id: str | None = None,
) -> str:
    """Serialize a ClockMap plus calibration extras. Assumes ``clock`` is valid."""
    payload: dict[str, Any] = {
        "clock": clock.to_dict(),
        "stdev_ms": stdev_ms,
        "warning": warning,
        "media_asset_id": media_asset_id,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def decode_clock_payload(raw: str) -> tuple[ClockMap, float | None, str | None, str | None]:
    """Parse ``encode_clock_payload`` output. ClockMap fields are not reinterpreted."""
    data: Mapping[str, Any] = json.loads(raw)
    clock_raw = data["clock"]
    if not isinstance(clock_raw, Mapping):
        raise ValueError("clock payload must be an object")
    clock = ClockMap.from_dict(clock_raw)
    stdev_raw = data.get("stdev_ms")
    stdev_ms = None if stdev_raw is None else float(stdev_raw)
    warning_raw = data.get("warning")
    warning = None if warning_raw is None else str(warning_raw)
    media_raw = data.get("media_asset_id")
    media_asset_id = None if media_raw is None else str(media_raw)
    return clock, stdev_ms, warning, media_asset_id
