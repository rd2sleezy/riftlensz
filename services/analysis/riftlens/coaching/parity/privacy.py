"""Reject privacy identifiers from RP records. Champion and participant id are OK."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

SENSITIVE_TOKENS = (
    "puuid",
    "summonerName",
    "summoner_name",
    "summoner name",
    "riot_id",
    "riotId",
    "accountId",
    "account_id",
    "gameName",
    "tagLine",
    "api_key",
    "apiKey",
    "Authorization",
    "Bearer ",
)


class PrivacyError(ValueError):
    """Raised when an RP record would store a forbidden identifier."""


def iter_strings(value: Any) -> Iterable[str]:
    """Yield string leaves from nested dict/list/tuple/dataclass-like values."""
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from iter_strings(item)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from iter_strings(item)


def find_sensitive_token(text: str) -> str | None:
    """Return the first sensitive token found in ``text``, else None."""
    lowered = text.lower()
    for token in SENSITIVE_TOKENS:
        if token.lower() in lowered:
            return token
    return None


def assert_no_sensitive(payload: Any, *, context: str = "parity_record") -> None:
    """Raise PrivacyError if forbidden identifiers appear in keys or values."""
    if isinstance(payload, dict):
        for key in payload:
            if isinstance(key, str) and find_sensitive_token(key):
                raise PrivacyError(f"{context}: forbidden field {key!r}")
    for text in iter_strings(payload):
        hit = find_sensitive_token(text)
        if hit is not None:
            raise PrivacyError(f"{context}: forbidden token {hit!r}")
