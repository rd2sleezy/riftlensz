from __future__ import annotations

from pydantic import BaseModel


class NullProvider:
    """Offline provider. Returns template prose and never opens a network connection."""

    name = "null"
    model = "null"

    async def complete(
        self,
        prompt: str,
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int = 800,
        fallback_text: str = "",
    ) -> str:
        """Return ``fallback_text`` (or the prompt). Assumes the caller passed the template."""
        del prompt, schema, max_tokens
        text = fallback_text.strip() or ""
        return text
