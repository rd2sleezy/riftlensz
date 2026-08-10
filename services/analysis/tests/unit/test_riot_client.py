from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import pytest
import respx
import structlog
from riftlens.adapters.riot.cache import RiotCache
from riftlens.adapters.riot.client import RiotClient
from riftlens.adapters.riot.errors import Forbidden, NotFound
from riftlens.adapters.riot.models import MatchDto, TimelineDto
from riftlens.adapters.riot.rate_limiter import FakeClock, RiotRateLimiter
from riftlens.cli import _fetch_match
from riftlens.config import get_settings
from riftlens.logging import configure_logging

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "riot"
SAMPLE_KEY = "RGAPI-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PLACEHOLDER_KEY = "RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"


def _load_fixture_pair(name: str) -> tuple[dict[str, object], dict[str, object]]:
    folder = FIXTURE_ROOT / name
    match = json.loads((folder / "match.json").read_text(encoding="utf-8"))
    timeline = json.loads((folder / "timeline.json").read_text(encoding="utf-8"))
    return match, timeline


def test_fixtures_parse_without_validation_errors() -> None:
    for name in ("NA1_fixture_a", "NA1_fixture_b", "NA1_fixture_c"):
        match_payload, timeline_payload = _load_fixture_pair(name)
        match = MatchDto.model_validate(match_payload)
        timeline = TimelineDto.model_validate(timeline_payload)
        assert match.metadata.match_id
        assert match.info.participants
        assert timeline.info.frame_interval >= 1
        assert timeline.info.frames


@pytest.mark.asyncio
@respx.mock
async def test_429_retry_uses_fake_clock(tmp_path: Path) -> None:
    clock = FakeClock()
    limiter = RiotRateLimiter(clock=clock)
    cache = RiotCache(tmp_path)
    client = RiotClient(api_key=SAMPLE_KEY, cache=cache, limiter=limiter)
    url = "https://americas.api.riotgames.com/lol/match/v5/matches/NA1_xxxx"
    match_payload, _timeline = _load_fixture_pair("NA1_fixture_a")
    route = respx.get(url).mock(
        side_effect=[
            httpx.Response(
                429,
                headers={
                    "Retry-After": "3",
                    "X-Rate-Limit-Type": "application",
                    "X-App-Rate-Limit": "20:1,100:120",
                    "X-App-Rate-Limit-Count": "20:1,20:120",
                },
            ),
            httpx.Response(
                200,
                json=match_payload,
                headers={
                    "X-App-Rate-Limit": "20:1,100:120",
                    "X-App-Rate-Limit-Count": "1:1,1:120",
                    "X-Method-Rate-Limit": "500:10",
                    "X-Method-Rate-Limit-Count": "1:10",
                },
            ),
        ]
    )

    async def run() -> MatchDto:
        return await client.get_match("NA1_xxxx", "americas")

    task = __import__("asyncio").create_task(run())
    await clock.pump_until(task.done)
    result = await task
    assert result.metadata.match_id
    assert route.call_count == 2
    assert clock.now_ms() >= 3000
    assert len(limiter._app_buckets[0]._stamps) == 1  # noqa: SLF001
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_404_is_not_retried_and_is_negatively_cached(tmp_path: Path) -> None:
    cache = RiotCache(tmp_path)
    client = RiotClient(api_key=SAMPLE_KEY, cache=cache)
    url = "https://americas.api.riotgames.com/lol/match/v5/matches/NA1_missing"
    route = respx.get(url).mock(
        return_value=httpx.Response(404, json={"status": {"message": "no"}})
    )
    with pytest.raises(NotFound):
        await client.get_match("NA1_missing", "americas")
    with pytest.raises(NotFound):
        await client.get_match("NA1_missing", "americas")
    assert route.call_count == 1
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_403_mentions_expired_dev_key(tmp_path: Path) -> None:
    cache = RiotCache(tmp_path)
    client = RiotClient(api_key=SAMPLE_KEY, cache=cache)
    respx.get("https://americas.api.riotgames.com/lol/match/v5/matches/NA1_x").mock(
        return_value=httpx.Response(403, json={"status": {"message": "forbidden"}})
    )
    with pytest.raises(Forbidden, match="your Riot API key may have expired"):
        await client.get_match("NA1_x", "americas")
    await client.aclose()


def test_riot_key_never_appears_in_structlog_output(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(json_output=True, level=logging.DEBUG)
    log = structlog.get_logger("test")
    try:
        raise RuntimeError(f"upstream boom {PLACEHOLDER_KEY} {SAMPLE_KEY}")
    except RuntimeError:
        log.exception("request failed", token=SAMPLE_KEY)
    captured = capsys.readouterr().err + capsys.readouterr().out
    assert SAMPLE_KEY not in captured
    assert PLACEHOLDER_KEY not in captured
    assert "RGAPI-aaaaaaaa" not in captured
    assert "RGAPI-xxxxxxxx" not in captured


@pytest.mark.asyncio
@respx.mock
async def test_cli_fetch_match_second_run_is_cache_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("RIFTLENS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RIFTLENS_RIOT_API_KEY", SAMPLE_KEY)
    configure_logging(json_output=True)
    match_payload, timeline_payload = _load_fixture_pair("NA1_fixture_a")
    headers = {
        "X-App-Rate-Limit": "20:1,100:120",
        "X-App-Rate-Limit-Count": "1:1,1:120",
        "X-Method-Rate-Limit": "500:10",
        "X-Method-Rate-Limit-Count": "1:10",
    }
    match_route = respx.get("https://americas.api.riotgames.com/lol/match/v5/matches/NA1_xxxx").mock(
        return_value=httpx.Response(200, json=match_payload, headers=headers)
    )
    timeline_route = respx.get(
        "https://americas.api.riotgames.com/lol/match/v5/matches/NA1_xxxx/timeline"
    ).mock(return_value=httpx.Response(200, json=timeline_payload, headers=headers))
    await _fetch_match(match_id="NA1_xxxx", region="americas")
    assert match_route.call_count == 1
    assert timeline_route.call_count == 1
    await _fetch_match(match_id="NA1_xxxx", region="americas")
    assert match_route.call_count == 1
    assert timeline_route.call_count == 1
    err = capsys.readouterr().err
    assert "cache_hit" in err
    assert "true" in err.lower()
    get_settings.cache_clear()
