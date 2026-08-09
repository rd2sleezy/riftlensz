from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

_DEFAULT_PATH = (
    Path(__file__).resolve().parents[2] / "resources" / "champions" / "tags.yaml"
)


def load_champion_tags(path: Path | None = None) -> dict[str, tuple[str, ...]]:
    """Return champion name → tags. Assumes YAML maps tag → list of champion names."""
    target = path or _DEFAULT_PATH
    if not target.is_file():
        return {}
    loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return {}
    inverted: dict[str, list[str]] = {}
    for tag, names in cast(dict[str, Any], loaded).items():
        if not isinstance(names, list):
            continue
        label = str(tag).upper()
        for name in names:
            key = str(name)
            inverted.setdefault(key, []).append(label)
            inverted.setdefault(key.casefold(), []).append(label)
    return {name: tuple(dict.fromkeys(tags)) for name, tags in inverted.items()}
