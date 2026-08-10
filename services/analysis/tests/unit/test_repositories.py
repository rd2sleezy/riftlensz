from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from riftlens.adapters.db.engine import checkpoint_wal, init_database, make_session_factory
from riftlens.adapters.db.loaders import RuleDefinitionLoader, TaxonomyLoader
from riftlens.adapters.db.repositories import (
    SqlCoachingRepository,
    SqlFindingRepository,
    SqlMatchRepository,
    SqlMediaRepository,
    SqlMetricRepository,
    SqlPlayerRepository,
    SqlReviewRepository,
    SqlSyncRepository,
)
from riftlens.adapters.riot.models import MatchDto, TimelineDto
from riftlens.config import Settings
from riftlens.domain.ids import new_ulid
from riftlens.domain.ports import (
    BaselineStatRecord,
    ChampionProfileRecord,
    CoachingItemRecord,
    EvidenceRecord,
    FindingFeedbackRecord,
    FindingRecord,
    FocusCommitmentRecord,
    LayoutProfileRecord,
    MediaAssetRecord,
    MetricValueRecord,
    PlayerAccountRecord,
    PlayerChampionProfileRecord,
    PlayerRecord,
    PlayerTrendRecord,
    ReviewRecord,
    SyncMapRecord,
)
from riftlens.pipeline.ingest_riot.persist import persist_riot_match
from sqlalchemy import Engine, inspect, text

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "riot"
_THREE_MB = 3 * 1024 * 1024


@pytest.fixture
def engine(settings: Settings) -> Iterator[Engine]:
    created = init_database(settings)
    try:
        yield created
    finally:
        created.dispose()


def _load_fixture(name: str = "NA1_fixture_a") -> tuple[MatchDto, TimelineDto]:
    folder = FIXTURE_ROOT / name
    match = MatchDto.model_validate(json.loads((folder / "match.json").read_text(encoding="utf-8")))
    timeline = TimelineDto.model_validate(
        json.loads((folder / "timeline.json").read_text(encoding="utf-8"))
    )
    return match, timeline


def _table_counts(engine: Engine) -> dict[str, int]:
    names = inspect(engine).get_table_names()
    counts: dict[str, int] = {}
    with engine.connect() as connection:
        for name in names:
            if name == "alembic_version":
                continue
            counts[name] = int(
                connection.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar_one()
            )
    return counts


def _db_bytes(path: Path) -> int:
    total = path.stat().st_size
    for suffix in ("-wal", "-shm"):
        extra = Path(str(path) + suffix)
        if extra.exists():
            total += extra.stat().st_size
    return total


@pytest.mark.asyncio
async def test_ingest_fixture_a_twice_is_idempotent(engine: Engine) -> None:
    repo = SqlMatchRepository(make_session_factory(engine))
    match, timeline = _load_fixture()
    await persist_riot_match(repo, match, timeline, now_ms=1_700_000_000_000)
    first = _table_counts(engine)
    await persist_riot_match(repo, match, timeline, now_ms=1_700_000_000_000)
    second = _table_counts(engine)
    assert first == second
    assert first["match"] == 1
    assert first["match_participation"] == 10
    assert first["timeline_event"] > 0
    assert first["participant_frame"] > 0


@pytest.mark.asyncio
async def test_one_match_occupies_less_than_3mb(settings: Settings, engine: Engine) -> None:
    repo = SqlMatchRepository(make_session_factory(engine))
    match, timeline = _load_fixture()
    checkpoint_wal(engine)
    before = _db_bytes(settings.db_path)
    await persist_riot_match(repo, match, timeline, now_ms=1_700_000_000_000)
    checkpoint_wal(engine)
    delta = _db_bytes(settings.db_path) - before
    assert 0 < delta < _THREE_MB


@pytest.mark.asyncio
async def test_two_async_writers_insert_findings(engine: Engine) -> None:
    factory = make_session_factory(engine)
    players = SqlPlayerRepository(factory)
    matches = SqlMatchRepository(factory)
    reviews = SqlReviewRepository(factory)
    findings = SqlFindingRepository(factory)
    player_id = new_ulid()
    review_id = new_ulid()
    await players.upsert_player(
        PlayerRecord(id=player_id, display_name="local", is_local_user=1, created_at=1)
    )
    match, timeline = _load_fixture()
    await persist_riot_match(matches, match, timeline, now_ms=2)
    await reviews.upsert(
        ReviewRecord(
            id=review_id,
            player_id=player_id,
            match_id=match.metadata.match_id,
            participant_id=5,
            media_asset_id=None,
            sync_map_id=None,
            rule_pack_version="stub-1",
            engine_version="0.1.0",
            analysis_tiers='["RIOT"]',
            status="COMPLETE",
            summary_text=None,
            overall_scores=None,
            llm_provider=None,
            llm_model=None,
            llm_prompt_version=None,
            created_at=3,
            completed_at=4,
        )
    )
    first_id = new_ulid()
    second_id = new_ulid()
    await _gather_findings(findings, review_id, first_id, second_id)
    stored = await findings.list_for_review(review_id)
    assert {row.id for row in stored} == {first_id, second_id}
    assert len(await findings.list_evidence(first_id)) == 1
    assert len(await findings.list_evidence(second_id)) == 1


