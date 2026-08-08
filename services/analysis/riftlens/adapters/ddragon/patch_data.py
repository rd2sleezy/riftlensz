from __future__ import annotations

from typing import Any

from riftlens.adapters.ddragon.client import DDragonClient


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


class PatchDataProvider:
    """Patch-scoped champion/item constants. Assumes load() ran for the match version."""

    def __init__(self, client: DDragonClient) -> None:
        self._client = client
        self._ddragon_version: str | None = None
        self._items: dict[str, Any] = {}
        self._champions: dict[str, Any] = {}

    @property
    def version(self) -> str:
        if self._ddragon_version is None:
            raise RuntimeError("PatchDataProvider.load() has not been called")
        return self._ddragon_version

    async def load(self, game_version: str) -> None:
        """Fetch and cache DDragon data for game_version. Assumes a live or mocked client."""
        versions = await self._client.versions()
        self._ddragon_version = ddragon_version_for(game_version, versions)
        self._items = await self._client.items(self._ddragon_version)
        self._champions = await self._client.champions(self._ddragon_version)

    def item_gold(self, item_id: int) -> int:
        """Return total gold cost for an item id. Assumes load() succeeded."""
        data = self._items.get("data", {})
        if not isinstance(data, dict):
            return 0
        entry = data.get(str(item_id), {})
        if not isinstance(entry, dict):
            return 0
        gold = entry.get("gold", {})
        if not isinstance(gold, dict):
            return 0
        return int(gold.get("total", 0) or 0)

    def champion(self, champion_name: str) -> dict[str, Any]:
        """Return the champion blob by name. Assumes load() succeeded."""
        data = self._champions.get("data", {})
        if not isinstance(data, dict):
            return {}
        blob = data.get(champion_name)
        return blob if isinstance(blob, dict) else {}
