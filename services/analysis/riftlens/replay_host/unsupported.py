from __future__ import annotations

import threading
from collections.abc import Sequence

from riftlens.domain.capture import (
    DEFAULT_CAPTURE_POLL_S,
    DEFAULT_CAPTURE_TIMEOUT_S,
    DEFAULT_MAX_ARTIFACTS,
    CaptureMode,
    CaptureResult,
    CaptureStatus,
)
from riftlens.domain.clock_map import ClockMap
from riftlens.domain.gameplay_source import SourceCapability
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.domain.sync_map import SEEK_LEAD_IN_MS
from riftlens.replay_host.clock.anchor_matcher import KillEvent
from riftlens.replay_host.clock.calibrator import CalibrationResult, calibrate_replay_clock
from riftlens.replay_host.port import CaptureProgressSink, ControlOutcome, EnvironmentCheck
from riftlens.replay_host.seek import SeekOutcome
from riftlens.replay_host.session import ReplaySessionPhase, ReplaySessionSnapshot


def _unsupported() -> ReplayError:
    return ReplayError(
        ReplayErrorCode.PLATFORM_UNSUPPORTED,
        details={
            "reason": "native_replay_windows_or_macos_only",
            "suggested_action": "attach_video",
        },
    )


class UnsupportedReplayHost:
    """Non-Windows/non-macOS ReplayHostPort. Never launches League."""

    def platform_supported(self) -> bool:
        return False

    def platform_capabilities(self) -> frozenset[SourceCapability]:
        return frozenset()

    def check_environment(self) -> EnvironmentCheck:
        error = _unsupported()
        return EnvironmentCheck(
            supported=False,
            install_found=False,
            replay_api_documented=False,
            live_game=False,
            error=error,
        )

    def open_session(self, rofl_path: str) -> ReplaySessionSnapshot:
        del rofl_path
        return ReplaySessionSnapshot(phase=ReplaySessionPhase.FAILED, error=_unsupported())

    def get_state(self) -> ReplaySessionSnapshot:
        return ReplaySessionSnapshot(phase=ReplaySessionPhase.IDLE)

    def poll_health(self) -> ReplaySessionSnapshot:
        return self.get_state()

    def close_session(self) -> ReplaySessionSnapshot:
        return ReplaySessionSnapshot(phase=ReplaySessionPhase.CLOSED)

    def reveal(
        self,
        game_t_ms: int,
        clock: ClockMap,
        *,
        lead_in_ms: int = SEEK_LEAD_IN_MS,
        match_duration_ms: int | None = None,
    ) -> SeekOutcome:
        del clock, lead_in_ms, match_duration_ms
        return SeekOutcome(
            ok=False,
            target_game_ms=int(game_t_ms),
            target_source_ms=None,
            landed_source_ms=None,
            attempts=0,
            resumed=False,
            playback=None,
            error=_unsupported(),
        )

    def calibrate(
        self,
        *,
        match_duration_ms: int | None,
        riot_kills: Sequence[KillEvent] = (),
    ) -> CalibrationResult:
        del riot_kills
        result = calibrate_replay_clock(
            playback_length_ms=0,
            match_duration_ms=match_duration_ms,
            lcd_available=False,
        )
        return CalibrationResult(
            clock=result.clock,
            method=result.method,
            confidence=result.confidence,
            offset_ms=result.offset_ms,
            anchor_count=result.anchor_count,
            residual_ms=result.residual_ms,
            stdev_ms=result.stdev_ms,
            duration_delta_ms=result.duration_delta_ms,
            gamestats_relation=result.gamestats_relation,
            lcd_available=False,
            error=_unsupported(),
            match=result.match,
            reason="platform_unsupported",
        )

    def pause(self) -> ControlOutcome:
        return ControlOutcome(ok=False, error=_unsupported())

    def resume(self) -> ControlOutcome:
        return ControlOutcome(ok=False, error=_unsupported())

    def set_speed(self, speed: float) -> ControlOutcome:
        del speed
        return ControlOutcome(ok=False, error=_unsupported())

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
        del start_game_ms, end_game_ms, clock, output_dir, mode, fps, max_artifacts
        del timeout_s, poll_s, cancel, on_progress
        return CaptureResult(
            ok=False,
            capture_id=capture_id,
            status=CaptureStatus.FAILED,
            error=_unsupported(),
        )