async def _gather_findings(
    findings: SqlFindingRepository, review_id: str, first_id: str, second_id: str
) -> None:
    import asyncio

    await asyncio.gather(
        findings.add(_finding(first_id, review_id, t_ms=10_000), [_evidence(first_id, "gold")]),
        findings.add(_finding(second_id, review_id, t_ms=20_000), [_evidence(second_id, "hp")]),
    )


def test_taxonomy_and_rule_loaders_are_idempotent(engine: Engine) -> None:
    factory = make_session_factory(engine)
    before = _table_counts(engine)
    assert before["concept"] >= 1
    assert before["rule_definition"] >= 1
    TaxonomyLoader(factory).load()
    RuleDefinitionLoader(factory).load()
    TaxonomyLoader(factory).load()
    RuleDefinitionLoader(factory).load()
    after = _table_counts(engine)
    assert after["concept"] == before["concept"]
    assert after["rule_definition"] == before["rule_definition"]


@pytest.mark.asyncio
async def test_repository_round_trips(engine: Engine) -> None:
    factory = make_session_factory(engine)
    players = SqlPlayerRepository(factory)
    matches = SqlMatchRepository(factory)
    media = SqlMediaRepository(factory)
    syncs = SqlSyncRepository(factory)
    reviews = SqlReviewRepository(factory)
    findings = SqlFindingRepository(factory)
    metrics = SqlMetricRepository(factory)
    coaching = SqlCoachingRepository(factory)

    player_id = new_ulid()
    account_id = new_ulid()
    await players.upsert_player(
        PlayerRecord(id=player_id, display_name="Ryland", is_local_user=1, created_at=10)
    )
    await players.upsert_account(
        PlayerAccountRecord(
            id=account_id,
            player_id=player_id,
            puuid="puuid-1",
            game_name="Ryland",
            tag_line="NA1",
            platform="na1",
            region="americas",
            summoner_level=50,
            tier="GOLD",
            rank_division="II",
            league_points=47,
            rank_updated_at=11,
        )
    )
    match, timeline = _load_fixture()
    await persist_riot_match(matches, match, timeline, now_ms=12)
    match_id = match.metadata.match_id
    stored_match = await matches.get_match(match_id)
    assert stored_match is not None
    assert stored_match.patch == "12.4"
    assert stored_match.platform == "na1"
    assert len(await matches.list_participations(match_id)) == 10

    layout = LayoutProfileRecord(
        id=new_ulid(),
        width=1920,
        height=1080,
        ui_scale_estimate=1.0,
        minimap_flipped=0,
        minimap_rect="[1600,780,300,300]",
        clock_rect="[920,0,80,32]",
        regions="{}",
        occluded_regions=None,
        world_to_minimap_affine=None,
        created_at=13,
    )
    await media.upsert_layout_profile(layout)
    asset = MediaAssetRecord(
        id=new_ulid(),
        content_hash="abc" * 20,
        original_path="/tmp/vod.mp4",
        playable_path=None,
        proxy_path=None,
        thumbnail_sheet_path=None,
        container="mp4",
        codec="h264",
        pix_fmt="yuv420p",
        width=1920,
        height=1080,
        fps_num=60,
        fps_den=1,
        duration_ms=1_200_000,
        size_bytes=1000,
        source_kind="PLAYER_POV",
        layout_profile_id=layout.id,
        quality_score=0.9,
        imported_at=14,
        last_accessed_at=14,
    )
    await media.upsert_asset(asset)
    sync = SyncMapRecord(
        id=new_ulid(),
        media_asset_id=asset.id,
        match_id=match_id,
        method="auto",
        segments="[]",
        pauses="[]",
        quality="{}",
        verified=1,
        created_at=15,
    )
    await syncs.upsert(sync)
    review_id = new_ulid()
    await reviews.upsert(
        ReviewRecord(
            id=review_id,
            player_id=player_id,
            match_id=match_id,
            participant_id=5,
            media_asset_id=asset.id,
            sync_map_id=sync.id,
            rule_pack_version="stub-1",
            engine_version="0.1.0",
            analysis_tiers='["RIOT","DERIVED"]',
            status="COMPLETE",
            summary_text="ok",
            overall_scores="{}",
            llm_provider="null",
            llm_model=None,
            llm_prompt_version="v1",
            created_at=16,
            completed_at=17,
        )
    )
    finding_id = new_ulid()
    await findings.add(
        _finding(finding_id, review_id, t_ms=60_000),
        [_evidence(finding_id, "cs")],
    )
    await findings.add_feedback(
        FindingFeedbackRecord(
            finding_id=finding_id, verdict="HELPFUL", note="yes", created_at=18
        )
    )
    await metrics.replace_for_review(
        review_id,
        [
            MetricValueRecord(
                review_id=review_id,
                metric_id="M-01",
                phase="EARLY",
                value=6.1,
                unit="cs/min",
                confidence=1.0,
                baseline_key="GOLD|MIDDLE|12.4|MAGE",
                baseline_p50=6.0,
                baseline_percentile=55.0,
                detail_json="{}",
            )
        ],
    )
    await coaching.replace_for_review(
        review_id,
        [
            CoachingItemRecord(
                id=new_ulid(),
                review_id=review_id,
                root_concept_id="LANING",
                rank=1,
                is_focus=1,
                is_strength=0,
                issue_type="TACTICAL",
                impact_score=12.0,
                gold_equivalent=300.0,
                occurrences=2,
                confidence=0.8,
                title="Hold the wave",
                body="Crash before recalling.",
                the_fix="Slow push then crash.",
                next_game_check="Crash before base",
                exemplar_finding_id=finding_id,
                finding_ids=(finding_id,),
            )
        ],
    )
    await players.upsert_trend(
        PlayerTrendRecord(
            id=new_ulid(),
            player_id=player_id,
            concept_id="LANING",
            metric_id="M-01",
            window_start=0,
            window_end=20,
            n_matches=5,
            value=6.2,
            prev_value=5.8,
            direction="IMPROVING",
            significance=0.04,
        )
    )
    await players.upsert_champion_profile(
        PlayerChampionProfileRecord(
            id=new_ulid(),
            player_id=player_id,
            champion_id=103,
            role="MIDDLE",
            games=12,
            aggregates_json="{}",
            updated_at=19,
        )
    )
    await coaching.upsert_focus_commitment(
        FocusCommitmentRecord(
            id=new_ulid(),
            player_id=player_id,
            review_id=review_id,
            concept_id="LANING",
            metric_id="M-01",
            target_value=7.0,
            comparison="GTE",
            created_at=20,
            resolved_review_id=None,
            outcome="PENDING",
        )
    )
    await metrics.upsert_champion_profile(
        ChampionProfileRecord(
            champion_id=103,
            patch="12.4",
            name="Ahri",
            class_tags='["MAGE"]',
            behavior_tags='["ROAMING"]',
            power_spikes="[]",
            win_condition="{}",
            typical_build=None,
            abilities="{}",
        )
    )
    await metrics.upsert_baseline(
        BaselineStatRecord(
            metric_id="M-01",
            tier="GOLD",
            role="MIDDLE",
            champion_class="MAGE",
            patch="12.4",
            phase="EARLY",
            n=100,
            p10=4.0,
            p25=5.0,
            p50=6.0,
            p75=7.0,
            p90=8.0,
            mean=6.1,
            stddev=1.0,
            updated_at=21,
        )
    )

    assert (await players.get_player(player_id)) is not None
    assert (await players.get_account_by_puuid("puuid-1")) is not None
    assert (await media.get_asset(asset.id)) is not None
    assert (await syncs.get_by_media_and_match(asset.id, match_id)) is not None
    assert (await reviews.get(review_id)) is not None
    assert (await findings.get(finding_id)) is not None
    assert (await metrics.list_for_review(review_id))[0].metric_id == "M-01"
    items = await coaching.list_for_review(review_id)
    assert items[0].finding_ids == (finding_id,)
    baseline = await metrics.get_baseline("M-01", "GOLD", "MIDDLE", "MAGE", "12.4", "EARLY")
    assert baseline is not None
    assert (await metrics.get_champion_profile(103, "12.4")) is not None
    assert (await players.get_champion_profile(player_id, 103, "MIDDLE")) is not None


def _finding(finding_id: str, review_id: str, *, t_ms: int) -> FindingRecord:
    return FindingRecord(
        id=finding_id,
        review_id=review_id,
        rule_id="R-000",
        rule_version=1,
        concept_id="LANING",
        t_ms=t_ms,
        t_end_ms=None,
        severity="LOW",
        confidence=0.9,
        gold_equivalent=None,
        outcome="NONE",
        map_x=None,
        map_y=None,
        title="stub",
        explanation="stub",
        alternative=None,
        explanation_source="TEMPLATE",
        suppressed=0,
        suppressed_by=None,
    )


def _evidence(finding_id: str, label: str) -> EvidenceRecord:
    return EvidenceRecord(
        finding_id=finding_id,
        kind="FACT",
        label=label,
        value_json='{"v":1}',
        t_ms=1000,
        source="RIOT_TIMELINE",
        confidence=1.0,
        provenance_json=None,
    )
