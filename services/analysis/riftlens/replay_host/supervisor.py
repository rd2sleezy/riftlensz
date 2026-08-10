from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.api.live_client import LiveClientDataClient
from riftlens.replay_host.api.models import ReplayPlayback
from riftlens.replay_host.api.replay_client import ReplayApiClient
from riftlens.replay_host.launch_strategies import (
    LaunchAttempt,
    LaunchContext,
    LaunchStrategy,
    ProcessHandle,
    ProcessOps,
    default_strategies,
    null_lcu,
    run_launch_chain,
    windows_process_ops,
)
from riftlens.replay_host.lcu.port import LcuReplayPort, is_live_gameflow_phase
from riftlens.replay_host.session import (
    ReplaySessionMachine,
    ReplaySessionPhase,
    ReplaySessionSnapshot,
)
from riftlens.replay_host.timing import SleepClock, WallClock
from riftlens.replay_host.windows.install_locator import LeagueInstall
from riftlens.rofl.identity import identify_rofl

DEFAULT_STARTUP_TIMEOUT_S = 120.0
MIN_POLL_INTERVAL_S = 0.25
MAX_POLL_INTERVAL_S = 2.0
ADVANCE_SAMPLE_GAP_S = 1.0
STARTUP_HTTP_RETRIES = 0


class PlaybackTransport(Protocol):
    """Replay API subset required for readiness. Tests inject scripted fakes."""

    def get_playback(self) -> ReplayPlayback:
        """GET /replay/playback."""

    def set_playback(
        self,
        *,
        paused: bool | None = None,
        time: float | None = None,
        speed: float | None = None,
        readback: bool = True,
    ) -> ReplayPlayback | None:
        """POST /replay/playback."""

    def get_game_process_id(self) -> int | None:
        """GET /replay/game processID when present."""


class LiveClientProbe(Protocol):
    """LCD subset used only for live-game safety."""

    def gamestats_reachable(self) -> bool:
        """Return True when /liveclientdata/gamestats answers."""


@dataclass
class ReplayApiTransport:
    """Adapter over R.4 clients. Does not reimplement HTTP."""

    replay: ReplayApiClient
    live: LiveClientDataClient | None = None

    def get_playback(self) -> ReplayPlayback:
        return self.replay.get_playback()

    def set_playback(
        self,
        *,
        paused: bool | None = None,
        time: float | None = None,
        speed: float | None = None,
        readback: bool = True,
    ) -> ReplayPlayback | None:
        return self.replay.set_playback(
            paused=paused, time=time, speed=speed, readback=readback
        )

    def get_game_process_id(self) -> int | None:
        try:
            game = self.replay.get_game()
        except ReplayError:
            return None
        return game.processID

    def gamestats_reachable(self) -> bool:
        if self.live is None:
            return False
        try:
            self.live.get_gamestats()
        except ReplayError:
            return False
        return True


