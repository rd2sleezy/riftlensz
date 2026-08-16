from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def canonical_json(value: object) -> str:
    """Return sorted, compact JSON. Assumes ``value`` is JSON-serializable."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def stage_cache_key(name: str, version: str, input_refs: Mapping[str, Any]) -> str:
    """Return sha256(name + version + canonical_json(input_refs))."""
    payload = f"{name}{version}{canonical_json(dict(input_refs))}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def llm_cache_key(bundle_json: str, prompt_version: str, model: str) -> str:
    """Return sha256(canonical bundle + prompt version + model)."""
    payload = f"{bundle_json}{prompt_version}{model}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
