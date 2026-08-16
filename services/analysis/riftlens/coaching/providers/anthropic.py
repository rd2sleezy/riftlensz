from __future__ import annotations

import httpx
from pydantic import BaseModel

from riftlens.coaching.providers.base import ProviderUnavailable

_DEFAULT_MODEL = "claude-haiku-4-5"


class AnthropicProvider:
    """Anthropic Messages adapter. Missing keys fail closed to the composer."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str = "") -> None:
        self._api_key = api_key.strip()
        self.model = model.strip() or _DEFAULT_MODEL

    async def complete(
        self,
        prompt: str,
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int = 800,
        fallback_text: str = "",
    ) -> str:
        """Return assistant text. Assumes ``prompt`` contains only EvidenceBundle content."""
        del schema, fallback_text
        if not self._api_key:
            raise ProviderUnavailable("anthropic is not configured")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": self.model,
                        "max_tokens": max_tokens,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("anthropic request failed") from exc
        try:
            return str(payload["content"][0]["text"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderUnavailable("anthropic response missing text") from exc
