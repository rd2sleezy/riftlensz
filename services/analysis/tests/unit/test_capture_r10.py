from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from riftlens.adapters.db.engine import init_database, make_session_factory
from riftlens.adapters.db.repositories import (
    SqlCaptureRepository,
    SqlGameplayRepository,
    SqlMatchRepository,
)
from riftlens.config import Settings, default_captures_dir
from riftlens.domain.capture import (
    CAPTURE_MANIFEST_NAME,
    DEFAULT_CAPTURE_BUDGET,
    TERMINAL_STATUSES,
    CaptureBudget,
    CaptureMode,
    CaptureRequest,
    CaptureStatus,
    RetentionClass,
    check_budget,
    frame_game_times,
    resolve_mode_settings,
    validate_interval,
)
from riftlens.domain.clock_map import ClockMap
from riftlens.domain.ids import new_ulid
from riftlens.domain.ports import CaptureIntervalRecord, MatchRecord
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.gameplay.service import GameplaySourceService
from riftlens.main import create_app
from riftlens.replay_host.api.replay_client import ReplayApiClient
from riftlens.replay_host.capture import artifact_store
from riftlens.replay_host.capture.capture_service import CaptureService
from riftlens.replay_host.capture.recording import RecordingOrchestrator, run_capture
from riftlens.replay_host.capture.retention import RetentionPolicy, RetentionService
from sqlalchemy import Engine
from tests.fakes.fake_replay_host import FakeReplayHost
from tests.fakes.fake_replay_runtime import FakeClock, write_tiny_rofl
from tests.fakes.fake_replay_server import FakeReplayApiServer, FakeReplayBehavior

_MATCH = "NA1_5617764200"
_AUTH = {"Authorization": "Bearer test-token"}
_START_MS = 1_110_000
_END_MS = 1_135_000


@pytest.fixture
def capture_settings(tmp_path: Path) -> Settings:
    """Settings whose capture root is a temp dir so tests never touch LOCALAPPDATA."""
    return Settings(data_dir=tmp_path / "data", capture_root=tmp_path / "captures")


@pytest.fixture
def engine(capture_settings: Settings) -> Iterator[Engine]:
    created = init_database(capture_settings)
    try:
        yield created
    finally:
        created.dispose()


def _clock() -> ClockMap:
    return ClockMap.identity(duration_ms=1_800_000)


def _client(server: FakeReplayApiServer) -> ReplayApiClient:
    return ReplayApiClient(
        server.origin,
        ca_file=str(server.ca_file),
        timeout_s=2.0,
        connect_timeout_s=1.0,
        max_retries=0,
    )


async def _seed_match(engine: Engine, match_id: str = _MATCH) -> None:
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


async def _import_source(engine: Engine, host: FakeReplayHost, tmp_path: Path) -> str:
    """Persist a native source with an active identity clock and return its id."""
    factory = make_session_factory(engine)
    service = GameplaySourceService(
        host=host,
        gameplay=SqlGameplayRepository(factory),
        matches=SqlMatchRepository(factory),
    )
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    imported = await service.import_rofl(str(rofl), now_ms=10, match_id=_MATCH)
    assert imported.source_id is not None
    await SqlGameplayRepository(factory).replace_clock(
        imported.source_id, _clock(), method="manual", created_at=11
    )
    return imported.source_id


def _capture_service(
    engine: Engine,
    host: FakeReplayHost,
    settings: Settings,
    *,
    budget: CaptureBudget = DEFAULT_CAPTURE_BUDGET,
    policy: RetentionPolicy | None = None,
) -> CaptureService:
    factory = make_session_factory(engine)
    return CaptureService(
        host=host,
        captures=SqlCaptureRepository(factory),
        gameplay=SqlGameplayRepository(factory),
        captures_dir=settings.captures_dir,
        budget=budget,
        retention_policy=policy,
        poll_s=0.0,
    )


# --- pure domain -----------------------------------------------------------------


def test_validate_interval_rejects_reversed_and_negative() -> None:
    validate_interval(_START_MS, _END_MS)
    for start, end in ((_END_MS, _START_MS), (5_000, 5_000), (-1, 10)):
        with pytest.raises(ReplayError) as exc_info:
            validate_interval(start, end)
        assert exc_info.value.code is ReplayErrorCode.CAPTURE_INVALID_INTERVAL


