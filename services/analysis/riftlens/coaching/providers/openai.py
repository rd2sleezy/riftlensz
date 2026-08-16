from __future__ import annotations

import httpx
from pydantic import BaseModel

from riftlens.coaching.providers.base import ProviderUnavailable

_DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIProvider:
    """OpenAI Chat Completions adapter. Missing keys fail closed to the composer."""

    name = "openai"

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
        del fallback_text
        if not self._api_key:
            raise ProviderUnavailable("openai is not configured")
        body: dict[str, object] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if schema is not None:
            body["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("openai request failed") from exc
        try:
            return str(payload["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderUnavailable("openai response missing text") from exc
