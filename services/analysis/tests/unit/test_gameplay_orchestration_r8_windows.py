from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from riftlens.adapters.db.engine import init_database, make_session_factory
from riftlens.adapters.db.repositories import SqlGameplayRepository, SqlMatchRepository
from riftlens.adapters.riot.cache import RiotCache
from riftlens.adapters.riot.client import RiotClient
from riftlens.adapters.riot.errors import RiotError
from riftlens.adapters.riot.rate_limiter import RiotRateLimiter
from riftlens.config import Settings, get_settings
from riftlens.domain.gameplay_source import SourceCapability
from riftlens.domain.replay_errors import ReplayErrorCode
from riftlens.domain.sync_map import SEEK_LEAD_IN_MS
from riftlens.gameplay.service import GameplaySourceService
from riftlens.pipeline.ingest_riot.persist import persist_riot_match
from riftlens.replay_host.factory import create_replay_host
from riftlens.replay_host.seek import REAL_SEEK_TOLERANCE_MS

MATCH_ID = "NA1_5617764200"


def _resolve_t4_rofl() -> Path | None:
    for key in ("RIFTLENS_R8_ROFL", "RIFTLENS_R6_ROFL", "RIFTLENS_REPLAY_ROFL"):
        raw = os.environ.get(key)
        if raw:
            path = Path(raw)
            return path if path.is_file() else None
    folders = (
        Path.home() / "OneDrive" / "Documents" / "League of Legends" / "Replays",
        Path.home() / "Documents" / "League of Legends" / "Replays",
    )
    for folder in folders:
        if not folder.is_dir():
            continue
        preferred = sorted(folder.glob("*5617764200*.rofl"))
        if preferred:
            return preferred[0]
        found = sorted(folder.glob("*.rofl"))
        if found:
            return found[0]
    return None


async def _ingest_cached_match(engine, match_id: str) -> bool:
    settings = get_settings()
    key = settings.riot_api_key.strip() or "RGAPI-cache-read"
    cache = RiotCache(settings.cache_dir)
    client = RiotClient(api_key=key, cache=cache, limiter=RiotRateLimiter())
    try:
        match = await client.get_match(match_id, "americas")
        timeline = await client.get_timeline(match_id, "americas")
    except RiotError:
        return False
    finally:
        await client.aclose()
    if match.metadata.match_id != match_id:
        return False
    await persist_riot_match(
        SqlMatchRepository(make_session_factory(engine)),
        match,
        timeline,
        now_ms=1,
    )
    return True


@pytest.mark.skipif(
    os.environ.get("RIFTLENS_R8_T4") != "1",
    reason="set RIFTLENS_R8_T4=1 for real R.8 Windows orchestration",
)
def test_t4_r8_orchestration_reveal(tmp_path: Path) -> None:
    rofl = _resolve_t4_rofl()
    if rofl is None:
        pytest.skip("No .rofl found via RIFTLENS_R8_ROFL / well-known Replays folder")
    settings = Settings(data_dir=tmp_path)
    engine = init_database(settings)
    try:
        ingested = asyncio.run(_ingest_cached_match(engine, MATCH_ID))
        if not ingested:
            pytest.skip("MATCH-V5 NA1_5617764200 not in H.2 cache and fetch failed")
        host = create_replay_host()
        service = GameplaySourceService(
            host=host,
            gameplay=SqlGameplayRepository(make_session_factory(engine)),
            matches=SqlMatchRepository(make_session_factory(engine)),
        )
        imported = asyncio.run(service.import_rofl(str(rofl), now_ms=10))
        assert imported.ok, imported.error
        assert imported.match_id == MATCH_ID
        assert imported.identity is not None
        assert imported.identity.platform_id == "NA1"
        assert imported.identity.game_id == 5617764200
        env = host.check_environment()
        if env.error is not None and env.error.code is ReplayErrorCode.LIVE_GAME_IN_PROGRESS:
            pytest.fail("Live game or queue detected. Finish it, then re-run R.8 T4.")
        if env.error is not None and env.error.code is ReplayErrorCode.INSTALL_NOT_FOUND:
            pytest.skip(f"League install not found: {env.error}")
        source_id = imported.source_id or ""
        first = asyncio.run(
            service.reveal(source_id, 180_000, lead_in_ms=SEEK_LEAD_IN_MS, now_ms=20)
        )
        if first.error is not None and first.error.code is ReplayErrorCode.LIVE_GAME_IN_PROGRESS:
            pytest.fail("Live game or queue detected during reveal. Finish it, then re-run.")
        assert first.ok, first.error
        assert first.clock is not None
        assert SourceCapability.SEEK in first.capabilities
        second = asyncio.run(service.reveal(source_id, 600_000, lead_in_ms=8_000, now_ms=21))
        third = asyncio.run(service.reveal(source_id, 1_122_000, lead_in_ms=8_000, now_ms=22))
        assert second.ok, second.error
        assert third.ok, third.error
        for outcome, game_ms in ((first, 180_000), (second, 600_000), (third, 1_122_000)):
            assert outcome.lead_in_ms == 8_000
            assert outcome.target_game_ms == game_ms - 8_000
            assert outcome.target_source_ms is not None
            assert outcome.landed_source_ms is not None
            delta = abs(outcome.landed_source_ms - outcome.target_source_ms)
            assert delta <= REAL_SEEK_TOLERANCE_MS
        asyncio.run(service.close_session(source_id, now_ms=30))
        host2 = create_replay_host()
        restarted = GameplaySourceService(
            host=host2,
            gameplay=SqlGameplayRepository(make_session_factory(engine)),
            matches=SqlMatchRepository(make_session_factory(engine)),
        )
        resolved = asyncio.run(restarted.resolve_source(source_id))
        assert resolved is not None
        assert resolved.source.clock.verified or resolved.source.clock.confidence.value
        assert host2.get_state().phase.value == "IDLE"
        reopened = asyncio.run(
            restarted.reveal(source_id, 240_000, lead_in_ms=8_000, now_ms=40)
        )
        assert reopened.ok, reopened.error
        asyncio.run(restarted.close_session(source_id, now_ms=41))
    finally:
        engine.dispose()
