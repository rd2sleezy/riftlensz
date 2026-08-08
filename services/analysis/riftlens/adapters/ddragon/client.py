from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

DDRAGON_ORIGIN = "https://ddragon.leagueoflegends.com"


class DDragonClient:
    def __init__(
        self,
        cache_dir: Path,
        http: httpx.AsyncClient | None = None,
        origin: str = DDRAGON_ORIGIN,
    ) -> None:
        self._cache_dir = cache_dir / "ddragon"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._http = http or httpx.AsyncClient(timeout=30.0)
        self._owns_http = http is None
        self._origin = origin.rstrip("/")

    async def aclose(self) -> None:
        """Close the owned httpx client. Assumes a caller-supplied client stays open."""
        if self._owns_http:
            await self._http.aclose()

    async def versions(self) -> list[str]:
        """Return Data Dragon version strings newest-first. Assumes the versions API shape."""
        payload = await self._get_json("/api/versions.json", cache_name="versions.json")
        if not isinstance(payload, list):
            raise ValueError("ddragon versions payload was not a list")
        return [str(item) for item in payload]

    async def items(self, version: str) -> dict[str, Any]:
        """Return item.json for a DDragon version. Assumes en_US locale."""
        payload = await self._get_json(
            f"/cdn/{version}/data/en_US/item.json",
            cache_name=f"{version}/item.json",
        )
        if not isinstance(payload, dict):
            raise ValueError("ddragon item payload was not an object")
        return payload

    async def champions(self, version: str) -> dict[str, Any]:
        """Return champion.json for a DDragon version. Assumes en_US locale."""
        payload = await self._get_json(
            f"/cdn/{version}/data/en_US/champion.json",
            cache_name=f"{version}/champion.json",
        )
        if not isinstance(payload, dict):
            raise ValueError("ddragon champion payload was not an object")
        return payload

    async def _get_json(self, path: str, cache_name: str) -> Any:
        cache_path = self._cache_dir / cache_name
        if cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))
        response = await self._http.get(f"{self._origin}{path}")
        response.raise_for_status()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(response.content)
        return response.json()