class ReplayProcessSupervisor:
    """Launch chain + verified readiness + teardown. No clock calibration or seeking."""

    def __init__(
        self,
        *,
        transport: PlaybackTransport | None = None,
        live_probe: LiveClientProbe | None = None,
        processes: ProcessOps | None = None,
        lcu: LcuReplayPort | None = None,
        clock: SleepClock | None = None,
        strategies: Sequence[LaunchStrategy] | None = None,
        startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S,
        allow_user_assisted: bool = True,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self._machine = ReplaySessionMachine()
        self._transport = transport
        self._live_probe = live_probe
        self._processes = processes if processes is not None else windows_process_ops()
        self._lcu = lcu if lcu is not None else null_lcu()
        self._clock = clock if clock is not None else WallClock()
        self._strategies = tuple(strategies) if strategies is not None else default_strategies()
        self._startup_timeout_s = startup_timeout_s
        self._allow_user_assisted = allow_user_assisted
        self._cancel_event = cancel_event
        self._handle: ProcessHandle | None = None
        self._attempts: tuple[LaunchAttempt, ...] = ()
        self._last_identity: tuple[Path, str | None, int | None] = (Path("."), None, None)

    @property
    def snapshot(self) -> ReplaySessionSnapshot:
        """Return the current session snapshot."""
        return self._machine.snapshot

    @property
    def machine(self) -> ReplaySessionMachine:
        """Return the session state machine. Assumes the supervisor still owns it."""
        return self._machine

    @property
    def attempts(self) -> tuple[LaunchAttempt, ...]:
        """Return every launch-strategy attempt from the last ``open``."""
        return self._attempts

    def open(self, rofl_path: str | Path, install: LeagueInstall) -> ReplaySessionSnapshot:
        """Validate, safety-check, launch, and verify READY. Does not auto-relaunch."""
        if self.snapshot.phase is not ReplaySessionPhase.IDLE:
            raise ReplayError(
                ReplayErrorCode.SOURCE_NOT_READY,
                details={"reason": "session_not_idle", "phase": self.snapshot.phase.value},
            )
        identity_error = self._identify(rofl_path)
        if identity_error is not None:
            return self._fail(identity_error)
        rofl, platform_id, game_id = self._last_identity
        safety = self._live_game_error()
        if safety is not None:
            return self._machine.fail(safety)
        self._machine.start_launch()
        ctx = LaunchContext(
            rofl_path=rofl,
            install=install,
            platform_id=platform_id,
            game_id=game_id,
            lcu=self._lcu,
            processes=self._processes,
            allow_user_assisted=self._allow_user_assisted,
        )
        def _note(attempt: LaunchAttempt) -> None:
            self._machine.record_attempt(attempt.strategy)

        winner, attempts = run_launch_chain(ctx, self._strategies, on_attempt=_note)
        self._attempts = attempts
        if not winner.ok:
            return self._fail(
                winner.error
                or ReplayError(
                    ReplayErrorCode.LAUNCH_FAILED,
                    details={"reason": "all_strategies_failed"},
                )
            )
        if self._cancelled():
            return self._cancel_close()
        self._handle = winner.handle
        self._machine.note_launch(
            strategy=winner.strategy, owns_process=winner.owns_process, pid=winner.pid
        )
        self._machine.begin_connect()
        return self._connect_until_ready()

    def poll_health(self) -> ReplaySessionSnapshot:
        """Detect session loss. Never relaunches."""
        snap = self.snapshot
        if not snap.is_active:
            return snap
        if self._owned_process_gone() or self._api_process_gone(snap.api_process_id):
            return self._machine.session_lost()
        try:
            playback = self._require_transport().get_playback()
        except ReplayError as exc:
            if exc.code is ReplayErrorCode.REPLAY_API_TLS:
                return self._machine.fail(exc)
            if self._owned_process_gone() or self._api_process_gone(snap.api_process_id):
                return self._machine.session_lost()
            if not snap.owns_process and exc.code is ReplayErrorCode.REPLAY_API_UNAVAILABLE:
                return self._machine.session_lost()
            return snap
        self._machine.sync_playback(playback.to_playback_state())
        return self.snapshot

    def close(self) -> ReplaySessionSnapshot:
        """Stop monitoring and terminate only a RiftLens-owned pid."""
        snap = self.snapshot
        if snap.is_terminal:
            return snap
        if snap.phase is not ReplaySessionPhase.CLOSING:
            self._machine.begin_close()
        self._teardown_owned()
        return self._machine.finish_close()

    def _identify(self, rofl_path: str | Path) -> ReplayError | None:
        result = identify_rofl(Path(rofl_path))
        if result.error is not None:
            return result.error
        self._last_identity = (
            Path(rofl_path).expanduser(),
            result.identity.platform_id,
            result.identity.game_id,
        )
        return None

    def _live_game_error(self) -> ReplayError | None:
        if is_live_gameflow_phase(self._lcu.gameflow_phase()):
            return ReplayError(
                ReplayErrorCode.LIVE_GAME_IN_PROGRESS,
                details={"reason": "lcu_gameflow", "phase": self._lcu.gameflow_phase()},
            )
        lcd_up = False
        if self._live_probe is not None:
            lcd_up = self._live_probe.gamestats_reachable()
        elif isinstance(self._transport, ReplayApiTransport):
            lcd_up = self._transport.gamestats_reachable()
        if not lcd_up:
            return None
        playback_up = False
        if self._transport is not None:
            try:
                playback = self._transport.get_playback()
                playback_up = playback.length > 0
            except ReplayError as exc:
                if exc.code is ReplayErrorCode.REPLAY_API_TLS:
                    return exc
                playback_up = False
        if not playback_up:
            return ReplayError(
                ReplayErrorCode.LIVE_GAME_IN_PROGRESS,
                details={"reason": "live_client_without_replay_api"},
            )
        return None

    def _connect_until_ready(self) -> ReplaySessionSnapshot:
        transport = self._require_transport()
        deadline = self._clock.monotonic() + self._startup_timeout_s
        interval = MIN_POLL_INTERVAL_S
        last_error: ReplayError | None = None
        saw_playback = False
        while self._clock.monotonic() < deadline:
            if self._cancelled():
                return self._cancel_close()
            if self._owned_process_gone():
                return self._fail(
                    ReplayError(
                        ReplayErrorCode.LAUNCH_REJECTED,
                        details={"reason": "process_exited_before_ready"},
                    )
                )
            try:
                playback = transport.get_playback()
            except ReplayError as exc:
                last_error = exc
                if exc.code is ReplayErrorCode.PLAYBACK_UNREADABLE:
                    return self._fail(exc)
                # TLS verify can race while League is still binding 2999; keep polling.
                self._clock.sleep(interval)
                interval = min(MAX_POLL_INTERVAL_S, interval * 2)
                continue
            saw_playback = True
            if playback.length <= 0:
                last_error = ReplayError(
                    ReplayErrorCode.PLAYBACK_NOT_STARTED,
                    details={"reason": "length_zero"},
                )
                self._clock.sleep(interval)
                interval = min(MAX_POLL_INTERVAL_S, interval * 2)
                continue
            return self._verify_advancement(playback)
        if saw_playback:
            return self._fail(
                last_error
                or ReplayError(
                    ReplayErrorCode.PLAYBACK_NOT_STARTED,
                    details={"reason": "length_never_positive"},
                )
            )
        if last_error is not None and last_error.code is ReplayErrorCode.REPLAY_API_TLS:
            return self._fail(last_error)
        return self._fail(
            ReplayError(
                ReplayErrorCode.LAUNCH_TIMEOUT,
                details={
                    "reason": "replay_api_not_ready",
                    "last": None if last_error is None else last_error.code.value,
                },
            )
        )

    def _verify_advancement(self, first: ReplayPlayback) -> ReplaySessionSnapshot:
        transport = self._require_transport()
        current = first
        if current.paused:
            try:
                updated = transport.set_playback(paused=False)
            except ReplayError as exc:
                return self._fail(exc)
            if updated is not None:
                current = updated
        t0 = current.time
        self._clock.sleep(ADVANCE_SAMPLE_GAP_S)
        if self._cancelled():
            return self._cancel_close()
        try:
            second = transport.get_playback()
        except ReplayError as exc:
            return self._fail(exc)
        if second.length <= 0:
            return self._fail(
                ReplayError(
                    ReplayErrorCode.PLAYBACK_NOT_STARTED,
                    details={"reason": "length_zero_after_unpause"},
                )
            )
        if second.time <= t0:
            return self._fail(
                ReplayError(
                    ReplayErrorCode.PLAYBACK_NOT_ADVANCING,
                    details={"t0": t0, "t1": second.time},
                )
            )
        api_pid = None
        try:
            api_pid = transport.get_game_process_id()
        except ReplayError:
            api_pid = None
        state = second.to_playback_state()
        self._machine.mark_ready(state, api_process_id=api_pid)
        self._machine.sync_playback(state)
        return self.snapshot

    def _cancel_close(self) -> ReplaySessionSnapshot:
        if self.snapshot.phase not in {
            ReplaySessionPhase.CLOSING,
            ReplaySessionPhase.CLOSED,
            ReplaySessionPhase.FAILED,
        }:
            self._machine.begin_close()
        self._teardown_owned()
        if self.snapshot.phase is ReplaySessionPhase.CLOSING:
            self._machine.finish_close(cancelled=True)
        return self.snapshot

    def _fail(self, error: ReplayError) -> ReplaySessionSnapshot:
        self._teardown_owned()
        return self._machine.fail(error)

    def _teardown_owned(self) -> None:
        handle = self._handle
        snap = self.snapshot
        if handle is None or not snap.owns_process:
            return
        handle.terminate()

    def _owned_process_gone(self) -> bool:
        handle = self._handle
        snap = self.snapshot
        if not snap.owns_process or handle is None:
            return False
        return handle.poll() is not None

    def _api_process_gone(self, api_pid: int | None) -> bool:
        if api_pid is None:
            return False
        return not self._processes.pid_is_running(api_pid)

    def _cancelled(self) -> bool:
        return self._cancel_event is not None and self._cancel_event.is_set()

    def _require_transport(self) -> PlaybackTransport:
        if self._transport is None:
            raise ReplayError(
                ReplayErrorCode.REPLAY_API_UNAVAILABLE,
                details={"reason": "transport_missing"},
            )
        return self._transport


def default_api_transport(
    *,
    origin: str | None = None,
    ca_file: str | None = None,
    timeout_s: float = 2.0,
    connect_timeout_s: float = 0.5,
) -> ReplayApiTransport:
    """Build R.4 clients for production open(). Assumes loopback Replay API."""
    if origin is not None:
        replay = ReplayApiClient(
            origin,
            ca_file=ca_file,
            timeout_s=timeout_s,
            connect_timeout_s=connect_timeout_s,
            max_retries=STARTUP_HTTP_RETRIES,
        )
        live = LiveClientDataClient(
            origin,
            ca_file=ca_file,
            timeout_s=timeout_s,
            connect_timeout_s=connect_timeout_s,
            max_retries=STARTUP_HTTP_RETRIES,
        )
    else:
        replay = ReplayApiClient(
            ca_file=ca_file,
            timeout_s=timeout_s,
            connect_timeout_s=connect_timeout_s,
            max_retries=STARTUP_HTTP_RETRIES,
        )
        live = LiveClientDataClient(
            ca_file=ca_file,
            timeout_s=timeout_s,
            connect_timeout_s=connect_timeout_s,
            max_retries=STARTUP_HTTP_RETRIES,
        )
    return ReplayApiTransport(replay=replay, live=live)
