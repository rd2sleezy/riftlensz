from __future__ import annotations

from riftlens.domain.clock_map import ClockMap
from riftlens.domain.gameplay_source import PlaybackState
from riftlens.domain.replay_errors import ReplayErrorCode
from riftlens.domain.sync_map import SEEK_LEAD_IN_MS
from riftlens.replay_host.api.replay_client import ReplayApiClient
from riftlens.replay_host.seek import (
    LANDING_TOLERANCE_MS,
    verified_seek,
)
from riftlens.replay_host.session import ReplaySessionMachine
from tests.fakes.fake_replay_runtime import FakeClock
from tests.fakes.fake_replay_server import FakeReplayApiServer, FakeReplayBehavior


def _client(server: FakeReplayApiServer) -> ReplayApiClient:
    return ReplayApiClient(
        server.origin,
        ca_file=str(server.ca_file),
        timeout_s=2.0,
        connect_timeout_s=1.0,
        max_retries=0,
    )


def _ready_machine(length_ms: int = 1_902_000) -> ReplaySessionMachine:
    machine = ReplaySessionMachine()
    machine.start_launch()
    machine.begin_connect()
    machine.mark_ready(
        PlaybackState(t_source_ms=2_000, length_ms=length_ms, paused=False, seeking=False)
    )
    return machine


def test_exact_seek_success_pauses_then_resumes() -> None:
    behavior = FakeReplayBehavior(time_frozen=False)
    clock = ClockMap.identity(duration_ms=1_902_000, verified=False)
    with FakeReplayApiServer(behavior) as server:
        outcome = verified_seek(
            _client(server),
            clock,
            60_000,
            lead_in_ms=0,
            machine=_ready_machine(),
            sleep_clock=FakeClock(),
        )
    assert outcome.ok is True
    assert outcome.target_source_ms == 60_000
    assert outcome.landed_source_ms is not None
    assert abs(outcome.landed_source_ms - 60_000) <= LANDING_TOLERANCE_MS
    assert outcome.resumed is True
    posts = [body for path, body in behavior.post_log if path == "/replay/playback"]
    assert posts[0].get("paused") is True
    assert "time" not in posts[0]
    assert any("time" in body for body in posts)
    assert posts[-1].get("paused") is False
    assert posts[-1].get("speed") == 1.0


def test_delayed_seeking_waits_until_false() -> None:
    behavior = FakeReplayBehavior(seeking_polls_remaining=3, time_frozen=False)
    with FakeReplayApiServer(behavior) as server:
        outcome = verified_seek(
            _client(server),
            ClockMap.identity(duration_ms=1_902_000, verified=False),
            180_000,
            lead_in_ms=0,
            machine=_ready_machine(),
            sleep_clock=FakeClock(),
        )
    assert outcome.ok is True
    assert outcome.attempts == 1


def test_seek_stuck_true_fails_without_resume() -> None:
    behavior = FakeReplayBehavior(seeking_stuck=True, time_frozen=False)
    with FakeReplayApiServer(behavior) as server:
        outcome = verified_seek(
            _client(server),
            ClockMap.identity(duration_ms=1_902_000, verified=False),
            60_000,
            lead_in_ms=0,
            then_play=True,
            machine=_ready_machine(),
            sleep_clock=FakeClock(),
        )
    assert outcome.ok is False
    assert outcome.resumed is False
    assert outcome.error is not None
    assert outcome.error.code is ReplayErrorCode.SEEK_FAILED
    assert outcome.error.details.get("reason") == "seeking_stuck"
    assert not any(
        body.get("paused") is False for _path, body in behavior.post_log if "time" not in body
    )


def test_seek_lands_outside_tolerance_no_silent_play() -> None:
    behavior = FakeReplayBehavior(seek_misses_remaining=2, time_frozen=False)
    with FakeReplayApiServer(behavior) as server:
        outcome = verified_seek(
            _client(server),
            ClockMap.identity(duration_ms=1_902_000, verified=False),
            60_000,
            lead_in_ms=0,
            machine=_ready_machine(),
            sleep_clock=FakeClock(),
        )
    assert outcome.ok is False
    assert outcome.resumed is False
    assert outcome.error is not None
    assert outcome.error.code is ReplayErrorCode.SEEK_TOLERANCE_EXCEEDED
    assert outcome.attempts == 2


