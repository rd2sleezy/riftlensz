from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path

from riftlens.coaching.bundler import EvidenceBundle, bundle_review
from riftlens.coaching.providers.base import LLMProvider, ProviderUnavailable
from riftlens.coaching.providers.null import NullProvider
from riftlens.coaching.validator import ValidationFailure, validate_bundle_text
from riftlens.domain.review import CoachingItem, Review
from riftlens.domain.timeline import GameStateTimeline

PROMPT_VERSION = "v1"
_PROMPT_DIR = Path(__file__).resolve().parents[1] / "resources" / "prompts"


@dataclass(frozen=True)
class NarrationMeta:
    text: str
    fallback: bool
    reason: str | None
    calls: int
    cache_hit: bool = False


@dataclass(frozen=True)
class ComposeResult:
    review: Review
    llm_fallback: bool
    item_meta: tuple[NarrationMeta, ...]
    summary_meta: NarrationMeta


def load_prompt(name: str) -> str:
    """Return a versioned prompt file. Assumes ``name`` is a file under resources/prompts."""
    path = _PROMPT_DIR / name
    return path.read_text(encoding="utf-8").strip()


async def compose_review(
    review: Review,
    gst: GameStateTimeline,
    provider: LLMProvider,
    *,
    cache_dir: Path | None = None,
) -> ComposeResult:
    """Narrate coaching items from EvidenceBundles. Never selects or mutates findings."""
    roster = tuple(info.champion for info in gst.participants.values())
    bundles = bundle_review(review)
    items = [*review.focus_items, *review.secondary_items, *review.strengths]
    cache = cache_dir
    metas: list[NarrationMeta] = []
    rewritten: list[CoachingItem] = []
    any_fallback = False
    for item, bundle in zip(items, bundles, strict=True):
        meta = await narrate_item(
            bundle, provider, extra_names=roster, cache=cache, skip_validate=_is_null(provider)
        )
        metas.append(meta)
        any_fallback = any_fallback or meta.fallback
        rewritten.append(
            replace(
                item,
                body=meta.text,
                explanation_source="TEMPLATE" if meta.fallback or _is_null(provider) else "LLM",
                llm_fallback=meta.fallback,
            )
        )
    summary_bundle = bundles[0] if bundles else None
    summary_meta = await narrate_summary(
        review,
        bundles,
        provider,
        extra_names=roster,
        cache=cache,
        skip_validate=_is_null(provider),
        fallback_text=review.summary_text or "",
    )
    any_fallback = any_fallback or summary_meta.fallback
    focus_n = len(review.focus_items)
    secondary_n = len(review.secondary_items)
    updated = replace(
        review,
        focus_items=tuple(rewritten[:focus_n]),
        secondary_items=tuple(rewritten[focus_n : focus_n + secondary_n]),
        strengths=tuple(rewritten[focus_n + secondary_n :]),
        summary_text=summary_meta.text or review.summary_text,
        llm_provider=provider.name,
        llm_model=provider.model,
        llm_prompt_version=PROMPT_VERSION,
        llm_fallback=any_fallback,
    )
    del summary_bundle
    return ComposeResult(
        review=updated,
        llm_fallback=any_fallback,
        item_meta=tuple(metas),
        summary_meta=summary_meta,
    )


async def narrate_item(
    bundle: EvidenceBundle,
    provider: LLMProvider,
    *,
    extra_names: tuple[str, ...] = (),
    cache: Path | None = None,
    skip_validate: bool = False,
) -> NarrationMeta:
    """Narrate one item. One repair then template fallback. Does not cache invalid text."""
    template = bundle.template_explanation.strip()
    if skip_validate:
        text = await provider.complete(
            _finding_prompt(bundle), fallback_text=template, max_tokens=400
        )
        return NarrationMeta(text=text.strip() or template, fallback=False, reason=None, calls=1)
    cached = _llm_get(cache, bundle, provider)
    if cached is not None:
        return NarrationMeta(text=cached, fallback=False, reason=None, calls=0, cache_hit=True)
    prompt = _finding_prompt(bundle)
    text, calls, failure = await _complete_validated(
        provider, prompt, bundle, extra_names, fallback_text=template
    )
    if failure is None:
        _llm_put(cache, bundle, provider, text)
        return NarrationMeta(text=text, fallback=False, reason=None, calls=calls)
    return NarrationMeta(text=template, fallback=True, reason=failure.describe(), calls=calls)


