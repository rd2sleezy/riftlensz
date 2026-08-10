from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from riftlens.adapters.db.engine import init_database, make_session_factory
from riftlens.adapters.db.repositories import (
    SqlGameplayRepository,
    SqlMatchRepository,
    SqlMediaRepository,
    SqlSyncRepository,
)
from riftlens.config import Settings
from riftlens.domain.clock_map import ClockConfidence, ClockMap, ClockMode
from riftlens.domain.clock_store import (
    CALIBRATION_METHOD_EVENT_ANCHOR_V1,
    CLOCK_KIND_CALIBRATED_REPLAY,
    CLOCK_KIND_LINEAR_OFFSET,
    SOURCE_STATUS_LINKED,
    SOURCE_STATUS_UNAVAILABLE,
    SOURCE_TYPE_ROFL,
    SOURCE_TYPE_VIDEO,
    STORE_CONFIDENCE_CALIBRATED,
    STORE_CONFIDENCE_ESTIMATED,
)
from riftlens.domain.ids import new_ulid
from riftlens.domain.ports import (
    GameplaySourceRecord,
    MatchRecord,
    MediaAssetRecord,
    ReplaySessionAuditRecord,
    RoflSourceDetailRecord,
    SyncMapRecord,
)
from riftlens.domain.sync_map import SyncMap, SyncQuality, SyncSegment
from sqlalchemy import Engine, inspect, text

_NA1_R6_MATCH = "NA1_5617764200"


@pytest.fixture
def engine(settings: Settings) -> Iterator[Engine]:
    created = init_database(settings)
    try:
        yield created
    finally:
        created.dispose()


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


def _rofl_source(
    *,
    source_id: str,
    match_id: str,
    path: Path,
    created_at: int = 10,
) -> tuple[GameplaySourceRecord, RoflSourceDetailRecord]:
    uri = str(path)
    source = GameplaySourceRecord(
        id=source_id,
        match_id=match_id,
        source_type=SOURCE_TYPE_ROFL,
        source_uri=uri,
        content_hash=None,
        display_name=path.name,
        duration_ms=1_800_000,
        status=SOURCE_STATUS_LINKED,
        platform_scope="windows",
        created_at=created_at,
        updated_at=created_at,
    )
    detail = RoflSourceDetailRecord(
        gameplay_source_id=source_id,
        platform_id="NA1",
        game_id=5617764200,
        declared_patch="16.9",
        declared_length_ms=1_798_000,
        identify_method="filename",
        header_parse_status="ok",
        file_size_bytes=12_345,
        magic="RIOT",
        raw_metadata_json=None,
    )
    return source, detail


