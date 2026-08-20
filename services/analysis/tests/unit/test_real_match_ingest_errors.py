"""Honest Riot error mapping for fresh-match ingest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx
from httpx import Response
from riftlens.adapters.riot.models import MatchDto, TimelineDto
from riftlens.config import Settings
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.pipeline.assemble.real_match import ensure_match_ingested

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "riot"
UNSEEN_MATCH_ID = "NA1_5624772791"


def _load_fixture(name: str) -> tuple[MatchDto, TimelineDto]:
    folder = FIXTURE_ROOT / name
    match = MatchDto.model_validate(
        json.loads((folder / "match.json").read_text(encoding="utf-8"))
    )
    timeline = TimelineDto.model_validate(
        json.loads((folder / "timeline.json").read_text(encoding="utf-8"))
    )
    return match, timeline


@respx.mock
@pytest.mark.asyncio
async def test_unseen_match_ingest_persisted_then_discoverable(settings: Settings) -> None:
    match, timeline = _load_fixture("NA1_fixture_b")
    match_id = UNSEEN_MATCH_ID
    base = f"https://americas.api.riotgames.com/lol/match/v5/matches/{match_id}"
    respx.get(base).mock(
        return_value=Response(
            200,
            json=json.loads(match.model_dump_json(by_alias=True)),
        )
    )
    respx.get(f"{base}/timeline").mock(
        return_value=Response(
            200,
            json=json.loads(timeline.model_dump_json(by_alias=True)),
        )
    )
    first = await ensure_match_ingested(match_id, api_key="RGAPI-test", settings=settings)
    assert first.fetched is True
    assert first.match_id == match_id

    second = await ensure_match_ingested(match_id, api_key="RGAPI-test", settings=settings)
    assert second.match_id == match_id
    assert second.match.info.participants
    assert respx.calls.call_count == 2


@respx.mock
@pytest.mark.asyncio
async def test_forbidden_maps_to_credential_not_match_not_ingested(settings: Settings) -> None:
    base = f"https://americas.api.riotgames.com/lol/match/v5/matches/{UNSEEN_MATCH_ID}"
    respx.get(base).mock(return_value=Response(403, json={"status": {"message": "forbidden"}}))
    with pytest.raises(ReplayError) as excinfo:
        await ensure_match_ingested(UNSEEN_MATCH_ID, api_key="RGAPI-test", settings=settings)
    err = excinfo.value
    assert err.code is ReplayErrorCode.RIOT_CREDENTIAL_MISSING
    assert excinfo.value.details.get("suggested_action") == "sign_in_api_key"
    assert "expired" in str(err).lower()


@respx.mock
@pytest.mark.asyncio
async def test_not_found_surfaces_honestly(settings: Settings) -> None:
    base = f"https://americas.api.riotgames.com/lol/match/v5/matches/{UNSEEN_MATCH_ID}"
    respx.get(base).mock(return_value=Response(404, json={"status": {"message": "missing"}}))
    with pytest.raises(ReplayError) as excinfo:
        await ensure_match_ingested(UNSEEN_MATCH_ID, api_key="RGAPI-test", settings=settings)
    err = excinfo.value
    assert err.code is ReplayErrorCode.MATCH_NOT_INGESTED
    assert "no record" in str(err).lower()
    assert err.details.get("suggested_action") == "choose_file"


@pytest.mark.asyncio
async def test_missing_credential_stops_before_riot(settings: Settings) -> None:
    with pytest.raises(ReplayError) as excinfo:
        await ensure_match_ingested(UNSEEN_MATCH_ID, api_key=None, settings=settings)
    assert excinfo.value.code is ReplayErrorCode.RIOT_CREDENTIAL_MISSING


def test_match_id_normalization_from_filename() -> None:
    from riftlens.rofl.identity import parse_filename_identity

    parsed = parse_filename_identity("NA1-5624772791.rofl")
    assert parsed.platform_id == "NA1"
    assert parsed.game_id == 5624772791
    assert f"{parsed.platform_id}_{parsed.game_id}" == UNSEEN_MATCH_ID
