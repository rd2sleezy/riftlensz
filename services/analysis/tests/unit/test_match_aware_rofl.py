"""Match-aware .rofl binding and real-match review assembly."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import respx
from httpx import Response
from riftlens.adapters.db.engine import init_database, make_session_factory
from riftlens.adapters.db.repositories import SqlGameplayRepository, SqlMatchRepository
from riftlens.adapters.riot.models import MatchDto, TimelineDto
from riftlens.config import Settings
from riftlens.domain.ports import MatchRecord
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.gameplay.service import GameplaySourceService
from riftlens.pipeline.assemble.real_match import (
    build_real_match_review,
    ensure_match_ingested,
    list_match_participants,
)
from riftlens.pipeline.ingest_riot.persist import persist_riot_match
from riftlens.rofl.identity import identify_rofl
from sqlalchemy import Engine
from tests.fakes.fake_replay_host import FakeReplayHost
from tests.fakes.fake_replay_runtime import write_tiny_rofl

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "riot"
REAL_MATCH_ID = "NA1_5620410094"
FIXTURE_A = "NA1_fixture_a"


@pytest.fixture
def engine(settings: Settings) -> Iterator[Engine]:
    created = init_database(settings)
    try:
        yield created
    finally:
        created.dispose()


def _service(engine: Engine) -> GameplaySourceService:
    factory = make_session_factory(engine)
    return GameplaySourceService(
        host=FakeReplayHost(),
        gameplay=SqlGameplayRepository(factory),
        matches=SqlMatchRepository(factory),
    )


async def _seed_match(engine: Engine, match_id: str, duration_ms: int = 1_800_000) -> None:
    repo = SqlMatchRepository(make_session_factory(engine))
    await repo.upsert_match(
        MatchRecord(
            match_id=match_id,
            platform="na1",
            region="americas",
            queue_id=420,
            map_id=11,
            game_version="16.9.1.123",
            patch="16.9",
            game_creation=1,
            game_start=1,
            game_duration_ms=duration_ms,
            game_end_ts=duration_ms + 1,
            winning_team=100,
            raw_match_blob=None,
            raw_timeline_blob=None,
            ingested_at=2,
        )
    )


def _load_fixture(fixture_id: str) -> tuple[MatchDto, TimelineDto]:
    match = MatchDto.model_validate(
        json.loads((FIXTURE_ROOT / fixture_id / "match.json").read_text(encoding="utf-8"))
    )
    timeline = TimelineDto.model_validate(
        json.loads((FIXTURE_ROOT / fixture_id / "timeline.json").read_text(encoding="utf-8"))
    )
    return match, timeline


def test_filename_na1_gameid_resolves_to_riot_match_id(tmp_path: Path) -> None:
    path = write_tiny_rofl(tmp_path / "NA1-5620410094.rofl")
    identified = identify_rofl(str(path))
    assert identified.error is None
    assert identified.identity is not None
    assert identified.identity.platform_id == "NA1"
    assert identified.identity.game_id == 5620410094
    assert identified.identity.match_id_hint == REAL_MATCH_ID


@pytest.mark.asyncio
async def test_matching_replay_binds_to_matching_review(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, REAL_MATCH_ID)
    rofl = write_tiny_rofl(tmp_path / "NA1-5620410094.rofl")
    outcome = await _service(engine).import_rofl(
        str(rofl), now_ms=10, match_id=REAL_MATCH_ID
    )
    assert outcome.ok is True
    assert outcome.match_id == REAL_MATCH_ID
    assert outcome.source_id is not None
    assert outcome.error is None


@pytest.mark.asyncio
async def test_mismatched_replay_rejected_against_unrelated_review(
    engine: Engine, tmp_path: Path
) -> None:
    await _seed_match(engine, REAL_MATCH_ID)
    await _seed_match(engine, FIXTURE_A)
    rofl = write_tiny_rofl(tmp_path / "NA1-5620410094.rofl")
    outcome = await _service(engine).import_rofl(
        str(rofl), now_ms=11, match_id=FIXTURE_A
    )
    assert outcome.ok is False
    assert outcome.error is not None
    assert outcome.error.code is ReplayErrorCode.MATCH_IDENTITY_MISMATCH
    assert outcome.match_id == REAL_MATCH_ID
    assert outcome.error.details.get("open_match_id") == FIXTURE_A
    assert outcome.error.details.get("replay_match_id") == REAL_MATCH_ID
    assert outcome.error.details.get("suggested_action") == "open_replay_match"
    sources = await _service(engine)._gameplay.list_sources_for_match(FIXTURE_A)
    assert sources == []


@pytest.mark.asyncio
async def test_fixture_review_cannot_silently_receive_real_replay(
    engine: Engine, tmp_path: Path
) -> None:
    await _seed_match(engine, FIXTURE_A)
    await _seed_match(engine, REAL_MATCH_ID)
    for fixture_id in ("NA1_fixture_a", "NA1_fixture_b", "NA1_fixture_c"):
        await _seed_match(engine, fixture_id)
        rofl = write_tiny_rofl(tmp_path / "NA1-5620410094.rofl")
        outcome = await _service(engine).import_rofl(
            str(rofl), now_ms=12, match_id=fixture_id
        )
        assert outcome.ok is False
        assert outcome.error is not None
        assert outcome.error.code is ReplayErrorCode.MATCH_IDENTITY_MISMATCH
        linked = await _service(engine)._gameplay.list_sources_for_match(fixture_id)
        assert linked == []


@pytest.mark.asyncio
async def test_unresolved_identity_requires_explicit_resolution(
    engine: Engine, tmp_path: Path
) -> None:
    await _seed_match(engine, REAL_MATCH_ID)
    rofl = write_tiny_rofl(tmp_path / "mystery.rofl")
    outcome = await _service(engine).import_rofl(
        str(rofl), now_ms=13, match_id=REAL_MATCH_ID
    )
    assert outcome.ok is False
    assert outcome.error is not None
    assert outcome.error.code is ReplayErrorCode.MATCH_ID_UNRESOLVED
    assert outcome.error.details.get("suggested_action") == "pick_match"


@pytest.mark.asyncio
async def test_open_match_id_not_used_for_binding_when_absent(
    engine: Engine, tmp_path: Path
) -> None:
    await _seed_match(engine, REAL_MATCH_ID)
    rofl = write_tiny_rofl(tmp_path / "NA1-5620410094.rofl")
    outcome = await _service(engine).import_rofl(str(rofl), now_ms=14, match_id=None)
    assert outcome.ok is True
    assert outcome.match_id == REAL_MATCH_ID


@respx.mock
@pytest.mark.asyncio
async def test_participant_selection_reaches_review_builder(settings: Settings) -> None:
    match, timeline = _load_fixture("NA1_fixture_b")
    match_id = match.metadata.match_id
    base = f"https://americas.api.riotgames.com/lol/match/v5/matches/{match_id}"
    respx.get(base).mock(
        return_value=Response(200, json=json.loads(match.model_dump_json(by_alias=True)))
    )
    respx.get(f"{base}/timeline").mock(
        return_value=Response(200, json=json.loads(timeline.model_dump_json(by_alias=True)))
    )
    participants = await list_match_participants(
        match_id, api_key="RGAPI-test", settings=settings
    )
    assert len(participants) == 10
    chosen = participants[2]
    pid = int(chosen["participant_id"])
    built = await build_real_match_review(
        match_id, pid, api_key="RGAPI-test", settings=settings
    )
    assert built.match_id == match_id
    assert built.participant_id == pid
    assert built.presentation["participant_id"] == pid
    assert built.presentation["match_id"] == match_id
    assert built.presentation["fixture_id"] is None
    assert built.presentation["findings"]
    assert built.champion


@respx.mock
@pytest.mark.asyncio
async def test_missing_credential_stops_at_boundary(settings: Settings) -> None:
    with pytest.raises(ReplayError) as excinfo:
        await ensure_match_ingested(REAL_MATCH_ID, api_key=None, settings=settings)
    assert excinfo.value.code is ReplayErrorCode.RIOT_CREDENTIAL_MISSING


@pytest.mark.asyncio
async def test_persist_then_list_participants_without_network(
    settings: Settings,
) -> None:
    match, timeline = _load_fixture("NA1_fixture_a")
    engine = init_database(settings)
    try:
        repo = SqlMatchRepository(make_session_factory(engine))
        await persist_riot_match(repo, match, timeline)
    finally:
        engine.dispose()
    rows = await list_match_participants(match.metadata.match_id, settings=settings)
    assert len(rows) == 10
    assert all("champion_name" in row for row in rows)
