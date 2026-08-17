from __future__ import annotations

import threading
from pathlib import Path

from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.api.replay_client import ReplayApiClient
from riftlens.replay_host.launch_strategies import (
    DirectExeStrategy,
    LcuWatchStrategy,
    ShellOpenStrategy,
    UserAssistedStrategy,
)
from riftlens.replay_host.lcu.lockfile import parse_lcu_lockfile
from riftlens.replay_host.session import ReplaySessionPhase
from riftlens.replay_host.supervisor import ReplayApiTransport, ReplayProcessSupervisor
from riftlens.replay_host.windows.install_locator import (
    InstallDiscoveryMethod,
    LeagueInstall,
    validate_install_root,
)
from tests.fakes.fake_replay_runtime import (
    FakeClock,
    FakeLcu,
    FakeLiveProbe,
    FakeProcessHandle,
    FakeProcessOps,
    ScriptedTransport,
    playback,
    unavailable,
    write_tiny_rofl,
)
from tests.fakes.fake_replay_server import FakeReplayApiServer, FakeReplayBehavior


def _install(tmp: Path) -> LeagueInstall:
    root = tmp / "League of Legends"
    (root / "Config").mkdir(parents=True)
    (root / "Game").mkdir()
    (root / "Game" / "League of Legends.exe").write_bytes(b"mz")
    (root / "LeagueClient.exe").write_bytes(b"mz")
    return validate_install_root(root, discovery_method=InstallDiscoveryMethod.CONFIGURED)


def _rofl(tmp: Path) -> Path:
    return write_tiny_rofl(tmp / "NA1-5617764200.rofl")


def _supervisor(
    tmp: Path,
    *,
    transport: ScriptedTransport | ReplayApiTransport | None = None,
    processes: FakeProcessOps | None = None,
    lcu: FakeLcu | None = None,
    live: FakeLiveProbe | None = None,
    clock: FakeClock | None = None,
    strategies: list[object] | None = None,
    timeout_s: float = 8.0,
    allow_user_assisted: bool = False,
    cancel_event: threading.Event | None = None,
) -> tuple[ReplayProcessSupervisor, Path, FakeProcessOps]:
    ops = processes if processes is not None else FakeProcessOps()
    supervisor = ReplayProcessSupervisor(
        transport=transport
        if transport is not None
        else ScriptedTransport([playback(time=2.0), playback(time=4.0)]),
        live_probe=live if live is not None else FakeLiveProbe(False),
        processes=ops,
        lcu=lcu if lcu is not None else FakeLcu(),
        clock=clock if clock is not None else FakeClock(),
        strategies=strategies,  # type: ignore[arg-type]
        startup_timeout_s=timeout_s,
        allow_user_assisted=allow_user_assisted,
        cancel_event=cancel_event,
    )
    return supervisor, _rofl(tmp), ops


def test_launch_strategy_succeeds_immediately(tmp_path: Path) -> None:
    supervisor, rofl, ops = _supervisor(tmp_path)
    snap = supervisor.open(rofl, _install(tmp_path))
    assert snap.is_active
    assert snap.reached_ready is True
    assert snap.winning_strategy == "direct_exe"
    assert snap.owns_process is True
    assert ops.direct_calls == 1
    assert ops.shell_calls == 0
    assert snap.phase is ReplaySessionPhase.PLAYING


def test_first_strategy_fails_then_fallback_succeeds(tmp_path: Path) -> None:
    lcu = FakeLcu(available=True, watch_error=ReplayError(ReplayErrorCode.LAUNCH_FAILED))
    ops = FakeProcessOps()
    supervisor, rofl, _ops = _supervisor(tmp_path, lcu=lcu, processes=ops)
    snap = supervisor.open(rofl, _install(tmp_path))
    assert snap.winning_strategy == "direct_exe"
    assert [item.strategy for item in supervisor.attempts][:2] == ["lcu_watch", "direct_exe"]
    assert supervisor.attempts[0].ok is False
    assert lcu.watch_calls == 1


