"""Coarse session-oriented ReplayHostPort. No Windows APIs live here."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from riftlens.domain.capture import (
    DEFAULT_CAPTURE_POLL_S,
    DEFAULT_CAPTURE_TIMEOUT_S,
    DEFAULT_MAX_ARTIFACTS,
    CaptureMode,
    CaptureProgress,
    CaptureResult,
)
from riftlens.domain.clock_map import ClockMap
from riftlens.domain.gameplay_source import PlaybackState, SourceCapability
from riftlens.domain.replay_errors import ReplayError
from riftlens.domain.sync_map import SEEK_LEAD_IN_MS
from riftlens.replay_host.clock.anchor_matcher import KillEvent
from riftlens.replay_host.clock.calibrator import CalibrationResult
from riftlens.replay_host.seek import SeekOutcome
from riftlens.replay_host.session import ReplaySessionSnapshot

CaptureProgressSink = Callable[[CaptureProgress], None]


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

    def capture_interval(
        self,
        start_game_ms: int,
        end_game_ms: int,
        clock: ClockMap,
        *,
        output_dir: str,
        capture_id: str,
        mode: CaptureMode = CaptureMode.CLIP,
        fps: float | None = None,
        max_artifacts: int = DEFAULT_MAX_ARTIFACTS,
        timeout_s: float = DEFAULT_CAPTURE_TIMEOUT_S,
        poll_s: float = DEFAULT_CAPTURE_POLL_S,
        cancel: threading.Event | None = None,
        on_progress: CaptureProgressSink | None = None,
    ) -> CaptureResult:
        """Record ``[start, end)`` game ms into ``output_dir`` (R.10). Blocks; never persists."""
