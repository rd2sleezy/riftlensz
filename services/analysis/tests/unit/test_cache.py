from __future__ import annotations

import time
from pathlib import Path

from riftlens.adapters.riot.cache import RiotCache


def test_key_ignores_api_key_query_param(tmp_path: Path) -> None:
    cache = RiotCache(tmp_path)
    left = cache.key("https://americas.api.riotgames.com/lol/match/v5/matches/NA1_1?api_key=secret")
    right = cache.key("https://americas.api.riotgames.com/lol/match/v5/matches/NA1_1")
    assert left == right


def test_put_get_roundtrip_gzip_layout(tmp_path: Path) -> None:
    cache = RiotCache(tmp_path)
    url = "https://americas.api.riotgames.com/lol/match/v5/matches/NA1_1"
    cache.put(url, b'{"ok":true}', ttl_s=None)
    digest = cache.key(url)
    blob = tmp_path / "riot" / digest[:2] / f"{digest}.json.gz"
    assert blob.is_file()
    assert cache.get(url) == b'{"ok":true}'


def test_negative_entry_expires(tmp_path: Path) -> None:
    cache = RiotCache(tmp_path)
    url = "https://americas.api.riotgames.com/lol/match/v5/matches/NA1_missing"
    cache.put_negative(url, status=404, ttl_s=1)
    hit = cache.lookup(url)
    assert hit is not None
    assert hit.status == 404
    assert cache.get(url) is None
    with cache._connect() as conn:  # noqa: SLF001
        conn.execute("UPDATE riot_cache SET ttl_expires_at = ?", (int(time.time()) - 5,))
        conn.commit()
    assert cache.lookup(url) is None