def test_check_budget_refuses_each_dimension() -> None:
    budget = CaptureBudget(max_seconds=30.0, max_artifacts=10, max_bytes=1_000)
    check_budget(budget, duration_ms=25_000, artifact_count=5, byte_count=500)
    for kwargs in (
        {"duration_ms": 40_000, "artifact_count": 1, "byte_count": 1},
        {"duration_ms": 1_000, "artifact_count": 11, "byte_count": 1},
        {"duration_ms": 1_000, "artifact_count": 1, "byte_count": 2_000},
    ):
        with pytest.raises(ReplayError) as exc_info:
            check_budget(budget, **kwargs)  # type: ignore[arg-type]
        assert exc_info.value.code is ReplayErrorCode.CAPTURE_BUDGET_EXCEEDED


def test_check_budget_counts_existing_review_usage() -> None:
    budget = CaptureBudget(max_seconds=30.0, max_artifacts=10, max_bytes=1_000)
    with pytest.raises(ReplayError):
        check_budget(
            budget,
            duration_ms=20_000,
            artifact_count=1,
            byte_count=1,
            existing_seconds=15.0,
        )


def test_resolve_mode_settings_per_mode() -> None:
    clip = resolve_mode_settings(CaptureMode.CLIP, 30.0, _START_MS, _END_MS)
    assert (clip.codec, clip.kind, clip.expected_artifacts) == ("webm", "clip", 1)
    sampled = resolve_mode_settings(CaptureMode.SAMPLED, 2.0, _START_MS, _START_MS + 10_000)
    assert sampled.codec == "png"
    assert sampled.kind == "image"
    assert sampled.expected_artifacts == 21
    still = resolve_mode_settings(CaptureMode.STILL, 2.0, _START_MS, _START_MS + 10_000)
    assert still.codec == "png"
    assert 1 <= still.expected_artifacts <= 3


def test_frame_game_times_spread_across_interval() -> None:
    assert frame_game_times(start_game_ms=1_000, end_game_ms=5_000, count=1) == (1_000,)
    assert frame_game_times(start_game_ms=0, end_game_ms=4_000, count=5) == (
        0,
        1_000,
        2_000,
        3_000,
        4_000,
    )


def test_default_captures_dir_is_machine_local() -> None:
    root = default_captures_dir()
    assert root.name == "captures"
    assert root.parent.name in {"RiftLens", ".riftlens"}
    assert root != Settings(data_dir=Path("data")).data_dir


# --- recording orchestration (T1 against the HTTPS fake) -------------------------


def test_orchestrator_polls_until_recording_stops(tmp_path: Path) -> None:
    behavior = FakeReplayBehavior(recording_poll_steps=3)
    with FakeReplayApiServer(behavior) as server:
        orchestrator = RecordingOrchestrator(_client(server), clock=FakeClock())
        target = tmp_path / "clip.webm"
        orchestrator.start(
            target, start_s=100.0, end_s=110.0, codec="webm", fps=30.0, lossless=False
        )
        samples: list[float] = []
        final = orchestrator.wait_until_complete(
            timeout_s=30.0, poll_s=0.1, on_progress=lambda item: samples.append(item.fraction)
        )
    assert final.recording is False
    assert samples == sorted(samples)
    assert samples[-1] == pytest.approx(1.0)
    assert target.is_file()
    posted = [body for path, body in behavior.post_log if path == "/replay/recording"]
    assert posted[0]["recording"] is True
    assert posted[0]["codec"] == "webm"
    assert posted[0]["startTime"] == 100.0
    assert posted[0]["endTime"] == 110.0
    assert posted[0]["enforceFrameRate"] is True


def test_run_capture_clip_writes_one_hashed_artifact(tmp_path: Path) -> None:
    behavior = FakeReplayBehavior(recording_instant=True)
    with FakeReplayApiServer(behavior) as server:
        result = run_capture(
            client=_client(server),
            clock=_clock(),
            capture_id="cap_clip",
            start_game_ms=_START_MS,
            end_game_ms=_END_MS,
            directory=tmp_path,
            mode=CaptureMode.CLIP,
            sleep_clock=FakeClock(),
        )
    assert result.ok is True
    assert result.status is CaptureStatus.COMPLETE
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.kind == "clip"
    assert artifact.game_t_ms == _START_MS
    assert artifact.source_t_ms == _START_MS
    assert artifact.bytes > 0
    assert len(artifact.sha256) == 64
    assert (tmp_path / artifact.relative_path).is_file()


