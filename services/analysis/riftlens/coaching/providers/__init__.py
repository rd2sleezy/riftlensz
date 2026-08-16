from __future__ import annotations

from riftlens.coaching.providers.anthropic import AnthropicProvider
from riftlens.coaching.providers.base import LLMProvider
from riftlens.coaching.providers.null import NullProvider
from riftlens.coaching.providers.ollama import OllamaProvider
from riftlens.coaching.providers.openai import OpenAIProvider
from riftlens.config import Settings


def create_provider(
    name: str,
    *,
    model: str = "",
    settings: Settings | None = None,
) -> LLMProvider:
    """Return the named provider. Unknown names fall back to ``null`` (offline-safe)."""
    key = (name or "null").strip().lower()
    cfg = settings
    if key in {"null", "none", ""}:
        return NullProvider()
    if cfg is None:
        return NullProvider()
    resolved_model = model.strip() or cfg.llm_model
    if key == "openai":
        return OpenAIProvider(cfg.openai_api_key, resolved_model)
    if key == "anthropic":
        return AnthropicProvider(cfg.anthropic_api_key, resolved_model)
    if key == "ollama":
        return OllamaProvider(cfg.ollama_base_url, resolved_model)
    return NullProvider()
