from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from riftlens.domain.gameplay_source import PlaybackState
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode


class ReplaySessionPhase(StrEnum):
    """§4.2 lifecycle phases. READY is never inferred from a process existing."""

    IDLE = "IDLE"
    LAUNCHING = "LAUNCHING"
    CONNECTING = "CONNECTING"
    READY = "READY"
    PLAYING = "PLAYING"
    PAUSED = "PAUSED"
    SEEKING = "SEEKING"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


_ACTIVE = frozenset(
    {
        ReplaySessionPhase.READY,
        ReplaySessionPhase.PLAYING,
        ReplaySessionPhase.PAUSED,
        ReplaySessionPhase.SEEKING,
    }
)

_ALLOWED: dict[ReplaySessionPhase, frozenset[ReplaySessionPhase]] = {
    ReplaySessionPhase.IDLE: frozenset(
        {ReplaySessionPhase.LAUNCHING, ReplaySessionPhase.FAILED}
    ),
    ReplaySessionPhase.LAUNCHING: frozenset(
        {ReplaySessionPhase.CONNECTING, ReplaySessionPhase.CLOSING, ReplaySessionPhase.FAILED}
    ),
    ReplaySessionPhase.CONNECTING: frozenset(
        {ReplaySessionPhase.READY, ReplaySessionPhase.CLOSING, ReplaySessionPhase.FAILED}
    ),
    ReplaySessionPhase.READY: frozenset(
        {
            ReplaySessionPhase.PLAYING,
            ReplaySessionPhase.PAUSED,
            ReplaySessionPhase.SEEKING,
            ReplaySessionPhase.CLOSING,
            ReplaySessionPhase.FAILED,
        }
    ),
    ReplaySessionPhase.PLAYING: frozenset(
        {
            ReplaySessionPhase.PAUSED,
            ReplaySessionPhase.SEEKING,
            ReplaySessionPhase.READY,
            ReplaySessionPhase.CLOSING,
            ReplaySessionPhase.FAILED,
        }
    ),
    ReplaySessionPhase.PAUSED: frozenset(
        {
            ReplaySessionPhase.PLAYING,
            ReplaySessionPhase.SEEKING,
            ReplaySessionPhase.READY,
            ReplaySessionPhase.CLOSING,
            ReplaySessionPhase.FAILED,
        }
    ),
    ReplaySessionPhase.SEEKING: frozenset(
        {
            ReplaySessionPhase.PLAYING,
            ReplaySessionPhase.PAUSED,
            ReplaySessionPhase.READY,
            ReplaySessionPhase.CLOSING,
            ReplaySessionPhase.FAILED,
        }
    ),
    ReplaySessionPhase.CLOSING: frozenset({ReplaySessionPhase.CLOSED, ReplaySessionPhase.FAILED}),
    ReplaySessionPhase.CLOSED: frozenset(),
    ReplaySessionPhase.FAILED: frozenset(),
}


class IllegalSessionTransition(ValueError):
    """Programming error: caller requested a transition the machine does not allow."""

    def __init__(self, source: ReplaySessionPhase, dest: ReplaySessionPhase) -> None:
        self.source = source
        self.dest = dest
        super().__init__(f"illegal replay session transition {source.value} -> {dest.value}")


@dataclass(frozen=True)
class ReplaySessionSnapshot:
    """Immutable view of session lifecycle. ``relaunch_count`` stays 0 after session loss."""

    phase: ReplaySessionPhase
    error: ReplayError | None = None
    attempted_strategies: tuple[str, ...] = ()
    winning_strategy: str | None = None
    owns_process: bool = False
    pid: int | None = None
    api_process_id: int | None = None
    playback: PlaybackState | None = None
    reached_ready: bool = False
    relaunch_count: int = 0
    cancelled: bool = False

    @property
    def is_active(self) -> bool:
        """Return True after verified READY, including playback substates."""
        return self.phase in _ACTIVE

    @property
    def is_terminal(self) -> bool:
        """Return True when the session cannot continue without a new supervisor."""
        return self.phase in {ReplaySessionPhase.CLOSED, ReplaySessionPhase.FAILED}