def test_run_capture_sampled_names_frames_with_game_time(tmp_path: Path) -> None:
    behavior = FakeReplayBehavior(recording_instant=True)
    with FakeReplayApiServer(behavior) as server:
        result = run_capture(
            client=_client(server),
            clock=_clock(),
            capture_id="cap_sampled",
            start_game_ms=_START_MS,
            end_game_ms=_START_MS + 4_000,
            directory=tmp_path,
            mode=CaptureMode.SAMPLED,
            fps=1.0,
            max_artifacts=10,
            sleep_clock=FakeClock(),
        )
    assert result.ok is True
    assert len(result.artifacts) == 5
    names = [item.relative_path for item in result.artifacts]
    assert names[0] == f"frame_000000_g{_START_MS}.png"
    assert names[-1] == f"frame_000004_g{_START_MS + 4_000}.png"
    assert [item.game_t_ms for item in result.artifacts] == [
        _START_MS + step for step in (0, 1_000, 2_000, 3_000, 4_000)
    ]
    assert not (tmp_path / artifact_store.FRAMES_DIRNAME).exists()


def test_run_capture_still_keeps_at_most_three_frames(tmp_path: Path) -> None:
    behavior = FakeReplayBehavior(recording_instant=True)
    with FakeReplayApiServer(behavior) as server:
        result = run_capture(
            client=_client(server),
            clock=_clock(),
            capture_id="cap_still",
            start_game_ms=_START_MS,
            end_game_ms=_START_MS + 10_000,
            directory=tmp_path,
            mode=CaptureMode.STILL,
            fps=2.0,
            sleep_clock=FakeClock(),
        )
    assert result.ok is True
    assert 1 <= len(result.artifacts) <= 3


def test_run_capture_cancellation_leaves_no_partials(tmp_path: Path) -> None:
    behavior = FakeReplayBehavior(recording_poll_steps=100)
    cancel = threading.Event()
    with FakeReplayApiServer(behavior) as server:
        client = _client(server)
        clock = FakeClock()
        clock.on_sleep = lambda _seconds: cancel.set()
        result = run_capture(
            client=client,
            clock=_clock(),
            capture_id="cap_cancel",
            start_game_ms=_START_MS,
            end_game_ms=_END_MS,
            directory=tmp_path,
            mode=CaptureMode.CLIP,
            cancel=cancel,
            poll_s=0.01,
            sleep_clock=clock,
        )
        stopped = client.get_recording()
    assert result.ok is False
    assert result.status is CaptureStatus.CANCELLED
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.CAPTURE_CANCELLED
    assert stopped.recording is False
    assert list(tmp_path.iterdir()) == []


def test_run_capture_cancel_wins_over_api_loss(tmp_path: Path) -> None:
    """Intentional cancel + Replay API death must surface CANCELLED, not FAILED."""
    behavior = FakeReplayBehavior(recording_poll_steps=100)
    cancel = threading.Event()
    with FakeReplayApiServer(behavior) as server:
        real = _client(server)

        class _CancelThenUnavailable:
            def __init__(self) -> None:
                self._gets = 0

            def get_recording(self) -> object:
                self._gets += 1
                if self._gets >= 1:
                    cancel.set()
                    raise ReplayError(
                        ReplayErrorCode.REPLAY_API_UNAVAILABLE,
                        details={"reason": "injected_api_loss"},
                    )
                return real.get_recording()

            def set_recording(self, patch: object) -> object:
                return real.set_recording(patch)  # type: ignore[arg-type]

            def get_playback(self) -> object:
                return real.get_playback()

            def set_playback(self, **kwargs: object) -> object:
                return real.set_playback(**kwargs)  # type: ignore[arg-type]

        result = run_capture(
            client=_CancelThenUnavailable(),
            clock=_clock(),
            capture_id="cap_cancel_api_loss",
            start_game_ms=_START_MS,
            end_game_ms=_END_MS,
            directory=tmp_path,
            mode=CaptureMode.CLIP,
            cancel=cancel,
            poll_s=0.01,
            sleep_clock=FakeClock(),
        )
    assert result.status is CaptureStatus.CANCELLED
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.CAPTURE_CANCELLED
    assert list(tmp_path.iterdir()) == []


