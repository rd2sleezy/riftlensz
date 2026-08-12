from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from riftlens.domain.observation.enums import ObservationPayloadError
from riftlens.domain.observation.frame_observation import FrameObservation
from riftlens.domain.observation.sequence import ObservationSequence

ObservationDocument = FrameObservation | ObservationSequence


def to_canonical_json(payload: Mapping[str, Any]) -> str:
    """Return deterministic UTF-8 JSON (sorted keys, no extra whitespace)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def dumps(document: ObservationDocument) -> str:
    """Serialize a frame or sequence to deterministic JSON."""
    return to_canonical_json(document.to_dict())


def loads_frame(raw: str | Mapping[str, Any]) -> FrameObservation:
    """Parse a FrameObservation. Rejects malformed JSON and unsupported versions."""
    return FrameObservation.from_dict(_as_mapping(raw))


def loads_sequence(raw: str | Mapping[str, Any]) -> ObservationSequence:
    """Parse an ObservationSequence. Rejects malformed JSON and unsupported versions."""
    return ObservationSequence.from_dict(_as_mapping(raw))


def _as_mapping(raw: str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(raw, Mapping):
        return raw
    if not isinstance(raw, str):
        raise ObservationPayloadError("observation payload must be JSON text or an object")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ObservationPayloadError("observation payload is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ObservationPayloadError("observation payload must be a JSON object")
    return parsed
