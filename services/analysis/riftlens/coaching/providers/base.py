from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class ProviderUnavailable(Exception):
    """Raised when a live provider cannot be reached or is not configured."""


class LLMProvider(Protocol):
    """Shared completion contract. Pipeline code must not branch on provider name."""

    name: str
    model: str

    async def complete(
        self,
        prompt: str,
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int = 800,
        fallback_text: str = "",
    ) -> str:
        """Return model text. ``fallback_text`` is what ``null`` echoes verbatim."""
        ...