def test_run_capture_timeout_is_typed(tmp_path: Path) -> None:
    behavior = FakeReplayBehavior(recording_poll_steps=10_000)
    with FakeReplayApiServer(behavior) as server:
        result = run_capture(
            client=_client(server),
            clock=_clock(),
            capture_id="cap_timeout",
            start_game_ms=_START_MS,
            end_game_ms=_END_MS,
            directory=tmp_path,
            mode=CaptureMode.CLIP,
            timeout_s=1.0,
            poll_s=0.5,
            sleep_clock=FakeClock(),
        )
    assert result.ok is False
    assert result.status is CaptureStatus.FAILED
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.CAPTURE_TIMEOUT


def test_run_capture_reports_missing_and_empty_output(tmp_path: Path) -> None:
    missing = FakeReplayBehavior(recording_instant=True, recording_write_output=False)
    with FakeReplayApiServer(missing) as server:
        result = run_capture(
            client=_client(server),
            clock=_clock(),
            capture_id="cap_missing",
            start_game_ms=_START_MS,
            end_game_ms=_END_MS,
            directory=tmp_path / "missing",
            mode=CaptureMode.CLIP,
            sleep_clock=FakeClock(),
        )
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.CAPTURE_OUTPUT_MISSING

    empty = FakeReplayBehavior(recording_instant=True, recording_clip_payload=b"")
    with FakeReplayApiServer(empty) as server:
        result = run_capture(
            client=_client(server),
            clock=_clock(),
            capture_id="cap_empty",
            start_game_ms=_START_MS,
            end_game_ms=_END_MS,
            directory=tmp_path / "empty",
            mode=CaptureMode.CLIP,
            sleep_clock=FakeClock(),
        )
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.CAPTURE_OUTPUT_EMPTY


def test_run_capture_refuses_uncovered_interval(tmp_path: Path) -> None:
    behavior = FakeReplayBehavior(recording_instant=True)
    with FakeReplayApiServer(behavior) as server:
        result = run_capture(
            client=_client(server),
            clock=ClockMap.identity(duration_ms=60_000),
            capture_id="cap_oob",
            start_game_ms=_START_MS,
            end_game_ms=_END_MS,
            directory=tmp_path,
            mode=CaptureMode.CLIP,
            sleep_clock=FakeClock(),
        )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.CLOCK_OUT_OF_BOUNDS


# --- CaptureService end to end ---------------------------------------------------


async def test_capture_service_persists_rows_manifest_and_artifacts(
    engine: Engine, capture_settings: Settings, tmp_path: Path
) -> None:
    behavior = FakeReplayBehavior(recording_instant=True)
    await _seed_match(engine)
    with FakeReplayApiServer(behavior) as server:
        host = FakeReplayHost(recording_client=_client(server), sleep_clock=FakeClock())
        source_id = await _import_source(engine, host, tmp_path)
        host.open_session("ignored")
        service = _capture_service(engine, host, capture_settings)
        started = await service.start_capture(
            CaptureRequest(
                source_id=source_id,
                start_game_ms=_START_MS,
                end_game_ms=_START_MS + 4_000,
                mode=CaptureMode.SAMPLED,
                fps=1.0,
                review_id="rev_1",
            ),
            now_ms=100,
        )
        assert started.ok is True
        assert started.status is CaptureStatus.REQUESTED
        result = await service.await_result(started.capture_id)
    assert result.ok is True
    assert result.status is CaptureStatus.COMPLETE
    assert len(result.artifacts) == 5

    repo = SqlCaptureRepository(make_session_factory(engine))
    row = await repo.get_interval(started.capture_id)
    assert row is not None
    assert row.status == CaptureStatus.COMPLETE.value
    assert row.progress == pytest.approx(1.0)
    assert row.artifact_count == 5
    assert row.total_bytes > 0
    assert row.match_id == _MATCH
    assert row.clock_map_id is not None
    assert row.t_start_source_ms == _START_MS
    assert row.review_id == "rev_1"
    artifacts = await repo.list_artifacts(started.capture_id)
    assert [item.game_t_ms for item in artifacts] == [
        _START_MS + step for step in (0, 1_000, 2_000, 3_000, 4_000)
    ]
    assert all(item.retention_class == RetentionClass.REVIEW.value for item in artifacts)
    assert all(Path(item.path).is_file() for item in artifacts)

    directory = artifact_store.capture_dir(
        capture_settings.captures_dir, _MATCH, started.capture_id
    )
    manifest_path = directory / CAPTURE_MANIFEST_NAME
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["capture_id"] == started.capture_id
    assert manifest["clock_map_id"] == row.clock_map_id
    assert manifest["match_id"] == _MATCH
    assert manifest["camera_controlled"] is False
    assert len(manifest["artifacts"]) == 5
    assert artifact_store.read_manifest(directory) is not None


