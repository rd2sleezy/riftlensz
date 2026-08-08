from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from riftlens.adapters.ddragon.client import DDragonClient
from riftlens.adapters.ddragon.patch_data import PatchDataProvider


@pytest.mark.asyncio
@respx.mock
async def test_patch_data_provider_resolves_item_gold(tmp_path: Path) -> None:
    respx.get("https://ddragon.leagueoflegends.com/api/versions.json").mock(
        return_value=httpx.Response(200, json=["12.4.1", "12.3.1"])
    )
    respx.get("https://ddragon.leagueoflegends.com/cdn/12.4.1/data/en_US/item.json").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"3031": {"gold": {"total": 3400, "base": 600, "sell": 2380}}}},
        )
    )
    respx.get("https://ddragon.leagueoflegends.com/cdn/12.4.1/data/en_US/champion.json").mock(
        return_value=httpx.Response(200, json={"data": {"Trundle": {"id": "Trundle"}}})
    )
    client = DDragonClient(tmp_path)
    provider = PatchDataProvider(client)
    await provider.load("12.4.423.2790")
    assert provider.version == "12.4.1"
    assert provider.item_gold(3031) == 3400
    await client.aclose()