class ReplaySessionMachine:
    """Deterministic §4.2 state machine. No I/O, no clock, no process handles."""

    def __init__(self) -> None:
        self._snap = ReplaySessionSnapshot(phase=ReplaySessionPhase.IDLE)

    @property
    def snapshot(self) -> ReplaySessionSnapshot:
        """Return the current immutable snapshot."""
        return self._snap

    def record_attempt(self, strategy: str) -> ReplaySessionSnapshot:
        """Append a launch strategy name. Assumes ``strategy`` is a known chain member."""
        attempted = (*self._snap.attempted_strategies, strategy)
        self._snap = replace(self._snap, attempted_strategies=attempted)
        return self._snap

    def note_launch(
        self,
        *,
        strategy: str,
        owns_process: bool,
        pid: int | None,
    ) -> ReplaySessionSnapshot:
        """Record which strategy produced a process or wait-for-user outcome."""
        self._snap = replace(
            self._snap,
            winning_strategy=strategy,
            owns_process=owns_process,
            pid=pid,
        )
        return self._snap

    def start_launch(self) -> ReplaySessionSnapshot:
        """IDLE -> LAUNCHING."""
        return self._go(ReplaySessionPhase.LAUNCHING)

    def begin_connect(self) -> ReplaySessionSnapshot:
        """LAUNCHING -> CONNECTING after a strategy accepted responsibility."""
        return self._go(ReplaySessionPhase.CONNECTING)

    def mark_ready(self, playback: PlaybackState, *, api_process_id: int | None = None) -> (
        ReplaySessionSnapshot
    ):
        """CONNECTING -> READY only after Replay API verification succeeded."""
        self._go(ReplaySessionPhase.READY)
        self._snap = replace(
            self._snap,
            playback=playback,
            api_process_id=api_process_id,
            reached_ready=True,
        )
        return self._snap

    def sync_playback(self, playback: PlaybackState) -> ReplaySessionSnapshot:
        """Move among READY/PLAYING/PAUSED/SEEKING from a verified playback snapshot."""
        if playback.seeking:
            dest = ReplaySessionPhase.SEEKING
        elif playback.paused:
            dest = ReplaySessionPhase.PAUSED
        else:
            dest = ReplaySessionPhase.PLAYING
        if self._snap.phase is dest:
            self._snap = replace(self._snap, playback=playback)
            return self._snap
        self._go(dest)
        self._snap = replace(self._snap, playback=playback)
        return self._snap

    def begin_close(self) -> ReplaySessionSnapshot:
        """Enter CLOSING from a non-terminal phase."""
        return self._go(ReplaySessionPhase.CLOSING)

    def finish_close(self, *, cancelled: bool = False) -> ReplaySessionSnapshot:
        """CLOSING -> CLOSED. Does not relaunch."""
        self._go(ReplaySessionPhase.CLOSED)
        self._snap = replace(self._snap, cancelled=cancelled)
        return self._snap

    def fail(self, error: ReplayError, *, cancelled: bool = False) -> ReplaySessionSnapshot:
        """Transition to FAILED from any non-terminal phase. Never increments relaunch_count."""
        if self._snap.phase is ReplaySessionPhase.FAILED:
            self._snap = replace(
                self._snap, error=error, cancelled=cancelled or self._snap.cancelled
            )
            return self._snap
        self._go(ReplaySessionPhase.FAILED)
        self._snap = replace(self._snap, error=error, cancelled=cancelled)
        return self._snap

    def session_lost(self) -> ReplaySessionSnapshot:
        """Mark SESSION_LOST without relaunching. Assumes the replay window is gone."""
        return self.fail(ReplayError(ReplayErrorCode.SESSION_LOST))

    def _go(self, dest: ReplaySessionPhase) -> ReplaySessionSnapshot:
        source = self._snap.phase
        if dest not in _ALLOWED[source]:
            raise IllegalSessionTransition(source, dest)
        self._snap = replace(self._snap, phase=dest)
        return self._snap