async def test_capture_service_refuses_when_session_not_ready(
    engine: Engine, capture_settings: Settings, tmp_path: Path
) -> None:
    behavior = FakeReplayBehavior(recording_instant=True)
    await _seed_match(engine)
    with FakeReplayApiServer(behavior) as server:
        host = FakeReplayHost(recording_client=_client(server))
        source_id = await _import_source(engine, host, tmp_path)
        service = _capture_service(engine, host, capture_settings)
        result = await service.start_capture(
            CaptureRequest(
                source_id=source_id,
                start_game_ms=_START_MS,
                end_game_ms=_END_MS,
                mode=CaptureMode.CLIP,
            ),
            now_ms=100,
        )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.SOURCE_NOT_READY
    assert host.capture_count == 0


async def test_capture_service_enforces_review_budget(
    engine: Engine, capture_settings: Settings, tmp_path: Path
) -> None:
    behavior = FakeReplayBehavior(recording_instant=True)
    await _seed_match(engine)
    with FakeReplayApiServer(behavior) as server:
        host = FakeReplayHost(recording_client=_client(server), sleep_clock=FakeClock())
        source_id = await _import_source(engine, host, tmp_path)
        host.open_session("ignored")
        service = _capture_service(
            engine,
            host,
            capture_settings,
            budget=CaptureBudget(max_seconds=10.0, max_artifacts=200, max_bytes=1 << 40),
        )
        result = await service.start_capture(
            CaptureRequest(
                source_id=source_id,
                start_game_ms=_START_MS,
                end_game_ms=_START_MS + 25_000,
                mode=CaptureMode.CLIP,
                review_id="rev_budget",
            ),
            now_ms=100,
        )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.CAPTURE_BUDGET_EXCEEDED
    assert host.capture_count == 0


async def test_capture_service_cancel_marks_row_and_deletes_files(
    engine: Engine, capture_settings: Settings, tmp_path: Path
) -> None:
    behavior = FakeReplayBehavior(recording_poll_steps=10_000)
    await _seed_match(engine)
    with FakeReplayApiServer(behavior) as server:
        host = FakeReplayHost(recording_client=_client(server), sleep_clock=None)
        source_id = await _import_source(engine, host, tmp_path)
        host.open_session("ignored")
        service = _capture_service(engine, host, capture_settings)
        started = await service.start_capture(
            CaptureRequest(
                source_id=source_id,
                start_game_ms=_START_MS,
                end_game_ms=_END_MS,
                mode=CaptureMode.CLIP,
            ),
            now_ms=100,
        )
        cancelled = await service.cancel(started.capture_id)
    assert cancelled.status is CaptureStatus.CANCELLED
    repo = SqlCaptureRepository(make_session_factory(engine))
    row = await repo.get_interval(started.capture_id)
    assert row is not None
    assert row.error_code == ReplayErrorCode.CAPTURE_CANCELLED.value
    assert row.artifact_count == 0
    directory = artifact_store.capture_dir(
        capture_settings.captures_dir, _MATCH, started.capture_id
    )
    assert not directory.exists()


