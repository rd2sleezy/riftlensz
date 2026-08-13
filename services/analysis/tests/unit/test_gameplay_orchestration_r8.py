from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from riftlens.adapters.db.engine import init_database, make_session_factory
from riftlens.adapters.db.repositories import (
    SqlGameplayRepository,
    SqlMatchRepository,
    SqlMediaRepository,
)
from riftlens.config import Settings
from riftlens.domain.clock_map import ClockConfidence, ClockMap
from riftlens.domain.clock_store import (
    CALIBRATION_METHOD_EVENT_ANCHOR_V1,
    SOURCE_STATUS_LINKED,
    SOURCE_TYPE_VIDEO,
)
from riftlens.domain.gameplay_source import SourceCapability, SourceKind
from riftlens.domain.ids import new_ulid
from riftlens.domain.ports import GameplaySourceRecord, MatchRecord, MediaAssetRecord
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.domain.sync_map import SEEK_LEAD_IN_MS, SyncMap, SyncQuality, SyncSegment
from riftlens.gameplay.factory import GameplaySourceFactory
from riftlens.gameplay.service import GameplaySourceService
from riftlens.replay_host.api.replay_client import ReplayApiClient
from riftlens.replay_host.clock.calibrator import CalibrationResult, GamestatsRelation
from riftlens.replay_host.factory import create_replay_host
from riftlens.replay_host.seek import LANDING_TOLERANCE_MS
from riftlens.replay_host.unsupported import UnsupportedReplayHost
from riftlens.replay_host.windows.install_locator import (
    InstallDiscoveryMethod,
    validate_install_root,
)
from sqlalchemy import Engine
from tests.fakes.fake_replay_host import FakeReplayHost
from tests.fakes.fake_replay_runtime import FakeClock, write_tiny_rofl
from tests.fakes.fake_replay_server import FakeReplayApiServer, FakeReplayBehavior

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "riftlens"


@pytest.fixture
def engine(settings: Settings) -> Iterator[Engine]:
    created = init_database(settings)
    try:
        yield created
    finally:
        created.dispose()


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


def _service(
    engine: Engine,
    host: FakeReplayHost | UnsupportedReplayHost,
) -> GameplaySourceService:
    factory = make_session_factory(engine)
    return GameplaySourceService(
        host=host,
        gameplay=SqlGameplayRepository(factory),
        matches=SqlMatchRepository(factory),
    )


def _verified_result(*, offset_ms: int = -670) -> CalibrationResult:
    clock = ClockMap.offset(
        offset_ms=offset_ms,
        source_start_ms=0,
        source_end_ms=1_800_000,
        confidence=ClockConfidence.GOOD,
        verified=True,
    )
    return CalibrationResult(
        clock=clock,
        method="event_anchor",
        confidence=ClockConfidence.GOOD,
        offset_ms=offset_ms,
        anchor_count=8,
        residual_ms=623.0,
        stdev_ms=306.08,
        duration_delta_ms=-12,
        gamestats_relation=GamestatsRelation.TRACKS_PLAYBACK,
        lcd_available=True,
        error=None,
        match=None,
        reason="event_anchor",
    )


def _degraded_result() -> CalibrationResult:
    clock = ClockMap.offset(
        offset_ms=-1200,
        source_start_ms=0,
        source_end_ms=1_800_000,
        confidence=ClockConfidence.DEGRADED,
        verified=False,
    )
    return CalibrationResult(
        clock=clock,
        method="duration_heuristic",
        confidence=ClockConfidence.DEGRADED,
        offset_ms=-1200,
        anchor_count=0,
        residual_ms=None,
        stdev_ms=None,
        duration_delta_ms=1200,
        gamestats_relation=GamestatsRelation.UNKNOWN,
        lcd_available=False,
        error=ReplayError(ReplayErrorCode.CLOCK_CALIBRATION_FAILED),
        match=None,
        reason="duration_heuristic",
    )


