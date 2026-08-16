from __future__ import annotations

import httpx
from pydantic import BaseModel

from riftlens.coaching.providers.base import ProviderUnavailable

_DEFAULT_MODEL = "llama3.2"


class OllamaProvider:
    """Local Ollama adapter. Unreachable hosts fail closed to the composer."""

    name = "ollama"

    def __init__(self, base_url: str, model: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self.model = model.strip() or _DEFAULT_MODEL

    async def complete(
        self,
        prompt: str,
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int = 800,
        fallback_text: str = "",
    ) -> str:
        """Return generated text from a local Ollama daemon."""
        del schema, fallback_text
        url = f"{self._base_url}/api/generate"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"num_predict": max_tokens},
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("ollama request failed") from exc
        text = payload.get("response")
        if not isinstance(text, str) or not text.strip():
            raise ProviderUnavailable("ollama response missing text")
        return text
