from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

from riftlens.domain.clock_map import ClockMap
from riftlens.domain.gameplay_source import PlaybackState
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.domain.sync_map import SEEK_LEAD_IN_MS
from riftlens.replay_host.api.models import ReplayPlayback
from riftlens.replay_host.session import ReplaySessionMachine, ReplaySessionPhase
from riftlens.replay_host.timing import SleepClock, WallClock

LANDING_TOLERANCE_MS = 500
REAL_SEEK_TOLERANCE_MS = 1_000
SEEK_POLL_TIMEOUT_S = 5.0
SEEK_POLL_INTERVAL_S = 0.25
RESUME_ADVANCE_WAIT_S = 1.5
MAX_SEEK_ATTEMPTS = 2


class SeekTransport(Protocol):
    """Playback GET/POST used by verified seek. Matches R.4/R.5 clients."""

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


@dataclass(frozen=True)
class SeekOutcome:
    """Result of one verified reveal seek. Play is never implied on failure."""

    ok: bool
    target_game_ms: int
    target_source_ms: int | None
    landed_source_ms: int | None
    attempts: int
    resumed: bool
    playback: PlaybackState | None
    error: ReplayError | None


def clamp_game_ms(
    game_t_ms: int,
    *,
    lead_in_ms: int,
    match_duration_ms: int | None,
) -> int:
    """Apply lead-in and clamp to ``[0, match_duration)``. Clock holes stay unmapped."""
    target = max(0, int(game_t_ms) - max(0, int(lead_in_ms)))
    if match_duration_ms is None:
        return target
    upper = max(0, int(match_duration_ms) - 1)
    return min(target, upper)


def verified_seek(
    transport: SeekTransport,
    clock: ClockMap,
    game_t_ms: int,
    *,
    lead_in_ms: int = SEEK_LEAD_IN_MS,
    then_play: bool = True,
    session_ready: bool = True,
    machine: ReplaySessionMachine | None = None,
    sleep_clock: SleepClock | None = None,
    cancel_event: threading.Event | None = None,
    landing_tolerance_ms: int = LANDING_TOLERANCE_MS,
    match_duration_ms: int | None = None,
    poll_timeout_s: float = SEEK_POLL_TIMEOUT_S,
) -> SeekOutcome:
    """Pause, seek source time, verify landing, optionally resume. One retry maximum."""
    waiter = sleep_clock if sleep_clock is not None else WallClock()
    if not session_ready or (machine is not None and not machine.snapshot.is_active):
        phase = None if machine is None else machine.snapshot.phase.value
        return _fail(
            ReplayError(
                ReplayErrorCode.SOURCE_NOT_READY,
                details={"reason": "session_not_ready", "phase": phase},
            ),
            game_t_ms,
            None,
            attempts=0,
        )

    target_game = clamp_game_ms(
        game_t_ms,
        lead_in_ms=lead_in_ms,
        match_duration_ms=match_duration_ms,
    )
    target_source = clock.game_to_source(target_game)
    if target_source is None:
        code = (
            ReplayErrorCode.CLOCK_UNMAPPED
            if clock.mode.value == "UNMAPPED"
            else ReplayErrorCode.CLOCK_OUT_OF_BOUNDS
        )
        return _fail(
            ReplayError(code, details={"target_game_ms": target_game}),
            target_game,
            None,
            attempts=0,
        )

    try:
        transport.set_playback(paused=True, readback=True)
    except ReplayError as exc:
        return _fail(exc, target_game, target_source, attempts=0)
    _sync(machine, transport, force_seeking=False)

    last_error: ReplayError | None = None
    landed: ReplayPlayback | None = None
    for attempt in range(1, MAX_SEEK_ATTEMPTS + 1):
        if _cancelled(cancel_event):
            return _fail(
                ReplayError(ReplayErrorCode.SEEK_FAILED, details={"reason": "cancelled"}),
                target_game,
                target_source,
                attempts=attempt - 1,
            )
        try:
            transport.set_playback(time=target_source / 1000.0, paused=True, readback=False)
        except ReplayError as exc:
            return _fail(exc, target_game, target_source, attempts=attempt)
        _sync(machine, None, force_seeking=True)
        landed, last_error = _poll_landing(
            transport,
            target_source_ms=target_source,
            tolerance_ms=landing_tolerance_ms,
            timeout_s=poll_timeout_s,
            waiter=waiter,
            cancel_event=cancel_event,
            machine=machine,
        )
        if landed is not None:
            break
    if landed is None:
        return _fail(
            last_error
            or ReplayError(ReplayErrorCode.SEEK_FAILED, details={"reason": "seek_timeout"}),
            target_game,
            target_source,
            attempts=MAX_SEEK_ATTEMPTS,
        )

    state = landed.to_playback_state().bind_clock(clock)
    landed_ms = state.t_source_ms
    if not then_play:
        _sync(machine, None, playback=landed)
        return SeekOutcome(
            ok=True,
            target_game_ms=target_game,
            target_source_ms=target_source,
            landed_source_ms=landed_ms,
            attempts=attempt,
            resumed=False,
            playback=state,
            error=None,
        )

    try:
        transport.set_playback(paused=False, speed=1.0, readback=True)
    except ReplayError as exc:
        return _fail(exc, target_game, target_source, attempts=attempt, landed=landed_ms)
    waiter.sleep(RESUME_ADVANCE_WAIT_S)
    try:
        after = transport.get_playback()
    except ReplayError as exc:
        return _fail(exc, target_game, target_source, attempts=attempt, landed=landed_ms)
    _sync(machine, None, playback=after)
    if after.paused or after.time * 1000.0 <= landed_ms:
        return _fail(
            ReplayError(
                ReplayErrorCode.PLAYBACK_NOT_ADVANCING,
                details={"t0": landed_ms, "t1": int(round(after.time * 1000.0))},
            ),
            target_game,
            target_source,
            attempts=attempt,
            landed=landed_ms,
        )
    final = after.to_playback_state().bind_clock(clock)
    return SeekOutcome(
        ok=True,
        target_game_ms=target_game,
        target_source_ms=target_source,
        landed_source_ms=landed_ms,
        attempts=attempt,
        resumed=True,
        playback=final,
        error=None,
    )


