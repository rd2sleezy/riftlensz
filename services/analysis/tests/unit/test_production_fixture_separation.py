"""Production review lists hide fixture/demo trials; fixtures remain for tests/dev."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from riftlens.adapters.db.engine import init_database, make_session_factory
from riftlens.adapters.db.repositories import SqlGameplayRepository, SqlMatchRepository
from riftlens.config import Settings
from riftlens.domain.enums import EvidenceKind, IssueType, Role, Severity, Source
from riftlens.domain.evidence import Evidence
from riftlens.domain.finding import Finding
from riftlens.domain.ports import MatchRecord
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.domain.review import CoachingItem, MetricSnapshot, Review
from riftlens.gameplay.service import GameplaySourceService
from riftlens.pipeline.assemble.real_match import ensure_match_ingested
from riftlens.pipeline.assemble.review_presentation import (
    is_fixture_trial_presentation,
    list_review_presentations,
    review_to_presentation,
    save_review_presentation,
)
from riftlens.rofl.identity import identify_rofl
from sqlalchemy import Engine
from tests.fakes.fake_replay_host import FakeReplayHost
from tests.fakes.fake_replay_runtime import write_tiny_rofl

_AUTH = {"Authorization": "Bearer test-token"}
_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "riot"


@pytest.fixture
def engine(settings: Settings) -> Iterator[Engine]:
    created = init_database(settings)
    try:
        yield created
    finally:
        created.dispose()


def _finding() -> Finding:
    return Finding(
        id="01H9FINDING000000000000001",
        rule_id="R-001",
        rule_version=1,
        concept_id="RISK.DEATH_CAUSE",
        t_ms=140_000,
        severity=Severity.HIGH,
        confidence=0.8,
        title="Died on a pushed wave",
        evidence=(
            Evidence(
                kind=EvidenceKind.FACT,
                label="info_age_ms",
                value=59_000,
                source=Source.DERIVED,
                t_ms=140_000,
                confidence=0.7,
            ),
        ),
        explanation="Jungler unseen.",
        alternative="Hold wave.",
    )


def _review(
    *,
    match_id: str,
    champion: str = "Ahri",
    review_id: str = "01H9REVIEW0000000000000001",
) -> Review:
    finding = _finding()
    item = CoachingItem(
        id="01H9ITEM000000000000000001",
        root_concept_id="RISK.DEATH_CAUSE",
        rank=1,
        is_focus=True,
        is_strength=False,
        issue_type=IssueType.TACTICAL,
        impact_score=12.0,
        gold_equivalent=900.0,
        occurrences=2,
        confidence=0.8,
        title="Know the jungler",
        body="Likely: you died on a pushed wave.",
        the_fix="Ward before pushing.",
        next_game_check="Die less on a crash.",
        exemplar_finding_id=finding.id,
        finding_ids=(finding.id,),
        evidence_timestamps_ms=(140_000,),
        grouping_reason="same concept",
        certainty="likely",
        cluster_id="c1",
        cost_summary="~900g",
    )
    return Review(
        id=review_id,
        player_id="p1",
        match_id=match_id,
        participant_id=5,
        champion=champion,
        role=Role.MIDDLE,
        rank="SILVER",
        patch="15.16",
        duration_ms=1_800_000,
        result="LOSS",
        rule_pack_version="1",
        engine_version="test",
        llm_provider="null",
        status="ready",
        summary_text="ok",
        findings=(finding,),
        clusters=(),
        grouping_log=(),
        focus_items=(item,),
        secondary_items=(),
        strengths=(),
        metrics=(
            MetricSnapshot(
                metric_id="M-01",
                value=1.0,
                unit="count",
                phase=None,
                confidence=1.0,
                baseline_percentile=None,
                sample_context=None,
                detail={},
            ),
        ),
        created_at=1,
        completed_at=1,
        unpaired_match_timeline=True,
        overall_scores={},
    )


async def _seed_match(engine: Engine, match_id: str) -> None:
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
            game_duration_ms=1_800_000,
            game_end_ts=1_800_001,
            winning_team=100,
            raw_match_blob=None,
            raw_timeline_blob=None,
            ingested_at=2,
        )
    )


def test_fixture_reviews_absent_from_normal_list(settings: Settings) -> None:
    fixture = review_to_presentation(
        _review(match_id="NA1_fixture_a"), fixture_id="NA1_fixture_a"
    )
    real = review_to_presentation(
        _review(match_id="NA1_5620410094", champion="Jinx", review_id="01H9REVIEWREAL000000000001"),
        fixture_id=None,
    )
    save_review_presentation(settings.data_dir, fixture)
    save_review_presentation(settings.data_dir, real)
    listed = list_review_presentations(settings.data_dir)
    assert [row["match_id"] for row in listed] == ["NA1_5620410094"]
    assert all(not is_fixture_trial_presentation(row) for row in listed)


def test_existing_fixture_rows_hidden_but_fetchable_by_id(
    client: TestClient, settings: Settings
) -> None:
    fixture = review_to_presentation(
        _review(match_id="NA1_fixture_b"), fixture_id="NA1_fixture_b"
    )
    save_review_presentation(settings.data_dir, fixture)
    listed = client.get("/reviews", headers=_AUTH)
    assert listed.status_code == 200
    assert listed.json()["reviews"] == []
    fetched = client.get(f"/reviews/{fixture['id']}", headers=_AUTH)
    assert fetched.status_code == 200
    assert fetched.json()["fixture_id"] == "NA1_fixture_b"


def test_include_fixtures_flag_for_developer_lists(client: TestClient, settings: Settings) -> None:
    fixture = review_to_presentation(
        _review(match_id="NA1_fixture_c"), fixture_id="NA1_fixture_c"
    )
    save_review_presentation(settings.data_dir, fixture)
    hidden = client.get("/reviews", headers=_AUTH)
    assert hidden.json()["reviews"] == []
    shown = client.get("/reviews?include_fixtures=true", headers=_AUTH)
    assert shown.status_code == 200
    assert any(row["id"] == fixture["id"] for row in shown.json()["reviews"])


def test_fixture_infrastructure_still_builds_reviews(client: TestClient) -> None:
    response = client.post(
        "/reviews/from-fixture",
        headers=_AUTH,
        json={"fixture_id": "NA1_fixture_b", "participant_id": 5, "rank": "SILVER"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fixture_id"] == "NA1_fixture_b"
    assert body["findings"]


def test_purge_fixtures_is_safe_and_optional(client: TestClient, settings: Settings) -> None:
    fixture = review_to_presentation(
        _review(match_id="NA1_fixture_a"), fixture_id="NA1_fixture_a"
    )
    real = review_to_presentation(
        _review(match_id="NA1_5620410094", review_id="01H9REVIEWREAL000000000002"),
        fixture_id=None,
    )
    save_review_presentation(settings.data_dir, fixture)
    save_review_presentation(settings.data_dir, real)
    purged = client.post("/reviews/purge-fixtures", headers=_AUTH)
    assert purged.status_code == 200
    assert purged.json()["removed"] == 1
    assert list_review_presentations(settings.data_dir, include_fixtures=True) == (
        list_review_presentations(settings.data_dir)
    )
    assert any(row["id"] == real["id"] for row in list_review_presentations(settings.data_dir))


def test_real_reviews_still_appear(client: TestClient, settings: Settings) -> None:
    real = review_to_presentation(
        _review(match_id="NA1_5620410094", champion="Ashe", review_id="01H9REVIEWREAL000000000003"),
        fixture_id=None,
    )
    save_review_presentation(settings.data_dir, real)
    listed = client.get("/reviews", headers=_AUTH)
    assert any(row["match_id"] == "NA1_5620410094" for row in listed.json()["reviews"])


def test_missing_credentials_do_not_fall_back_to_fixtures(settings: Settings) -> None:
    import asyncio

    with pytest.raises(ReplayError) as excinfo:
        asyncio.run(ensure_match_ingested("NA1_5620410094", api_key=None, settings=settings))
    assert excinfo.value.code is ReplayErrorCode.RIOT_CREDENTIAL_MISSING
    assert "Riot access is required" in str(excinfo.value)


@pytest.mark.asyncio
async def test_real_replay_cannot_bind_to_fixture_review(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_5620410094")
    await _seed_match(engine, "NA1_fixture_a")
    factory = make_session_factory(engine)
    service = GameplaySourceService(
        host=FakeReplayHost(),
        gameplay=SqlGameplayRepository(factory),
        matches=SqlMatchRepository(factory),
    )
    rofl = write_tiny_rofl(tmp_path / "NA1-5620410094.rofl")
    outcome = await service.import_rofl(str(rofl), now_ms=10, match_id="NA1_fixture_a")
    assert outcome.ok is False
    assert outcome.error is not None
    assert outcome.error.code is ReplayErrorCode.MATCH_IDENTITY_MISMATCH
    assert outcome.match_id == "NA1_5620410094"
    assert list(await service._gameplay.list_sources_for_match("NA1_fixture_a")) == []


def test_replay_identity_determines_real_match(tmp_path: Path) -> None:
    path = write_tiny_rofl(tmp_path / "NA1-5620410094.rofl")
    identified = identify_rofl(str(path))
    assert identified.identity is not None
    assert identified.identity.match_id_hint == "NA1_5620410094"
    assert not identified.identity.match_id_hint.startswith("NA1_fixture_")


def test_fixture_files_still_present_for_tests() -> None:
    for fixture_id in ("NA1_fixture_a", "NA1_fixture_b", "NA1_fixture_c"):
        assert (_FIXTURE_ROOT / fixture_id / "match.json").is_file()
        assert (_FIXTURE_ROOT / fixture_id / "timeline.json").is_file()