@pytest.mark.asyncio
async def test_import_valid_rofl_persists_source(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_5617764200")
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    service = _service(engine, FakeReplayHost())
    outcome = await service.import_rofl(str(rofl), now_ms=10)
    assert outcome.ok is True
    assert outcome.error is None
    assert outcome.match_id == "NA1_5617764200"
    assert outcome.identity is not None
    assert outcome.identity.platform_id == "NA1"
    assert outcome.identity.game_id == 5617764200
    assert outcome.snapshot is not None
    assert outcome.snapshot.source.source_type == "rofl"
    assert outcome.snapshot.rofl is not None
    assert outcome.snapshot.rofl.game_id == 5617764200
    assert outcome.snapshot.source.status == SOURCE_STATUS_LINKED
    loaded = await service.resolve_source(outcome.source_id or "")
    assert loaded is not None
    assert loaded.source.kind is SourceKind.NATIVE_REPLAY


@pytest.mark.asyncio
async def test_invalid_rofl_typed_failure(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_5617764200")
    path = tmp_path / "NA1-5617764200.rofl"
    path.write_bytes(b"not a replay")
    outcome = await _service(engine, FakeReplayHost()).import_rofl(str(path), now_ms=11)
    assert outcome.ok is False
    assert outcome.error is not None
    assert outcome.error.code is ReplayErrorCode.ROFL_NOT_RECOGNISED


@pytest.mark.asyncio
async def test_missing_match_is_recoverable(engine: Engine, tmp_path: Path) -> None:
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    outcome = await _service(engine, FakeReplayHost()).import_rofl(str(rofl), now_ms=12)
    assert outcome.ok is False
    assert outcome.error is not None
    assert outcome.error.code is ReplayErrorCode.MATCH_NOT_INGESTED
    assert outcome.error.is_retryable()
    assert outcome.match_id == "NA1_5617764200"
    assert outcome.error.details.get("suggested_action") == "ingest_match"


@pytest.mark.asyncio
async def test_unresolved_identity(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_other")
    rofl = write_tiny_rofl(tmp_path / "replay.rofl")
    outcome = await _service(engine, FakeReplayHost()).import_rofl(str(rofl), now_ms=13)
    assert outcome.ok is False
    assert outcome.error is not None
    assert outcome.error.code is ReplayErrorCode.MATCH_ID_UNRESOLVED


@pytest.mark.asyncio
async def test_reload_after_simulated_restart(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_5617764200")
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    host = FakeReplayHost(calibrate_result=_verified_result())
    first = _service(engine, host)
    imported = await first.import_rofl(str(rofl), now_ms=20)
    assert imported.ok
    reveal = await first.reveal(imported.source_id or "", 600_000, lead_in_ms=8_000, now_ms=21)
    assert reveal.ok
    await first.close_session(imported.source_id or "", now_ms=22)
    host.reset_live_session()
    second = _service(engine, host)
    resolved = await second.resolve_source(imported.source_id or "")
    assert resolved is not None
    assert resolved.source.clock.verified is True
    assert host.get_state().phase.value == "IDLE"
    again = await second.reveal(imported.source_id or "", 180_000, lead_in_ms=8_000, now_ms=23)
    assert again.ok
    assert host.open_count == 2


@pytest.mark.asyncio
async def test_verified_clock_is_reused(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_5617764200")
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    host = FakeReplayHost(calibrate_result=_verified_result())
    service = _service(engine, host)
    imported = await service.import_rofl(str(rofl), now_ms=30)
    first = await service.reveal(imported.source_id or "", 120_000, now_ms=31)
    second = await service.reveal(imported.source_id or "", 240_000, now_ms=32)
    assert first.ok and second.ok
    assert host.calibrate_count == 1
    stored = await SqlGameplayRepository(make_session_factory(engine)).get_active_clock(
        imported.source_id or ""
    )
    assert stored is not None
    assert stored.clock.verified is True
    assert stored.method == CALIBRATION_METHOD_EVENT_ANCHOR_V1
    assert stored.anchor_count == 8
    assert stored.residual_ms == 623


@pytest.mark.asyncio
async def test_degraded_clock_does_not_become_verified(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_5617764200")
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    host = FakeReplayHost(calibrate_result=_degraded_result())
    service = _service(engine, host)
    imported = await service.import_rofl(str(rofl), now_ms=40)
    outcome = await service.reveal(imported.source_id or "", 90_000, now_ms=41)
    assert outcome.ok
    assert outcome.clock is not None
    assert outcome.clock.verified is False
    assert outcome.clock.confidence is ClockConfidence.DEGRADED
    stored = await SqlGameplayRepository(make_session_factory(engine)).get_active_clock(
        imported.source_id or ""
    )
    assert stored is not None
    assert stored.clock.verified is False


@pytest.mark.asyncio
async def test_absent_clock_triggers_calibration(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_5617764200")
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    host = FakeReplayHost(calibrate_result=_verified_result())
    service = _service(engine, host)
    imported = await service.import_rofl(str(rofl), now_ms=50)
    assert imported.snapshot is not None
    assert imported.snapshot.clock is None
    await service.reveal(imported.source_id or "", 60_000, now_ms=51)
    assert host.calibrate_count == 1


@pytest.mark.asyncio
async def test_reveal_uses_clockmap_and_lead_in(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_5617764200")
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    host = FakeReplayHost(calibrate_result=_verified_result(offset_ms=-670))
    service = _service(engine, host)
    imported = await service.import_rofl(str(rofl), now_ms=60)
    outcome = await service.reveal(
        imported.source_id or "", 1_122_000, lead_in_ms=SEEK_LEAD_IN_MS, now_ms=61
    )
    assert outcome.ok
    assert outcome.lead_in_ms == 8_000
    assert outcome.target_game_ms == 1_114_000
    assert outcome.target_source_ms == 1_114_670
    assert outcome.landed_source_ms == 1_114_670
    assert host.reveal_count == 1


@pytest.mark.asyncio
async def test_reveal_fails_when_not_ready(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_5617764200")
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    host = FakeReplayHost(
        calibrate_result=_verified_result(),
        open_error=ReplayError(ReplayErrorCode.LAUNCH_TIMEOUT),
    )
    service = _service(engine, host)
    imported = await service.import_rofl(str(rofl), now_ms=70)
    outcome = await service.reveal(imported.source_id or "", 30_000, now_ms=71)
    assert outcome.ok is False
    assert outcome.error is not None
    assert outcome.error.code is ReplayErrorCode.LAUNCH_TIMEOUT
    assert host.reveal_count == 0


@pytest.mark.asyncio
async def test_session_loss_is_surfaced(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_5617764200")
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    host = FakeReplayHost(calibrate_result=_verified_result())
    service = _service(engine, host)
    imported = await service.import_rofl(str(rofl), now_ms=80)
    first = await service.reveal(imported.source_id or "", 40_000, now_ms=81)
    assert first.ok
    host.session_lost = True
    lost = await service.reveal(imported.source_id or "", 50_000, now_ms=82)
    assert lost.ok is False
    assert lost.error is not None
    assert lost.error.code is ReplayErrorCode.SESSION_LOST


@pytest.mark.asyncio
async def test_missing_file_after_persist(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_5617764200")
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    service = _service(engine, FakeReplayHost(calibrate_result=_verified_result()))
    imported = await service.import_rofl(str(rofl), now_ms=90)
    rofl.unlink()
    outcome = await service.reveal(imported.source_id or "", 20_000, now_ms=91)
    assert outcome.ok is False
    assert outcome.error is not None
    assert outcome.error.code is ReplayErrorCode.ROFL_MISSING


@pytest.mark.asyncio
async def test_linux_native_replay_platform_unsupported(
    engine: Engine, tmp_path: Path
) -> None:
    await _seed_match(engine, "NA1_5617764200")
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    host = create_replay_host(platform="linux")
    assert isinstance(host, UnsupportedReplayHost)
    service = _service(engine, host)
    imported = await service.import_rofl(str(rofl), now_ms=100)
    assert imported.ok
    resolved = await service.resolve_source(imported.source_id or "")
    assert resolved is not None
    assert resolved.available is False
    assert resolved.reason is not None
    assert resolved.reason.code is ReplayErrorCode.PLATFORM_UNSUPPORTED
    assert SourceCapability.SEEK not in resolved.source.capabilities
    outcome = await service.reveal(imported.source_id or "", 15_000, now_ms=101)
    assert outcome.ok is False
    assert outcome.error is not None
    assert outcome.error.code is ReplayErrorCode.PLATFORM_UNSUPPORTED


@pytest.mark.asyncio
async def test_darwin_factory_exposes_native_capabilities(
    engine: Engine, tmp_path: Path
) -> None:
    from riftlens.replay_host.mac.host import MacReplayHost

    await _seed_match(engine, "NA1_5617764200")
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    host = create_replay_host(platform="darwin")
    assert isinstance(host, MacReplayHost)
    service = _service(engine, host)
    imported = await service.import_rofl(str(rofl), now_ms=100)
    assert imported.ok
    resolved = await service.resolve_source(imported.source_id or "")
    assert resolved is not None
    assert SourceCapability.SEEK in resolved.source.capabilities


@pytest.mark.asyncio
async def test_video_h9_reveal_unchanged(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_video")
    vod = tmp_path / "vod.mp4"
    vod.write_bytes(b"ftyp")
    factory = make_session_factory(engine)
    media = SqlMediaRepository(factory)
    gameplay = SqlGameplayRepository(factory)
    asset_id = new_ulid()
    await media.upsert_asset(
        MediaAssetRecord(
            id=asset_id,
            content_hash="c" * 64,
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
            duration_ms=1_200_000,
            size_bytes=4,
            source_kind="PLAYER_POV",
            layout_profile_id=None,
            quality_score=None,
            imported_at=1,
            last_accessed_at=1,
        )
    )
    source_id = new_ulid()
    await gameplay.upsert_source(
        GameplaySourceRecord(
            id=source_id,
            match_id="NA1_video",
            source_type=SOURCE_TYPE_VIDEO,
            source_uri=str(vod),
            content_hash="c" * 64,
            display_name="vod.mp4",
            duration_ms=1_200_000,
            status=SOURCE_STATUS_LINKED,
            platform_scope="any",
            created_at=2,
            updated_at=2,
            media_asset_id=asset_id,
        )
    )
    sync = SyncMap(
        segments=(SyncSegment(0, 1_200_000, -8_000, 3, 40.0),),
        pauses=(),
        quality=SyncQuality(
            method="manual",
            n_readings=3,
            n_inliers=3,
            inlier_ratio=1.0,
            residual_p50_ms=10.0,
            residual_p95_ms=40.0,
            coverage=1.0,
            n_segments=1,
            verdict="GOOD",
        ),
        media_asset_id=asset_id,
        match_id="NA1_video",
        version=1,
        verified=True,
    )
    await gameplay.replace_clock(
        source_id, ClockMap.from_sync_map(sync), method="manual", created_at=3
    )
    host = FakeReplayHost()
    service = GameplaySourceService(
        host=host,
        gameplay=gameplay,
        matches=SqlMatchRepository(factory),
        factory=GameplaySourceFactory(host),
    )
    outcome = await service.reveal(source_id, 60_000, lead_in_ms=8_000)
    assert outcome.ok
    assert outcome.kind is SourceKind.VIDEO
    assert outcome.video_seek is not None
    assert outcome.video_seek.covered is True
    assert outcome.video_seek.t_video_ms == 68_000
    assert outcome.target_source_ms == 60_000
    assert host.open_count == 0
    assert host.reveal_count == 0


@pytest.mark.asyncio
async def test_fake_server_end_to_end_reveal(engine: Engine, tmp_path: Path) -> None:
    await _seed_match(engine, "NA1_5617764200")
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    behavior = FakeReplayBehavior(time_frozen=False)
    with FakeReplayApiServer(behavior) as server:
        client = ReplayApiClient(
            server.origin,
            ca_file=str(server.ca_file),
            timeout_s=2.0,
            connect_timeout_s=1.0,
            max_retries=0,
        )
        host = FakeReplayHost(
            calibrate_result=_verified_result(offset_ms=0),
            seek_transport=client,
            sleep_clock=FakeClock(),
        )
        service = _service(engine, host)
        imported = await service.import_rofl(str(rofl), now_ms=110)
        outcome = await service.reveal(
            imported.source_id or "", 60_000, lead_in_ms=0, now_ms=111
        )
    assert outcome.ok
    assert outcome.target_source_ms == 60_000
    assert outcome.landed_source_ms is not None
    assert abs(outcome.landed_source_ms - 60_000) <= LANDING_TOLERANCE_MS
    assert outcome.native_seek is not None
    assert outcome.native_seek.resumed is True


def test_create_replay_host_non_windows() -> None:
    host = create_replay_host(platform="linux")
    check = host.check_environment()
    assert check.supported is False
    assert check.error is not None
    assert check.error.code is ReplayErrorCode.PLATFORM_UNSUPPORTED
    capture = host.capture_interval(
        0,
        1,
        ClockMap.identity(duration_ms=1_800_000),
        output_dir=".",
        capture_id="cap_unsupported",
    )
    assert capture.ok is False
    assert capture.error is not None


def test_windows_imports_stay_inside_windows_package() -> None:
    pattern = re.compile(
        r"^\s*(import winreg|from winreg import|from ctypes import windll|import win32api)\b",
        re.MULTILINE,
    )
    offenders: list[str] = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if not pattern.search(text):
            continue
        rel = path.relative_to(PACKAGE_ROOT).as_posix()
        if rel.startswith("replay_host/windows/"):
            continue
        offenders.append(rel)
    assert offenders == []


def test_tmp_install_helper_still_validates(tmp_path: Path) -> None:
    root = tmp_path / "League of Legends"
    (root / "Config").mkdir(parents=True)
    (root / "Game").mkdir()
    (root / "Game" / "League of Legends.exe").write_bytes(b"mz")
    install = validate_install_root(root, discovery_method=InstallDiscoveryMethod.CONFIGURED)
    assert install.game_exe.is_file()
