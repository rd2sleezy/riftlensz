"""Coarse session-oriented ReplayHostPort. No Windows APIs live here."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from riftlens.domain.clock_map import ClockMap
from riftlens.domain.gameplay_source import PlaybackState, SourceCapability
from riftlens.domain.replay_errors import ReplayError
from riftlens.domain.sync_map import SEEK_LEAD_IN_MS
from riftlens.replay_host.clock.anchor_matcher import KillEvent
from riftlens.replay_host.clock.calibrator import CalibrationResult
from riftlens.replay_host.seek import SeekOutcome
from riftlens.replay_host.session import ReplaySessionSnapshot


@dataclass(frozen=True)
class EnvironmentCheck:
    """Install + Replay API capability snapshot. Does not imply a live session."""

    supported: bool
    install_found: bool
    replay_api_documented: bool
    live_game: bool
    error: ReplayError | None = None
    warnings: tuple[ReplayError, ...] = ()


@dataclass(frozen=True)
class ControlOutcome:
    """Pause/resume/speed/capture result. Errors stay typed."""

    ok: bool
    playback: PlaybackState | None = None
    error: ReplayError | None = None


class ReplayHostPort(Protocol):
    """Session-oriented native-replay seam. Implementations must not leak HTTP calls."""

    def platform_supported(self) -> bool:
        """Return True when this host can launch a native replay on this OS."""

    def platform_capabilities(self) -> frozenset[SourceCapability]:
        """Return runtime capabilities, or empty when native replay is unavailable."""

    def check_environment(self) -> EnvironmentCheck:
        """Locate League and probe Replay API docs. Does not launch a replay."""

    def open_session(self, rofl_path: str) -> ReplaySessionSnapshot:
        """Launch/connect until verified READY, or return a typed failed snapshot."""

    def get_state(self) -> ReplaySessionSnapshot:
        """Return the in-memory session snapshot. Never reads persisted R.7 audit rows."""

    def poll_health(self) -> ReplaySessionSnapshot:
        """Detect session loss. Does not auto-relaunch."""

    def close_session(self) -> ReplaySessionSnapshot:
        """Tear down the live session. Persisted source/ClockMap are untouched."""

    def reveal(
        self,
        game_t_ms: int,
        clock: ClockMap,
        *,
        lead_in_ms: int = SEEK_LEAD_IN_MS,
        match_duration_ms: int | None = None,
    ) -> SeekOutcome:
        """Verified seek in source time via R.6. Does not invent timestamps."""

    def calibrate(
        self,
        *,
        match_duration_ms: int | None,
        riot_kills: Sequence[KillEvent] = (),
    ) -> CalibrationResult:
        """Run the existing R.6 ladder against the live session. No new algorithm."""

    def pause(self) -> ControlOutcome:
        """Pause playback when a session is active."""

    def resume(self) -> ControlOutcome:
        """Resume playback when a session is active."""

    def set_speed(self, speed: float) -> ControlOutcome:
        """Set playback speed when a session is active."""

    def capture_interval(self, start_game_ms: int, end_game_ms: int) -> ControlOutcome:
        """Reserved for R.10. Must return a typed unsupported result until then."""