def test_all_launch_strategies_fail(tmp_path: Path) -> None:
    ops = FakeProcessOps(
        direct=ReplayError(ReplayErrorCode.LAUNCH_FAILED, details={"reason": "spawn"}),
        shell_error=ReplayError(ReplayErrorCode.LAUNCH_FAILED, details={"reason": "shell"}),
    )
    supervisor, rofl, _ops = _supervisor(
        tmp_path,
        processes=ops,
        allow_user_assisted=False,
        strategies=[DirectExeStrategy(), ShellOpenStrategy(), UserAssistedStrategy()],
    )
    snap = supervisor.open(rofl, _install(tmp_path))
    assert snap.phase is ReplaySessionPhase.FAILED
    assert snap.error is not None
    assert snap.error.code is ReplayErrorCode.LAUNCH_FAILED
    assert snap.reached_ready is False


def test_replay_api_initially_unavailable_then_ready(tmp_path: Path) -> None:
    transport = ScriptedTransport(
        [unavailable(), unavailable(), playback(time=2.0), playback(time=5.0)]
    )
    clock = FakeClock()
    supervisor, rofl, _ops = _supervisor(tmp_path, transport=transport, clock=clock)
    snap = supervisor.open(rofl, _install(tmp_path))
    assert snap.reached_ready is True
    assert clock.sleeps


def test_startup_timeout(tmp_path: Path) -> None:
    transport = ScriptedTransport([unavailable()])
    supervisor, rofl, _ops = _supervisor(
        tmp_path, transport=transport, clock=FakeClock(), timeout_s=1.0
    )
    snap = supervisor.open(rofl, _install(tmp_path))
    assert snap.phase is ReplaySessionPhase.FAILED
    assert snap.error is not None
    assert snap.error.code is ReplayErrorCode.LAUNCH_TIMEOUT


def test_process_exits_immediately(tmp_path: Path) -> None:
    ops = FakeProcessOps(direct=FakeProcessHandle(7, running=False))
    supervisor, rofl, _ops = _supervisor(
        tmp_path,
        processes=ops,
        strategies=[DirectExeStrategy()],
        allow_user_assisted=False,
    )
    snap = supervisor.open(rofl, _install(tmp_path))
    assert snap.phase is ReplaySessionPhase.FAILED
    assert snap.error is not None
    assert snap.error.code is ReplayErrorCode.LAUNCH_REJECTED


def test_process_exits_during_connect(tmp_path: Path) -> None:
    handle = FakeProcessHandle(8, running=True)

    def die_then_unavailable() -> ReplayError:
        handle.running = False
        return unavailable()

    transport = ScriptedTransport([die_then_unavailable])
    ops = FakeProcessOps(direct=handle)
    supervisor, rofl, _ops = _supervisor(tmp_path, transport=transport, processes=ops)
    snap = supervisor.open(rofl, _install(tmp_path))
    assert snap.error is not None
    assert snap.error.code is ReplayErrorCode.LAUNCH_REJECTED


def test_playback_length_remains_zero(tmp_path: Path) -> None:
    transport = ScriptedTransport([playback(length=0.0, time=0.0)])
    supervisor, rofl, _ops = _supervisor(
        tmp_path, transport=transport, clock=FakeClock(), timeout_s=1.0
    )
    snap = supervisor.open(rofl, _install(tmp_path))
    assert snap.error is not None
    assert snap.error.code is ReplayErrorCode.PLAYBACK_NOT_STARTED
    assert snap.reached_ready is False


def test_playback_does_not_advance(tmp_path: Path) -> None:
    frozen = playback(time=10.0, paused=False)
    transport = ScriptedTransport([frozen, frozen])
    supervisor, rofl, _ops = _supervisor(tmp_path, transport=transport)
    snap = supervisor.open(rofl, _install(tmp_path))
    assert snap.error is not None
    assert snap.error.code is ReplayErrorCode.PLAYBACK_NOT_ADVANCING
    assert snap.reached_ready is False


def test_playback_at_end_rewinds_then_ready(tmp_path: Path) -> None:
    """A finished replay (clock at length) is still a usable Replay API session."""
    ended = playback(length=2484.4, time=2484.4, paused=True)
    unpaused = playback(length=2484.4, time=2484.4, paused=False)
    rewound = playback(length=2484.4, time=5.0, paused=False)
    advancing = playback(length=2484.4, time=6.4, paused=False)
    transport = ScriptedTransport([ended, unpaused, unpaused, rewound, advancing])
    supervisor, rofl, _ops = _supervisor(tmp_path, transport=transport)
    snap = supervisor.open(rofl, _install(tmp_path))
    assert snap.error is None, snap.error
    assert snap.reached_ready is True
    assert any(call.get("time") == 5.0 for call in transport.set_calls)


