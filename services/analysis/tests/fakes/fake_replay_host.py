from __future__ import annotations

import threading
from collections.abc import Sequence
from pathlib import Path

from riftlens.domain.capture import (
    DEFAULT_CAPTURE_POLL_S,
    DEFAULT_CAPTURE_TIMEOUT_S,
    DEFAULT_MAX_ARTIFACTS,
    CaptureMode,
    CaptureResult,
    CaptureStatus,
)
from riftlens.domain.clock_map import ClockMap
from riftlens.domain.gameplay_source import (
    NATIVE_REPLAY_CAPABILITIES,
    PlaybackState,
    SourceCapability,
)
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.domain.sync_map import SEEK_LEAD_IN_MS
from riftlens.replay_host.capture.recording import RecordingClient, run_capture
from riftlens.replay_host.clock.anchor_matcher import KillEvent
from riftlens.replay_host.clock.calibrator import CalibrationResult, calibrate_replay_clock
from riftlens.replay_host.port import CaptureProgressSink, ControlOutcome, EnvironmentCheck
from riftlens.replay_host.seek import SeekOutcome, clamp_game_ms, verified_seek
from riftlens.replay_host.session import ReplaySessionPhase, ReplaySessionSnapshot
from riftlens.replay_host.timing import SleepClock


