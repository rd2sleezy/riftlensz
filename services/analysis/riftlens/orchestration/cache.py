from __future__ import annotations

import pickle
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from riftlens.orchestration.canonical import stage_cache_key


class StageCache:
    """Filesystem stage cache keyed by name+version+canonical input refs."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def get(self, name: str, version: str, input_refs: dict[str, Any]) -> dict[str, Any] | None:
        """Return cached outputs or None. Assumes values were pickled by ``put``."""
        path = self._path(name, version, input_refs)
        if not path.is_file():
            return None
        try:
            loaded = pickle.loads(path.read_bytes())
        except (pickle.UnpicklingError, AttributeError, EOFError, ValueError):
            return None
        if not isinstance(loaded, dict):
            return None
        return loaded

    def put(
        self,
        name: str,
        version: str,
        input_refs: dict[str, Any],
        outputs: dict[str, Any],
    ) -> None:
        """Store pickle-safe ``outputs``. MappingProxy values are converted to dicts."""
        path = self._path(name, version, input_refs)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            dumped = pickle.dumps(_pickle_safe(outputs), protocol=4)
        except (pickle.PicklingError, TypeError) as exc:
            raise TypeError(f"cannot pickle stage {name} outputs: {exc}") from exc
        path.write_bytes(dumped)

    def invalidate_prefix(self, names: set[str]) -> int:
        """Delete cache files whose filename starts with a given stage name. Returns count."""
        removed = 0
        if not self._root.is_dir():
            return 0
        for path in self._root.glob("*.pkl"):
            stem = path.name
            if any(stem.startswith(f"{name}__") for name in names):
                path.unlink(missing_ok=True)
                removed += 1
        return removed

    def _path(self, name: str, version: str, input_refs: dict[str, Any]) -> Path:
        key = stage_cache_key(name, version, input_refs)
        return self._root / f"{name}__{key}.pkl"


def _pickle_safe(value: object) -> object:
    if isinstance(value, MappingProxyType):
        return {str(key): _pickle_safe(item) for key, item in value.items()}
    if isinstance(value, dict):
        return {key: _pickle_safe(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_pickle_safe(item) for item in value)
    if isinstance(value, list):
        return [_pickle_safe(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        updates = {
            field.name: _pickle_safe(getattr(value, field.name)) for field in fields(value)
        }
        try:
            return replace(value, **updates)
        except TypeError:
            return value
    return value
