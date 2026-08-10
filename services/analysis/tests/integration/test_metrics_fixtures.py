from __future__ import annotations

from pathlib import Path

from riftlens.analysis.metrics.registry import compute_metrics, persist_metrics
from riftlens.domain.enums import GamePhase
from riftlens.pipeline.ingest_riot.fact_builder import games_are_paired
from tests.helpers.gst import bundled_patch, load_fixture_pair, load_gst

# Hand-verified from NA1_fixture_a timeline participantFrames (GST / timeline),
# NOT from match.json post-game stats.
#
# BLOCKING LIMITATION: match.info.gameId=4223689858 duration=1257s (Bard support
# pid 5, 12 CS, KDA 1/3/17) while timeline GAME_END.gameId=3988447001 lasts
# 2022037 ms (~33.7 min). H.3 GST prefers timeline identity (pid 5 → Pyke).
# Fixtures B and C are byte-identical to A after match-id rewrite.
# Asserting M-01/M-02 against match.json KDA/CS would compare two different games.
_M01_EARLY = 22 / (780204 / 60_000)
_M01_MID = 11 / ((1_440_392 - 840_229) / 60_000)
_M01_LATE = 10 / ((2_022_037 - 1_500_404) / 60_000)
_M02 = {"5": 6.0, "10": 10.0, "14": 19.0}


def test_m01_m02_hand_verified_against_gst_timeline() -> None:
    gst = load_gst("NA1_fixture_a")
    match, timeline = load_fixture_pair("NA1_fixture_a")
    assert games_are_paired(match, timeline) is False
    values = compute_metrics(gst, 5, bundled_patch(gst.patch))
    m01 = {row.phase: row for row in values if row.metric_id == "M-01"}
    assert isinstance(m01[GamePhase.EARLY].phase, GamePhase)
    assert m01[GamePhase.EARLY].value == _M01_EARLY
    assert m01[GamePhase.MID].value == _M01_MID
    assert m01[GamePhase.LATE].value == _M01_LATE
    m02 = {str(row.phase): row.value for row in values if row.metric_id == "M-02"}
    assert m02 == _M02


def test_all_h5_metrics_emit_for_fixture_a() -> None:
    gst = load_gst("NA1_fixture_a")
    values = compute_metrics(gst, 5, bundled_patch(gst.patch))
    ids = {row.metric_id for row in values}
    assert ids == {"M-01", "M-02", "M-03", "M-04", "M-05", "M-07", "M-15", "M-19", "M-20", "M-22"}
    assert all(0.0 <= row.confidence <= 1.0 for row in values)


def test_cli_metrics_prints_readable_table() -> None:
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "riftlens.cli", "metrics", "NA1_fixture_a", "--pid", "5"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "M-01" in result.stdout
    assert "M-02" in result.stdout
    assert "unpaired" in result.stdout.lower()
    assert "cs_per_min" in result.stdout


def test_fixtures_b_and_c_are_id_renames_of_a() -> None:
    root = Path(__file__).resolve().parents[1] / "fixtures" / "riot"

    def rewrite(name: str, text: str) -> str:
        return text.replace(name, "NA1_fixture_X")

    for kind in ("match.json", "timeline.json"):
        a = rewrite("NA1_fixture_a", (root / "NA1_fixture_a" / kind).read_text(encoding="utf-8"))
        b = rewrite("NA1_fixture_b", (root / "NA1_fixture_b" / kind).read_text(encoding="utf-8"))
        c = rewrite("NA1_fixture_c", (root / "NA1_fixture_c" / kind).read_text(encoding="utf-8"))
        assert a == b == c


def test_persist_metrics_uses_h4_repository(tmp_path: Path) -> None:
    import asyncio

    from riftlens.adapters.db.engine import init_database, make_session_factory
    from riftlens.adapters.db.repositories import (
        SqlMatchRepository,
        SqlMetricRepository,
        SqlPlayerRepository,
        SqlReviewRepository,
    )
    from riftlens.config import Settings
    from riftlens.domain.ids import new_ulid
    from riftlens.domain.ports import PlayerRecord, ReviewRecord
    from riftlens.pipeline.ingest_riot.persist import persist_riot_match

    async def run() -> None:
        settings = Settings(data_dir=tmp_path)
        engine = init_database(settings)
        factory = make_session_factory(engine)
        players = SqlPlayerRepository(factory)
        matches = SqlMatchRepository(factory)
        reviews = SqlReviewRepository(factory)
        metrics_repo = SqlMetricRepository(factory)
        player_id = new_ulid()
        review_id = new_ulid()
        await players.upsert_player(
            PlayerRecord(id=player_id, display_name="local", is_local_user=1, created_at=1)
        )
        match, timeline = load_fixture_pair()
        await persist_riot_match(matches, match, timeline, now_ms=2)
        await reviews.upsert(
            ReviewRecord(
                id=review_id,
                player_id=player_id,
                match_id=match.metadata.match_id,
                participant_id=5,
                media_asset_id=None,
                sync_map_id=None,
                rule_pack_version="h5",
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
        gst = load_gst()
        values = compute_metrics(gst, 5, bundled_patch(gst.patch))
        await persist_metrics(metrics_repo, review_id, values)
        stored = await metrics_repo.list_for_review(review_id)
        assert {row.metric_id for row in stored} == {
            "M-01",
            "M-02",
            "M-03",
            "M-04",
            "M-05",
            "M-07",
            "M-15",
            "M-19",
            "M-20",
            "M-22",
        }
        engine.dispose()

    asyncio.run(run())