async def test_reveal_never_starts_a_capture(
    engine: Engine, capture_settings: Settings, tmp_path: Path
) -> None:
    behavior = FakeReplayBehavior(recording_instant=True)
    await _seed_match(engine)
    with FakeReplayApiServer(behavior) as server:
        host = FakeReplayHost(recording_client=_client(server), sleep_clock=FakeClock())
        source_id = await _import_source(engine, host, tmp_path)
        factory = make_session_factory(engine)
        capture_service = _capture_service(engine, host, capture_settings)
        service = GameplaySourceService(
            host=host,
            gameplay=SqlGameplayRepository(factory),
            matches=SqlMatchRepository(factory),
            captures=capture_service,
        )
        outcome = await service.reveal(source_id, 140_000, lead_in_ms=8_000, now_ms=120)
    assert outcome.ok is True
    assert host.capture_count == 0
    assert await SqlCaptureRepository(make_session_factory(engine)).list_all() == []
    assert list(capture_settings.captures_dir.rglob("*")) == []


# --- retention -------------------------------------------------------------------


async def _seed_capture_row(
    repo: SqlCaptureRepository,
    root: Path,
    *,
    source_id: str,
    retention: RetentionClass,
    status: CaptureStatus = CaptureStatus.COMPLETE,
    review_id: str | None = None,
    created_at: int = 0,
    payload: bytes = b"0123456789",
) -> CaptureIntervalRecord:
    capture_id = new_ulid()
    record = CaptureIntervalRecord(
        id=capture_id,
        gameplay_source_id=source_id,
        match_id=_MATCH,
        clock_map_id=None,
        t_start_ms=_START_MS,
        t_end_ms=_END_MS,
        reason="test",
        mode=CaptureMode.CLIP.value,
        fps=30.0,
        status=status.value,
        progress=1.0,
        retention_class=retention.value,
        created_at=created_at,
        review_id=review_id,
        artifact_count=1,
        total_bytes=len(payload),
    )
    await repo.upsert_interval(record)
    directory = artifact_store.ensure_capture_dir(root, _MATCH, capture_id)
    (directory / "clip_g0.webm").write_bytes(payload)
    return record


async def test_retention_cleanup_review_and_ephemeral(
    engine: Engine, capture_settings: Settings, tmp_path: Path
) -> None:
    await _seed_match(engine)
    host = FakeReplayHost()
    source_id = await _import_source(engine, host, tmp_path)
    repo = SqlCaptureRepository(make_session_factory(engine))
    root = capture_settings.captures_dir
    reviewed = await _seed_capture_row(
        repo, root, source_id=source_id, retention=RetentionClass.REVIEW, review_id="rev_x"
    )
    ephemeral = await _seed_capture_row(
        repo, root, source_id=source_id, retention=RetentionClass.EPHEMERAL
    )
    pinned = await _seed_capture_row(
        repo, root, source_id=source_id, retention=RetentionClass.PINNED
    )
    retention = RetentionService(captures=repo, captures_dir=root)

    report = await retention.cleanup_review("rev_x")
    assert report.deleted_capture_ids == [reviewed.id]
    assert not artifact_store.capture_dir(root, _MATCH, reviewed.id).exists()

    await retention.cleanup_ephemeral()
    assert not artifact_store.capture_dir(root, _MATCH, ephemeral.id).exists()

    remaining = {row.id for row in await repo.list_all()}
    assert remaining == {pinned.id}
    assert artifact_store.capture_dir(root, _MATCH, pinned.id).is_dir()


async def test_startup_gc_removes_partials_and_orphans(
    engine: Engine, capture_settings: Settings, tmp_path: Path
) -> None:
    await _seed_match(engine)
    host = FakeReplayHost()
    source_id = await _import_source(engine, host, tmp_path)
    repo = SqlCaptureRepository(make_session_factory(engine))
    root = capture_settings.captures_dir
    failed = await _seed_capture_row(
        repo,
        root,
        source_id=source_id,
        retention=RetentionClass.REVIEW,
        status=CaptureStatus.FAILED,
    )
    kept = await _seed_capture_row(
        repo, root, source_id=source_id, retention=RetentionClass.REVIEW
    )
    orphan = artifact_store.ensure_capture_dir(root, _MATCH, "orphan_capture")
    (orphan / "clip_g0.webm").write_bytes(b"junk")

    retention = RetentionService(captures=repo, captures_dir=root)
    report = await retention.startup_gc()

    assert failed.id in report.deleted_capture_ids
    assert not orphan.exists()
    assert artifact_store.capture_dir(root, _MATCH, kept.id).is_dir()
    assert {row.id for row in await repo.list_all()} == {kept.id}