def _poll_landing(
    transport: SeekTransport,
    *,
    target_source_ms: int,
    tolerance_ms: int,
    timeout_s: float,
    waiter: SleepClock,
    cancel_event: threading.Event | None,
    machine: ReplaySessionMachine | None,
) -> tuple[ReplayPlayback | None, ReplayError | None]:
    deadline = waiter.monotonic() + timeout_s
    last_error: ReplayError | None = None
    last_pb: ReplayPlayback | None = None
    while waiter.monotonic() < deadline:
        if _cancelled(cancel_event):
            return None, ReplayError(ReplayErrorCode.SEEK_FAILED, details={"reason": "cancelled"})
        try:
            playback = transport.get_playback()
        except ReplayError as exc:
            last_error = exc
            waiter.sleep(SEEK_POLL_INTERVAL_S)
            continue
        last_pb = playback
        _sync(machine, None, playback=playback)
        landed_ms = int(round(playback.time * 1000.0))
        if playback.seeking:
            waiter.sleep(SEEK_POLL_INTERVAL_S)
            continue
        if abs(landed_ms - target_source_ms) <= tolerance_ms:
            return playback, None
        return None, ReplayError(
            ReplayErrorCode.SEEK_TOLERANCE_EXCEEDED,
            details={
                "target_source_ms": target_source_ms,
                "landed_source_ms": landed_ms,
                "tolerance_ms": tolerance_ms,
            },
        )
    if last_pb is not None and last_pb.seeking:
        return None, ReplayError(
            ReplayErrorCode.SEEK_FAILED,
            details={"reason": "seeking_stuck"},
        )
    return None, last_error or ReplayError(
        ReplayErrorCode.SEEK_FAILED, details={"reason": "seek_timeout"}
    )


def _sync(
    machine: ReplaySessionMachine | None,
    transport: SeekTransport | None,
    *,
    force_seeking: bool = False,
    playback: ReplayPlayback | None = None,
) -> None:
    if machine is None:
        return
    pb = playback
    if pb is None and transport is not None:
        try:
            pb = transport.get_playback()
        except ReplayError:
            return
    if pb is None and force_seeking:
        dummy = PlaybackState(t_source_ms=0, length_ms=1, paused=True, seeking=True)
        if machine.snapshot.phase is not ReplaySessionPhase.SEEKING:
            try:
                machine.sync_playback(dummy)
            except Exception:
                return
        return
    if pb is None:
        return
    try:
        machine.sync_playback(pb.to_playback_state())
    except Exception:
        return


def _cancelled(event: threading.Event | None) -> bool:
    return event is not None and event.is_set()


def _fail(
    error: ReplayError,
    target_game_ms: int,
    target_source_ms: int | None,
    *,
    attempts: int,
    landed: int | None = None,
) -> SeekOutcome:
    return SeekOutcome(
        ok=False,
        target_game_ms=target_game_ms,
        target_source_ms=target_source_ms,
        landed_source_ms=landed,
        attempts=attempts,
        resumed=False,
        playback=None,
        error=error,
    )