def test_ready_only_after_playback_verification(tmp_path: Path) -> None:
    seen: list[ReplaySessionPhase] = []
    box: dict[str, ReplayProcessSupervisor] = {}

    def capture() -> ReplayError:
        seen.append(box["s"].snapshot.phase)
        return unavailable()

    transport = ScriptedTransport([capture, playback(time=1.0), playback(time=3.0)])
    supervisor, rofl, _ops = _supervisor(tmp_path, transport=transport)
    box["s"] = supervisor
    assert supervisor.snapshot.is_active is False
    snap = supervisor.open(rofl, _install(tmp_path))
    assert ReplaySessionPhase.CONNECTING in seen
    assert all(phase is not ReplaySessionPhase.READY for phase in seen)
    assert snap.reached_ready is True
    assert snap.is_active is True


def test_user_closes_replay_session_lost_without_relaunch(tmp_path: Path) -> None:
    handle = FakeProcessHandle(11)
    ops = FakeProcessOps(direct=handle)
    supervisor, rofl, _ops = _supervisor(tmp_path, processes=ops)
    snap = supervisor.open(rofl, _install(tmp_path))
    assert snap.is_active
    direct_calls = ops.direct_calls
    handle.running = False
    lost = supervisor.poll_health()
    assert lost.phase is ReplaySessionPhase.FAILED
    assert lost.error is not None
    assert lost.error.code is ReplayErrorCode.SESSION_LOST
    assert lost.relaunch_count == 0
    again = supervisor.poll_health()
    assert again.phase is ReplaySessionPhase.FAILED
    assert ops.direct_calls == direct_calls


def test_teardown_owned_process_only(tmp_path: Path) -> None:
    handle = FakeProcessHandle(12)
    ops = FakeProcessOps(direct=handle)
    supervisor, rofl, _ops = _supervisor(tmp_path, processes=ops)
    supervisor.open(rofl, _install(tmp_path))
    closed = supervisor.close()
    assert closed.phase is ReplaySessionPhase.CLOSED
    assert handle.terminated is True
    assert ops.unrelated.terminated is False
    assert ops.unrelated.running is True


def test_teardown_without_ownership_does_not_kill(tmp_path: Path) -> None:
    ops = FakeProcessOps()
    supervisor, rofl, _ops = _supervisor(
        tmp_path,
        processes=ops,
        strategies=[UserAssistedStrategy()],
        allow_user_assisted=True,
    )
    supervisor.open(rofl, _install(tmp_path))
    assert supervisor.snapshot.owns_process is False
    supervisor.close()
    assert isinstance(ops.direct, FakeProcessHandle)
    assert ops.direct.terminated is False
    assert ops.unrelated.terminated is False


def test_cancellation_during_launch(tmp_path: Path) -> None:
    cancel = threading.Event()
    clock = FakeClock()
    clock.on_sleep = lambda _s: cancel.set()
    transport = ScriptedTransport([unavailable(), playback(time=2.0), playback(time=4.0)])
    supervisor, rofl, ops = _supervisor(
        tmp_path, transport=transport, clock=clock, cancel_event=cancel
    )
    snap = supervisor.open(rofl, _install(tmp_path))
    assert snap.phase is ReplaySessionPhase.CLOSED
    assert snap.cancelled is True
    assert snap.reached_ready is False
    assert ops.direct.terminated is True  # type: ignore[union-attr]


def test_transient_errors_during_startup_are_retried(tmp_path: Path) -> None:
    transport = ScriptedTransport(
        [
            ReplayError(ReplayErrorCode.REPLAY_API_UNAVAILABLE, details={"status": 500}),
            playback(time=1.5),
            playback(time=3.5),
        ]
    )
    supervisor, rofl, _ops = _supervisor(tmp_path, transport=transport)
    snap = supervisor.open(rofl, _install(tmp_path))
    assert snap.reached_ready is True