async def test_size_ceiling_evicts_oldest_but_never_pinned(
    engine: Engine, capture_settings: Settings, tmp_path: Path
) -> None:
    await _seed_match(engine)
    host = FakeReplayHost()
    source_id = await _import_source(engine, host, tmp_path)
    repo = SqlCaptureRepository(make_session_factory(engine))
    root = capture_settings.captures_dir
    pinned = await _seed_capture_row(
        repo,
        root,
        source_id=source_id,
        retention=RetentionClass.PINNED,
        created_at=1,
        payload=b"x" * 100,
    )
    old = await _seed_capture_row(
        repo,
        root,
        source_id=source_id,
        retention=RetentionClass.REVIEW,
        created_at=2,
        payload=b"x" * 100,
    )
    recent = await _seed_capture_row(
        repo,
        root,
        source_id=source_id,
        retention=RetentionClass.REVIEW,
        created_at=3,
        payload=b"x" * 100,
    )
    retention = RetentionService(
        captures=repo, captures_dir=root, policy=RetentionPolicy(max_total_bytes=250)
    )

    report = await retention.enforce_size_ceiling()

    assert report.deleted_capture_ids == [old.id]
    assert {row.id for row in await repo.list_all()} == {pinned.id, recent.id}
    assert artifact_store.capture_dir(root, _MATCH, pinned.id).is_dir()


# --- HTTP surface ----------------------------------------------------------------


def _poll_capture(client: TestClient, capture_id: str, *, attempts: int = 200) -> dict[str, Any]:
    """Poll the capture endpoint until the job reaches a terminal status."""
    payload: dict[str, Any] = {}
    for _ in range(attempts):
        payload = client.get(f"/gameplay/captures/{capture_id}", headers=_AUTH).json()
        if payload["status"] in {status.value for status in TERMINAL_STATUSES}:
            return payload
        time.sleep(0.02)
    return payload


def test_capture_endpoints_roundtrip(capture_settings: Settings, tmp_path: Path) -> None:
    seeded = init_database(capture_settings)
    asyncio.run(_seed_match(seeded))
    seeded.dispose()
    behavior = FakeReplayBehavior(recording_instant=True)
    with FakeReplayApiServer(behavior) as server:
        host = FakeReplayHost(recording_client=_client(server), sleep_clock=FakeClock())
        app = create_app(settings=capture_settings, token="test-token", replay_host=host)
        with TestClient(app) as client:
            rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
            source_id = client.post(
                "/gameplay/import",
                headers=_AUTH,
                json={"path": str(rofl), "match_id": _MATCH},
            ).json()["source_id"]
            client.post(
                "/gameplay/open",
                headers=_AUTH,
                json={"source_id": source_id, "match_id": _MATCH},
            )
            created = client.post(
                "/gameplay/captures",
                headers=_AUTH,
                json={
                    "source_id": source_id,
                    "start_game_ms": _START_MS,
                    "end_game_ms": _START_MS + 2_000,
                    "mode": "SAMPLED",
                    "fps": 1.0,
                    "retention": "review",
                    "review_id": "rev_http",
                },
            ).json()
            assert created["ok"] is True, created["error"]
            assert created["status"] == CaptureStatus.REQUESTED.value
            capture_id = created["capture_id"]
            fetched = _poll_capture(client, capture_id)
            unknown = client.get("/gameplay/captures/nope", headers=_AUTH).json()
            cancelled = client.post(
                f"/gameplay/captures/{capture_id}/cancel", headers=_AUTH
            ).json()
    assert fetched["status"] == CaptureStatus.COMPLETE.value
    assert fetched["progress"] == pytest.approx(1.0)
    assert len(fetched["artifacts"]) == 3
    assert fetched["manifest"]["mode"] == "SAMPLED"
    assert fetched["manifest"]["camera_controlled"] is False
    assert unknown["ok"] is False
    assert unknown["error"]["code"] == ReplayErrorCode.CAPTURE_OUTPUT_MISSING.value
    assert cancelled["status"] == CaptureStatus.COMPLETE.value


def test_capture_endpoints_require_bearer(capture_settings: Settings) -> None:
    host = FakeReplayHost()
    app = create_app(settings=capture_settings, token="test-token", replay_host=host)
    with TestClient(app) as client:
        assert client.get("/gameplay/captures/anything").status_code == 401
        assert client.post("/gameplay/captures", json={}).status_code == 401