@pytest.mark.asyncio
async def test_save_load_native_replay_source(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_replay_one")
    path = tmp_path / "NA1_5617764200.rofl"
    path.write_bytes(b"RIOT")
    factory = make_session_factory(engine)
    repo = SqlGameplayRepository(factory)
    source_id = new_ulid()
    source, detail = _rofl_source(source_id=source_id, match_id="NA1_replay_one", path=path)
    stored_id = await repo.upsert_source(source, rofl=detail)
    loaded = await repo.get_source(stored_id)
    assert loaded is not None
    assert loaded.source.source_type == SOURCE_TYPE_ROFL
    assert loaded.source.match_id == "NA1_replay_one"
    assert loaded.source.source_uri == str(path)
    assert loaded.source.display_name == "NA1_5617764200.rofl"
    assert loaded.file_present is True
    assert loaded.rofl is not None
    assert loaded.rofl.platform_id == "NA1"
    assert loaded.rofl.game_id == 5617764200
    assert loaded.rofl.declared_patch == "16.9"
    assert loaded.rofl.identify_method == "filename"
    assert loaded.rofl.header_parse_status == "ok"
    assert loaded.rofl.file_size_bytes == 12_345
    assert loaded.rofl.magic == "RIOT"
    assert loaded.clock is None


@pytest.mark.asyncio
async def test_save_load_video_source(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_video_one")
    vod = tmp_path / "vod.mp4"
    vod.write_bytes(b"ftyp")
    factory = make_session_factory(engine)
    media = SqlMediaRepository(factory)
    gameplay = SqlGameplayRepository(factory)
    asset_id = new_ulid()
    await media.upsert_asset(
        MediaAssetRecord(
            id=asset_id,
            content_hash="a" * 64,
            original_path=str(vod),
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
            size_bytes=4,
            source_kind="PLAYER_POV",
            layout_profile_id=None,
            quality_score=None,
            imported_at=14,
            last_accessed_at=14,
        )
    )
    source_id = new_ulid()
    await gameplay.upsert_source(
        GameplaySourceRecord(
            id=source_id,
            match_id="NA1_video_one",
            source_type=SOURCE_TYPE_VIDEO,
            source_uri=str(vod),
            content_hash="a" * 64,
            display_name="vod.mp4",
            duration_ms=1_200_000,
            status=SOURCE_STATUS_LINKED,
            platform_scope="any",
            created_at=15,
            updated_at=15,
            media_asset_id=asset_id,
        )
    )
    sync = SyncMap(
        segments=(SyncSegment(0, 1_200_000, -8_000, 4, 50.0),),
        pauses=(),
        quality=SyncQuality(
            method="manual",
            n_readings=4,
            n_inliers=4,
            inlier_ratio=1.0,
            residual_p50_ms=12.0,
            residual_p95_ms=50.0,
            coverage=1.0,
            n_segments=1,
            verdict="GOOD",
        ),
        media_asset_id=asset_id,
        match_id="NA1_video_one",
        version=1,
        verified=True,
    )
    clock = ClockMap.from_sync_map(sync)
    stored = await gameplay.replace_clock(source_id, clock, method="manual", created_at=16)
    loaded = await gameplay.get_source(source_id)
    assert loaded is not None
    assert loaded.source.source_type == SOURCE_TYPE_VIDEO
    assert loaded.source.media_asset_id == asset_id
    assert loaded.clock is not None
    assert loaded.clock.clock == clock
    assert loaded.clock.clock.mode is ClockMode.SYNC_MAP
    assert stored.kind == CLOCK_KIND_LINEAR_OFFSET


@pytest.mark.asyncio
async def test_verified_clockmap_round_trip(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_clock_verified")
    path = tmp_path / "NA1_clock_verified.rofl"
    path.write_bytes(b"RIOT")
    repo = SqlGameplayRepository(make_session_factory(engine))
    source_id = new_ulid()
    source, detail = _rofl_source(source_id=source_id, match_id="NA1_clock_verified", path=path)
    await repo.upsert_source(source, rofl=detail)
    clock = ClockMap.offset(
        offset_ms=-670,
        source_start_ms=0,
        source_end_ms=1_800_000,
        confidence=ClockConfidence.GOOD,
        verified=True,
    )
    await repo.replace_clock(
        source_id,
        clock,
        method=CALIBRATION_METHOD_EVENT_ANCHOR_V1,
        created_at=20,
        anchor_count=8,
        residual_ms=623,
        stdev_ms=306.08,
    )
    loaded = await repo.get_active_clock(source_id)
    assert loaded is not None
    assert loaded.clock == clock
    assert loaded.clock.verified is True
    assert loaded.clock.confidence is ClockConfidence.GOOD
    assert loaded.kind == CLOCK_KIND_CALIBRATED_REPLAY
    assert loaded.confidence == STORE_CONFIDENCE_CALIBRATED
    assert loaded.method == CALIBRATION_METHOD_EVENT_ANCHOR_V1
    assert loaded.anchor_count == 8
    assert loaded.residual_ms == 623
    assert loaded.stdev_ms == pytest.approx(306.08)
    assert loaded.clock.game_to_source(600_000) == clock.game_to_source(600_000)
    assert loaded.clock.source_to_game(100_000) == clock.source_to_game(100_000)


@pytest.mark.asyncio
async def test_estimated_clockmap_does_not_upgrade_on_reload(
    engine: Engine, tmp_path: Path
) -> None:
    await _seed_match(engine, "NA1_clock_est")
    path = tmp_path / "NA1_clock_est.rofl"
    path.write_bytes(b"RIOT")
    repo = SqlGameplayRepository(make_session_factory(engine))
    source_id = new_ulid()
    source, detail = _rofl_source(source_id=source_id, match_id="NA1_clock_est", path=path)
    await repo.upsert_source(source, rofl=detail)
    clock = ClockMap.offset(
        offset_ms=-1_200,
        source_start_ms=0,
        source_end_ms=1_800_000,
        confidence=ClockConfidence.DEGRADED,
        verified=False,
    )
    await repo.replace_clock(
        source_id,
        clock,
        method="duration_heuristic",
        created_at=21,
        warning="duration mismatch",
    )
    loaded = await repo.get_active_clock(source_id)
    assert loaded is not None
    assert loaded.clock == clock
    assert loaded.clock.verified is False
    assert loaded.clock.confidence is ClockConfidence.DEGRADED
    assert loaded.kind == CLOCK_KIND_LINEAR_OFFSET
    assert loaded.confidence == STORE_CONFIDENCE_ESTIMATED
    assert loaded.warning == "duration mismatch"


@pytest.mark.asyncio
async def test_replace_clock_appends_without_duplicate_active(
    engine: Engine, tmp_path: Path
) -> None:
    await _seed_match(engine, "NA1_clock_replace")
    path = tmp_path / "NA1_clock_replace.rofl"
    path.write_bytes(b"RIOT")
    repo = SqlGameplayRepository(make_session_factory(engine))
    source_id = new_ulid()
    source, detail = _rofl_source(source_id=source_id, match_id="NA1_clock_replace", path=path)
    await repo.upsert_source(source, rofl=detail)
    first = ClockMap.offset(
        offset_ms=-1_200,
        source_start_ms=0,
        source_end_ms=1_800_000,
        confidence=ClockConfidence.DEGRADED,
        verified=False,
    )
    second = ClockMap.offset(
        offset_ms=-670,
        source_start_ms=0,
        source_end_ms=1_800_000,
        confidence=ClockConfidence.GOOD,
        verified=True,
    )
    await repo.replace_clock(source_id, first, method="duration_heuristic", created_at=30)
    await repo.replace_clock(
        source_id,
        second,
        method=CALIBRATION_METHOD_EVENT_ANCHOR_V1,
        created_at=31,
        anchor_count=8,
        residual_ms=623,
    )
    active = await repo.get_active_clock(source_id)
    assert active is not None
    assert active.clock == second
    with engine.connect() as connection:
        total = connection.execute(
            text("SELECT COUNT(*) FROM clock_map WHERE gameplay_source_id = :id"),
            {"id": source_id},
        ).scalar_one()
        actives = connection.execute(
            text(
                "SELECT COUNT(*) FROM clock_map WHERE gameplay_source_id = :id AND is_active = 1"
            ),
            {"id": source_id},
        ).scalar_one()
    assert int(total) == 2
    assert int(actives) == 1


@pytest.mark.asyncio
async def test_duplicate_source_save_is_idempotent(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_dup")
    path = tmp_path / "NA1_dup.rofl"
    path.write_bytes(b"RIOT")
    repo = SqlGameplayRepository(make_session_factory(engine))
    first_id = new_ulid()
    second_id = new_ulid()
    source_a, detail_a = _rofl_source(source_id=first_id, match_id="NA1_dup", path=path)
    source_b, detail_b = _rofl_source(
        source_id=second_id, match_id="NA1_dup", path=path, created_at=99
    )
    stored_a = await repo.upsert_source(source_a, rofl=detail_a)
    stored_b = await repo.upsert_source(source_b, rofl=detail_b)
    assert stored_a == stored_b == first_id
    listed = await repo.list_sources_for_match("NA1_dup")
    assert len(listed) == 1
    assert listed[0].source.updated_at == 99
    with engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM gameplay_source")).scalar_one()
    assert int(count) == 1


@pytest.mark.asyncio
async def test_list_sources_for_match_and_empty_match(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_list")
    await _seed_match(engine, "NA1_other")
    path = tmp_path / "NA1_list.rofl"
    path.write_bytes(b"RIOT")
    repo = SqlGameplayRepository(make_session_factory(engine))
    source_id = new_ulid()
    source, detail = _rofl_source(source_id=source_id, match_id="NA1_list", path=path)
    await repo.upsert_source(source, rofl=detail)
    found = await repo.list_sources_for_match("NA1_list")
    assert len(found) == 1
    assert found[0].source.id == source_id
    assert await repo.list_sources_for_match("NA1_other") == []
    assert await repo.get_source(new_ulid()) is None
    assert await repo.get_active_clock(source_id) is None


@pytest.mark.asyncio
async def test_missing_file_after_persistence(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_missing")
    path = tmp_path / "NA1_missing.rofl"
    path.write_bytes(b"RIOT")
    repo = SqlGameplayRepository(make_session_factory(engine))
    source_id = new_ulid()
    source, detail = _rofl_source(source_id=source_id, match_id="NA1_missing", path=path)
    await repo.upsert_source(source, rofl=detail)
    path.unlink()
    loaded = await repo.get_source(source_id)
    assert loaded is not None
    assert loaded.file_present is False
    assert loaded.source.status == SOURCE_STATUS_LINKED
    refreshed = await repo.revalidate_source(source_id, updated_at=50)
    assert refreshed.file_present is False
    assert refreshed.source.status == SOURCE_STATUS_UNAVAILABLE
    assert loaded.source.source_uri == str(path)


@pytest.mark.asyncio
async def test_replay_session_audit_is_not_live_state(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_session")
    path = tmp_path / "NA1_session.rofl"
    path.write_bytes(b"RIOT")
    repo = SqlGameplayRepository(make_session_factory(engine))
    source_id = new_ulid()
    source, detail = _rofl_source(source_id=source_id, match_id="NA1_session", path=path)
    await repo.upsert_source(source, rofl=detail)
    await repo.record_session(
        ReplaySessionAuditRecord(
            id=new_ulid(),
            gameplay_source_id=source_id,
            replay_api_base="https://127.0.0.1:2999",
            replay_api_port=2999,
            state="closed",
            last_error=None,
            started_at=60,
            ended_at=90,
        )
    )
    sessions = await repo.list_sessions(source_id)
    assert len(sessions) == 1
    assert sessions[0].state == "closed"
    assert sessions[0].ended_at == 90
    assert not hasattr(sessions[0], "pid")
    snapshot = await repo.get_source(source_id)
    assert snapshot is not None
    assert snapshot.source.status != "ready"


@pytest.mark.asyncio
async def test_h9_sync_dual_writes_gameplay_source(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_h9_shim")
    vod = tmp_path / "shim.mp4"
    vod.write_bytes(b"ftyp")
    factory = make_session_factory(engine)
    media = SqlMediaRepository(factory)
    syncs = SqlSyncRepository(factory)
    gameplay = SqlGameplayRepository(factory)
    asset_id = new_ulid()
    await media.upsert_asset(
        MediaAssetRecord(
            id=asset_id,
            content_hash="b" * 64,
            original_path=str(vod),
            playable_path=None,
            proxy_path=None,
            thumbnail_sheet_path=None,
            container="mp4",
            codec=None,
            pix_fmt=None,
            width=None,
            height=None,
            fps_num=None,
            fps_den=None,
            duration_ms=900_000,
            size_bytes=4,
            source_kind="PLAYER_POV",
            layout_profile_id=None,
            quality_score=None,
            imported_at=70,
            last_accessed_at=70,
        )
    )
    sync_id = new_ulid()
    sync_row = SyncMapRecord(
        id=sync_id,
        media_asset_id=asset_id,
        match_id="NA1_h9_shim",
        method="auto",
        segments="[]",
        pauses="[]",
        quality="{}",
        verified=0,
        created_at=71,
    )
    await syncs.upsert(sync_row)
    await syncs.upsert(sync_row)
    fetched = await syncs.get(sync_id)
    assert fetched is not None
    assert fetched.segments == "[]"
    listed = await gameplay.list_sources_for_match("NA1_h9_shim")
    assert len(listed) == 1
    assert listed[0].source.source_type == SOURCE_TYPE_VIDEO
    assert listed[0].source.display_name == "shim.mp4"
    assert listed[0].clock is not None
    assert listed[0].clock.clock.verified is False


@pytest.mark.asyncio
async def test_r6_na1_calibration_round_trip_conversions(engine: Engine, tmp_path: Path) -> None:
    """Persist the observed R.6 NA1_5617764200 calibration without launching League."""
    await _seed_match(engine, _NA1_R6_MATCH)
    path = tmp_path / f"{_NA1_R6_MATCH}.rofl"
    path.write_bytes(b"RIOT")
    repo = SqlGameplayRepository(make_session_factory(engine))
    source_id = new_ulid()
    source, detail = _rofl_source(source_id=source_id, match_id=_NA1_R6_MATCH, path=path)
    await repo.upsert_source(source, rofl=detail)
    observed_offset_ms = -670
    observed_residual_ms = 623
    observed_anchor_count = 8
    clock = ClockMap.offset(
        offset_ms=observed_offset_ms,
        source_start_ms=0,
        source_end_ms=1_800_000,
        confidence=ClockConfidence.GOOD,
        verified=True,
    )
    await repo.replace_clock(
        source_id,
        clock,
        method=CALIBRATION_METHOD_EVENT_ANCHOR_V1,
        created_at=80,
        anchor_count=observed_anchor_count,
        residual_ms=observed_residual_ms,
        stdev_ms=306.08,
        warning=None,
    )
    loaded = await repo.get_source(source_id)
    assert loaded is not None
    assert loaded.source.match_id == _NA1_R6_MATCH
    assert loaded.rofl is not None
    assert loaded.rofl.game_id == 5617764200
    assert loaded.clock is not None
    assert loaded.clock.clock == clock
    assert loaded.clock.method == "event_anchor_v1"
    assert loaded.clock.confidence == STORE_CONFIDENCE_CALIBRATED
    assert loaded.clock.clock.verified is True
    assert loaded.clock.anchor_count == observed_anchor_count
    assert loaded.clock.residual_ms == observed_residual_ms
    for t_game in (0, 180_000, 600_000, 1_200_000):
        assert loaded.clock.clock.game_to_source(t_game) == clock.game_to_source(t_game)
    for t_source in (670, 50_000, 400_000):
        assert loaded.clock.clock.source_to_game(t_source) == clock.source_to_game(t_source)


def test_r7_tables_exist_after_init(engine: Engine) -> None:
    names = set(inspect(engine).get_table_names())
    assert {
        "gameplay_source",
        "rofl_source_detail",
        "clock_map",
        "replay_session",
        "capture_interval",
        "media_artifact",
    } <= names