async def narrate_summary(
    review: Review,
    bundles: list[EvidenceBundle],
    provider: LLMProvider,
    *,
    extra_names: tuple[str, ...] = (),
    cache: Path | None = None,
    skip_validate: bool = False,
    fallback_text: str = "",
) -> NarrationMeta:
    """Narrate the session summary. Falls back to the deterministic summary text."""
    template = fallback_text.strip() or (review.summary_text or "").strip()
    if skip_validate or not bundles:
        text = await provider.complete(
            _summary_prompt(bundles), fallback_text=template, max_tokens=400
        )
        return NarrationMeta(text=text.strip() or template, fallback=False, reason=None, calls=1)
    prompt = _summary_prompt(bundles)
    text, calls, failure = await _complete_validated(
        provider, prompt, bundles[0], extra_names, fallback_text=template
    )
    if failure is None:
        return NarrationMeta(text=text, fallback=False, reason=None, calls=calls)
    return NarrationMeta(text=template, fallback=True, reason=failure.describe(), calls=calls)


async def _complete_validated(
    provider: LLMProvider,
    prompt: str,
    bundle: EvidenceBundle,
    extra_names: tuple[str, ...],
    *,
    fallback_text: str,
) -> tuple[str, int, ValidationFailure | None]:
    calls = 0
    try:
        raw = await provider.complete(prompt, fallback_text=fallback_text, max_tokens=400)
        calls += 1
    except ProviderUnavailable:
        return fallback_text, calls, ValidationFailure(("provider",), "provider unavailable")
    extracted = _extract_prose(raw)
    failure = validate_bundle_text(extracted, bundle, extra_names=extra_names)
    if failure is None:
        return extracted, calls, None
    repair_prompt = (
        f"{prompt}\n\nPrevious output was rejected ({failure.describe()}). "
        "Rewrite using only allowed_values. Return JSON {\"explanation\": \"...\"}."
    )
    try:
        raw = await provider.complete(
            repair_prompt, fallback_text=fallback_text, max_tokens=400
        )
        calls += 1
    except ProviderUnavailable:
        return fallback_text, calls, failure
    extracted = _extract_prose(raw)
    second = validate_bundle_text(extracted, bundle, extra_names=extra_names)
    if second is None:
        return extracted, calls, None
    return fallback_text, calls, second


def _finding_prompt(bundle: EvidenceBundle) -> str:
    header = load_prompt("finding_v1.md")
    return f"{header}\n\n{bundle.model_dump_json()}"


def _summary_prompt(bundles: list[EvidenceBundle]) -> str:
    header = load_prompt("summary_v1.md")
    payload = [item.model_dump() for item in bundles]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"{header}\n\n{encoded}"


def _extract_prose(raw: str) -> str:
    text = raw.strip()
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(parsed, dict):
            for key in ("explanation", "summary", "text"):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return text


def _is_null(provider: LLMProvider) -> bool:
    return provider.name == "null" or isinstance(provider, NullProvider)


def _llm_get(cache: Path | None, bundle: EvidenceBundle, provider: LLMProvider) -> str | None:
    path = _llm_path(cache, bundle, provider)
    if path is None or not path.is_file():
        return None
    parsed = json.loads(path.read_text(encoding="utf-8"))
    text = parsed.get("text") if isinstance(parsed, dict) else None
    return text if isinstance(text, str) else None


def _llm_put(
    cache: Path | None, bundle: EvidenceBundle, provider: LLMProvider, text: str
) -> None:
    path = _llm_path(cache, bundle, provider)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"text": text}), encoding="utf-8")


def _llm_path(
    cache: Path | None, bundle: EvidenceBundle, provider: LLMProvider
) -> Path | None:
    if cache is None:
        return None
    payload = f"{bundle.model_dump_json()}{PROMPT_VERSION}{provider.name}{provider.model}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return cache / f"{digest}.json"