class FakeReplayHost:
    """Deterministic ReplayHostPort for R.8 service tests."""

    def __init__(
        self,
        *,
        supported: bool = True,
        environment: EnvironmentCheck | None = None,
        open_error: ReplayError | None = None,
        session_lost: bool = False,
        calibrate_result: CalibrationResult | None = None,
        seek_transport: object | None = None,
        sleep_clock: SleepClock | None = None,
        auto_ready: bool = True,
        reveal_error: ReplayError | None = None,
        recording_client: RecordingClient | None = None,
    ) -> None:
        self.supported = supported
        self.environment = environment
        self.open_error = open_error
        self.session_lost = session_lost
        self.calibrate_result = calibrate_result
        self.seek_transport = seek_transport
        self.sleep_clock = sleep_clock
        self.auto_ready = auto_ready
        self.reveal_error = reveal_error
        self.recording_client = recording_client
        self.open_count = 0
        self.calibrate_count = 0
        self.reveal_count = 0
        self.close_count = 0
        self.capture_count = 0
        self._state = ReplaySessionSnapshot(phase=ReplaySessionPhase.IDLE)

    def platform_supported(self) -> bool:
        return self.supported

    def platform_capabilities(self) -> frozenset[SourceCapability]:
        return NATIVE_REPLAY_CAPABILITIES if self.supported else frozenset()

    def check_environment(self) -> EnvironmentCheck:
        if self.environment is not None:
            return self.environment
        if not self.supported:
            error = ReplayError(ReplayErrorCode.PLATFORM_UNSUPPORTED)
            return EnvironmentCheck(
                supported=False,
                install_found=False,
                replay_api_documented=False,
                live_game=False,
                error=error,
            )
        return EnvironmentCheck(
            supported=True,
            install_found=True,
            replay_api_documented=True,
            live_game=False,
        )

    def open_session(self, rofl_path: str) -> ReplaySessionSnapshot:
        del rofl_path
        self.open_count += 1
        if self.open_error is not None:
            self._state = ReplaySessionSnapshot(
                phase=ReplaySessionPhase.FAILED, error=self.open_error
            )
            return self._state
        if not self.auto_ready:
            self._state = ReplaySessionSnapshot(phase=ReplaySessionPhase.CONNECTING)
            return self._state
        playback = PlaybackState(
            t_source_ms=2000, length_ms=1_800_000, paused=False, seeking=False
        )
        self._state = ReplaySessionSnapshot(
            phase=ReplaySessionPhase.READY,
            playback=playback,
            reached_ready=True,
        )
        return self._state

    def get_state(self) -> ReplaySessionSnapshot:
        return self._state

    def poll_health(self) -> ReplaySessionSnapshot:
        if self.session_lost and self._state.is_active:
            error = ReplayError(ReplayErrorCode.SESSION_LOST)
            self._state = ReplaySessionSnapshot(phase=ReplaySessionPhase.FAILED, error=error)
        return self._state

    def close_session(self) -> ReplaySessionSnapshot:
        self.close_count += 1
        self._state = ReplaySessionSnapshot(phase=ReplaySessionPhase.CLOSED)
        return self._state

    def reveal(
        self,
        game_t_ms: int,
        clock: ClockMap,
        *,
        lead_in_ms: int = SEEK_LEAD_IN_MS,
        match_duration_ms: int | None = None,
    ) -> SeekOutcome:
        self.reveal_count += 1
        if self.reveal_error is not None:
            return SeekOutcome(
                ok=False,
                target_game_ms=int(game_t_ms),
                target_source_ms=None,
                landed_source_ms=None,
                attempts=0,
                resumed=False,
                playback=None,
                error=self.reveal_error,
            )
        health = self.poll_health()
        if health.error is not None and health.error.code is ReplayErrorCode.SESSION_LOST:
            return SeekOutcome(
                ok=False,
                target_game_ms=int(game_t_ms),
                target_source_ms=None,
                landed_source_ms=None,
                attempts=0,
                resumed=False,
                playback=None,
                error=health.error,
            )
        if not health.is_active:
            return SeekOutcome(
                ok=False,
                target_game_ms=int(game_t_ms),
                target_source_ms=None,
                landed_source_ms=None,
                attempts=0,
                resumed=False,
                playback=None,
                error=ReplayError(
                    ReplayErrorCode.SOURCE_NOT_READY,
                    details={"phase": health.phase.value},
                ),
            )
        if self.seek_transport is not None:
            return verified_seek(
                self.seek_transport,  # type: ignore[arg-type]
                clock,
                game_t_ms,
                lead_in_ms=lead_in_ms,
                match_duration_ms=match_duration_ms,
                sleep_clock=self.sleep_clock,
            )
        target_game = clamp_game_ms(
            game_t_ms, lead_in_ms=lead_in_ms, match_duration_ms=match_duration_ms
        )
        target_source = clock.game_to_source(target_game)
        if target_source is None:
            return SeekOutcome(
                ok=False,
                target_game_ms=target_game,
                target_source_ms=None,
                landed_source_ms=None,
                attempts=0,
                resumed=False,
                playback=None,
                error=ReplayError(ReplayErrorCode.CLOCK_UNMAPPED),
            )
        playback = PlaybackState(
            t_source_ms=target_source,
            length_ms=clock.source_end_ms,
            paused=False,
            seeking=False,
        )
        return SeekOutcome(
            ok=True,
            target_game_ms=target_game,
            target_source_ms=target_source,
            landed_source_ms=target_source,
            attempts=1,
            resumed=True,
            playback=playback,
            error=None,
        )

    def calibrate(
        self,
        *,
        match_duration_ms: int | None,
        riot_kills: Sequence[KillEvent] = (),
    ) -> CalibrationResult:
        del riot_kills
        self.calibrate_count += 1
        if self.calibrate_result is not None:
            return self.calibrate_result
        return calibrate_replay_clock(
            playback_length_ms=1_800_000,
            match_duration_ms=match_duration_ms,
            lcd_available=False,
        )

    def pause(self) -> ControlOutcome:
        return ControlOutcome(ok=self._state.is_active)

    def resume(self) -> ControlOutcome:
        return ControlOutcome(ok=self._state.is_active)

    def set_speed(self, speed: float) -> ControlOutcome:
        del speed
        return ControlOutcome(ok=self._state.is_active)

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
        """Run the real R.10 engine when a recording client was injected, else refuse."""
        self.capture_count += 1
        if self.recording_client is None:
            return CaptureResult(
                ok=False,
                capture_id=capture_id,
                status=CaptureStatus.FAILED,
                error=ReplayError(ReplayErrorCode.CAPABILITY_UNSUPPORTED),
            )
        health = self.poll_health()
        if not health.is_active:
            return CaptureResult(
                ok=False,
                capture_id=capture_id,
                status=CaptureStatus.FAILED,
                error=ReplayError(
                    ReplayErrorCode.SOURCE_NOT_READY, details={"phase": health.phase.value}
                ),
            )
        return run_capture(
            client=self.recording_client,
            clock=clock,
            capture_id=capture_id,
            start_game_ms=start_game_ms,
            end_game_ms=end_game_ms,
            directory=Path(output_dir),
            mode=mode,
            fps=fps,
            max_artifacts=max_artifacts,
            timeout_s=timeout_s,
            poll_s=poll_s,
            cancel=cancel,
            on_progress=on_progress,
            sleep_clock=self.sleep_clock,
        )

    def reset_live_session(self) -> None:
        """Simulate application restart: persisted data remains, live session does not."""
        self._state = ReplaySessionSnapshot(phase=ReplaySessionPhase.IDLE)

    def force_phase(self, phase: ReplaySessionPhase, *, reached_ready: bool = False) -> None:
        """Test helper: set the in-memory session without launching."""
        playback = None
        active = phase in {
            ReplaySessionPhase.READY,
            ReplaySessionPhase.PLAYING,
            ReplaySessionPhase.PAUSED,
            ReplaySessionPhase.SEEKING,
        }
        if active:
            playback = PlaybackState(
                t_source_ms=2000,
                length_ms=1_800_000,
                paused=phase is ReplaySessionPhase.PAUSED,
                seeking=phase is ReplaySessionPhase.SEEKING,
            )
        self._state = ReplaySessionSnapshot(
            phase=phase,
            playback=playback,
            reached_ready=reached_ready or active,
        )
