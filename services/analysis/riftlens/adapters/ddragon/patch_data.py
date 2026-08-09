from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from riftlens.adapters.ddragon.client import DDragonClient

_RESOURCES = Path(__file__).resolve().parents[2] / "resources" / "patches"
_CONSTANTS_PATH = _RESOURCES / "constants.yaml"


def ddragon_version_for(game_version: str, versions: list[str]) -> str:
    """Map a match gameVersion onto a Data Dragon version. Assumes versions is newest-first."""
    parts = game_version.split(".")
    if len(parts) >= 2:
        prefix = f"{parts[0]}.{parts[1]}"
        for version in versions:
            if version == prefix or version.startswith(prefix + "."):
                return version
    if not versions:
        raise ValueError(f"no ddragon versions available for gameVersion={game_version}")
    return versions[0]


def patch_prefix(game_version: str) -> str:
    """Return ``major.minor`` from a Riot ``gameVersion``. Assumes dotted version text."""
    parts = game_version.split(".")
    if len(parts) < 2:
        return game_version
    return f"{parts[0]}.{parts[1]}"


class PatchDataProvider:
    """Patch-scoped champion/item/economy constants for metrics and features."""

    def __init__(self, client: DDragonClient | None = None) -> None:
        self._client = client
        self._ddragon_version: str | None = None
        self._items: dict[str, Any] = {}
        self._champions: dict[str, Any] = {}
        self._constants: dict[str, Any] = {}

    @property
    def version(self) -> str:
        if self._ddragon_version is None:
            raise RuntimeError("PatchDataProvider.load() has not been called")
        return self._ddragon_version

    def load_bundled(self, game_version: str) -> None:
        """Load shipped patch constants and item gold. Assumes no network is available."""
        prefix = patch_prefix(game_version)
        self._ddragon_version = prefix
        self._constants = _select_constants(prefix)
        self._items = _load_bundled_items(prefix)
        self._champions = {}

    async def load(self, game_version: str) -> None:
        """Fetch and cache DDragon data for game_version. Assumes a live or mocked client."""
        if self._client is None:
            self.load_bundled(game_version)
            return
        versions = await self._client.versions()
        self._ddragon_version = ddragon_version_for(game_version, versions)
        self._items = await self._client.items(self._ddragon_version)
        self._champions = await self._client.champions(self._ddragon_version)
        self._constants = _select_constants(patch_prefix(game_version))

    def item_gold(self, item_id: int) -> int:
        """Return total gold cost for an item id. Assumes load() succeeded."""
        gold = self._item_gold_blob(item_id)
        if gold is None:
            return 0
        return int(gold.get("total", 0) or 0)

    def item_purchase_cost(self, item_id: int) -> int | None:
        """Return incremental buy cost (``gold.base``). Assumes load() succeeded."""
        gold = self._item_gold_blob(item_id)
        if gold is None:
            return None
        if "base" not in gold:
            return None
        return int(gold.get("base") or 0)

    def item_sell_value(self, item_id: int) -> int | None:
        """Return sell refund. Assumes load() succeeded."""
        gold = self._item_gold_blob(item_id)
        if gold is None:
            return None
        if "sell" not in gold:
            return None
        return int(gold.get("sell") or 0)

    def average_cs_gold(self, *, jungle: bool = False) -> float | None:
        """Return average gold per CS. Assumes constants were loaded."""
        key = "jungle_minion_gold" if jungle else "average_lane_minion_gold"
        raw = self._constants.get(key)
        return None if raw is None else float(raw)

    def passive_gold(self, start_ms: int, end_ms: int) -> float:
        """Return passive gold on ``[start_ms, end_ms)``. Assumes constants were loaded."""
        if end_ms <= start_ms:
            return 0.0
        rate = float(self._constants.get("passive_gold_per_second") or 0.0)
        origin = int(self._constants.get("passive_gold_start_ms") or 0)
        lo = max(start_ms, origin)
        hi = end_ms
        if hi <= lo:
            return 0.0
        return rate * (hi - lo) / 1000.0

    def gold_per_second_rate(self, raw: int) -> float | None:
        """Return gold/ms from a timeline ``goldPerSecond`` sample. Assumes constants loaded."""
        if raw <= 0:
            return None
        unit = self._constants.get("gold_per_second_unit")
        if unit is None:
            return None
        return float(raw) * float(unit) / 1000.0

    def respawn_ms(self, level: int, death_t_ms: int) -> int | None:
        """Return respawn duration in ms. Assumes constants include a BRW table."""
        blob = self._constants.get("respawn")
        if not isinstance(blob, dict):
            return None
        table = blob.get("base_seconds_by_level")
        if not isinstance(table, list) or level < 1 or level >= len(table):
            return None
        base = float(table[level])
        start = int(blob.get("scaling_start_ms") or 0)
        per_step = float(blob.get("scaling_per_30s") or 0.0)
        cap = float(blob.get("scaling_cap") or 0.0)
        tif = 0.0
        if death_t_ms > start and per_step:
            steps = (death_t_ms - start) / 30_000.0
            tif = min(cap, steps * per_step)
        return int(round(base * (1.0 + tif) * 1000.0))

    def health_regen_per_ms(self, regen_stat: float) -> float:
        """Return HP/ms from timeline ``healthRegen``. Assumes a period constant is loaded."""
        period = float(self._constants.get("health_regen_period_ms") or 5000.0)
        if period <= 0:
            return 0.0
        return float(regen_stat) / period

    def champion(self, champion_name: str) -> dict[str, Any]:
        """Return the champion blob by name. Assumes load() succeeded."""
        data = self._champions.get("data", {})
        if not isinstance(data, dict):
            return {}
        blob = data.get(champion_name)
        return blob if isinstance(blob, dict) else {}

    def _item_gold_blob(self, item_id: int) -> dict[str, Any] | None:
        data = self._items.get("data", self._items)
        if not isinstance(data, dict):
            return None
        entry = data.get(str(item_id))
        if not isinstance(entry, dict):
            return None
        gold = entry.get("gold", entry)
        return gold if isinstance(gold, dict) else None


def _select_constants(prefix: str) -> dict[str, Any]:
    raw = yaml.safe_load(_CONSTANTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("patch constants.yaml must be a mapping")
    defaults = dict(raw.get("default") or {})
    patches = raw.get("patches") or {}
    override = patches.get(prefix) if isinstance(patches, dict) else None
    if isinstance(override, dict):
        merged = dict(defaults)
        merged.update(override)
        return merged
    return defaults


def _load_bundled_items(prefix: str) -> dict[str, Any]:
    path = _RESOURCES / prefix / "item_gold.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    data: dict[str, Any] = {}
    for item_id, entry in payload.items():
        if isinstance(entry, dict) and "base" in entry:
            data[str(item_id)] = {
                "gold": {
                    "base": entry.get("base", 0),
                    "total": entry.get("total", 0),
                    "sell": entry.get("sell", 0),
                },
                "name": entry.get("name", ""),
            }
        elif isinstance(entry, dict):
            data[str(item_id)] = entry
    return {"data": data}