def test_terminal_tls_during_startup(tmp_path: Path) -> None:
    transport = ScriptedTransport(
        [ReplayError(ReplayErrorCode.REPLAY_API_TLS, details={"reason": "tls_verify_failed"})]
    )
    supervisor, rofl, _ops = _supervisor(
        tmp_path, transport=transport, clock=FakeClock(), timeout_s=1.0
    )
    snap = supervisor.open(rofl, _install(tmp_path))
    assert snap.error is not None
    assert snap.error.code is ReplayErrorCode.REPLAY_API_TLS
    assert snap.reached_ready is False


def test_schema_error_during_startup(tmp_path: Path) -> None:
    transport = ScriptedTransport(
        [ReplayError(ReplayErrorCode.PLAYBACK_UNREADABLE, details={"reason": "invalid_schema"})]
    )
    supervisor, rofl, _ops = _supervisor(tmp_path, transport=transport)
    snap = supervisor.open(rofl, _install(tmp_path))
    assert snap.error is not None
    assert snap.error.code is ReplayErrorCode.PLAYBACK_UNREADABLE


def test_live_game_lcu_phase_prevents_launch(tmp_path: Path) -> None:
    ops = FakeProcessOps()
    supervisor, rofl, _ops = _supervisor(
        tmp_path, lcu=FakeLcu(phase="InProgress"), processes=ops
    )
    snap = supervisor.open(rofl, _install(tmp_path))
    assert snap.phase is ReplaySessionPhase.FAILED
    assert snap.error is not None
    assert snap.error.code is ReplayErrorCode.LIVE_GAME_IN_PROGRESS
    assert ops.direct_calls == 0


def test_live_game_lcd_without_replay_api_prevents_launch(tmp_path: Path) -> None:
    ops = FakeProcessOps()
    supervisor, rofl, _ops = _supervisor(
        tmp_path,
        transport=ScriptedTransport([unavailable()]),
        live=FakeLiveProbe(True),
        processes=ops,
    )
    snap = supervisor.open(rofl, _install(tmp_path))
    assert snap.error is not None
    assert snap.error.code is ReplayErrorCode.LIVE_GAME_IN_PROGRESS
    assert ops.direct_calls == 0


def test_uncertain_live_detection_does_not_invent_certainty(tmp_path: Path) -> None:
    supervisor, rofl, ops = _supervisor(
        tmp_path,
        transport=ScriptedTransport([unavailable(), playback(time=2.0), playback(time=4.0)]),
        live=FakeLiveProbe(False),
        lcu=FakeLcu(available=False, phase=None),
    )
    snap = supervisor.open(rofl, _install(tmp_path))
    assert snap.reached_ready is True
    assert ops.direct_calls == 1


def test_lcu_skip_does_not_block_direct_exe(tmp_path: Path) -> None:
    supervisor, rofl, _ops = _supervisor(
        tmp_path,
        lcu=FakeLcu(available=False),
        strategies=[LcuWatchStrategy(), DirectExeStrategy()],
    )
    snap = supervisor.open(rofl, _install(tmp_path))
    assert snap.winning_strategy == "direct_exe"
    assert supervisor.attempts[0].skipped is True


def test_lockfile_password_is_redacted(tmp_path: Path) -> None:
    parsed = parse_lcu_lockfile(
        "LeagueClient:1234:53921:super-secret:https", path=tmp_path / "lockfile"
    )
    dumped = parsed.redacted_dict()
    assert dumped["password"] == "***"
    assert "super-secret" not in str(dumped)


def test_t1_fake_https_server_connect_poll(tmp_path: Path) -> None:
    behavior = FakeReplayBehavior(
        transient_failures={"/replay/playback": 2},
        time_frozen=False,
        playback={
            "length": 1902.97,
            "paused": False,
            "seeking": False,
            "speed": 1,
            "time": 2.0,
        },
    )
    with FakeReplayApiServer(behavior) as server:
        replay = ReplayApiClient(
            server.origin,
            ca_file=str(server.ca_file),
            timeout_s=2.0,
            max_retries=0,
        )
        transport = ReplayApiTransport(replay=replay)
        supervisor, rofl, _ops = _supervisor(
            tmp_path, transport=transport, clock=FakeClock(), timeout_s=10.0
        )
        snap = supervisor.open(rofl, _install(tmp_path))
        assert snap.reached_ready is True
        assert snap.playback is not None
        assert snap.playback.length_ms > 0
        supervisor.close()