def test_retry_succeeds_after_one_miss() -> None:
    behavior = FakeReplayBehavior(seek_misses_remaining=1, time_frozen=False)
    with FakeReplayApiServer(behavior) as server:
        outcome = verified_seek(
            _client(server),
            ClockMap.identity(duration_ms=1_902_000, verified=False),
            300_000,
            lead_in_ms=0,
            machine=_ready_machine(),
            sleep_clock=FakeClock(),
        )
    assert outcome.ok is True
    assert outcome.attempts == 2
    assert outcome.resumed is True


def test_retry_fails_after_two_misses() -> None:
    behavior = FakeReplayBehavior(seek_misses_remaining=5, time_frozen=False)
    with FakeReplayApiServer(behavior) as server:
        outcome = verified_seek(
            _client(server),
            ClockMap.identity(duration_ms=1_902_000, verified=False),
            60_000,
            lead_in_ms=0,
            machine=_ready_machine(),
            sleep_clock=FakeClock(),
        )
    assert outcome.ok is False
    assert outcome.attempts == 2
    assert outcome.error is not None
    assert outcome.error.code is ReplayErrorCode.SEEK_TOLERANCE_EXCEEDED


def test_pause_before_seek_order() -> None:
    behavior = FakeReplayBehavior(time_frozen=True)
    with FakeReplayApiServer(behavior) as server:
        outcome = verified_seek(
            _client(server),
            ClockMap.identity(duration_ms=1_902_000, verified=False),
            90_000,
            lead_in_ms=SEEK_LEAD_IN_MS,
            then_play=False,
            machine=_ready_machine(),
            sleep_clock=FakeClock(),
        )
    assert outcome.ok is True
    assert outcome.resumed is False
    assert outcome.target_game_ms == 82_000
    assert outcome.target_source_ms == 82_000
    posts = [body for _path, body in behavior.post_log]
    assert posts[0] == {"paused": True}
    assert posts[1].get("time") == 82.0
    assert posts[1].get("paused") is True


def test_resume_after_seek_requires_advancement() -> None:
    behavior = FakeReplayBehavior(time_frozen=True)
    with FakeReplayApiServer(behavior) as server:
        outcome = verified_seek(
            _client(server),
            ClockMap.identity(duration_ms=1_902_000, verified=False),
            60_000,
            lead_in_ms=0,
            then_play=True,
            machine=_ready_machine(),
            sleep_clock=FakeClock(),
        )
    assert outcome.ok is False
    assert outcome.error is not None
    assert outcome.error.code is ReplayErrorCode.PLAYBACK_NOT_ADVANCING
    assert outcome.resumed is False


def test_session_not_ready() -> None:
    behavior = FakeReplayBehavior()
    with FakeReplayApiServer(behavior) as server:
        outcome = verified_seek(
            _client(server),
            ClockMap.identity(duration_ms=1_902_000, verified=False),
            60_000,
            session_ready=False,
            sleep_clock=FakeClock(),
        )
    assert outcome.ok is False
    assert outcome.error is not None
    assert outcome.error.code is ReplayErrorCode.SOURCE_NOT_READY
    assert behavior.post_log == []


def test_target_outside_clock_map_domain() -> None:
    clock = ClockMap.offset(
        offset_ms=0,
        source_start_ms=0,
        source_end_ms=30_000,
        verified=True,
    )
    behavior = FakeReplayBehavior()
    with FakeReplayApiServer(behavior) as server:
        outcome = verified_seek(
            _client(server),
            clock,
            90_000,
            lead_in_ms=0,
            then_play=False,
            machine=_ready_machine(30_000),
            sleep_clock=FakeClock(),
        )
    assert outcome.ok is False
    assert outcome.error is not None
    assert outcome.error.code is ReplayErrorCode.CLOCK_OUT_OF_BOUNDS


def test_unmapped_clock_refuses_seek() -> None:
    behavior = FakeReplayBehavior()
    with FakeReplayApiServer(behavior) as server:
        outcome = verified_seek(
            _client(server),
            ClockMap.unmapped(duration_ms=1_902_000),
            60_000,
            lead_in_ms=0,
            machine=_ready_machine(),
            sleep_clock=FakeClock(),
        )
    assert outcome.ok is False
    assert outcome.error is not None
    assert outcome.error.code is ReplayErrorCode.CLOCK_UNMAPPED
