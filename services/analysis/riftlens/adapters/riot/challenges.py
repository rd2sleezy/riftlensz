from __future__ import annotations

from typing import Any

from riftlens.adapters.riot.models import ParticipantDto


def challenge(participant: ParticipantDto, name: str, default: Any = None) -> Any:
    """Return a named challenges field. Assumes missing maps should degrade to default."""
    blob = participant.challenges
    if not blob:
        return default
    return blob.get(name, default)
