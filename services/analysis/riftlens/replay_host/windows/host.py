from __future__ import annotations

from collections.abc import Callable, Sequence

from riftlens.domain.clock_map import ClockConfidence, ClockMap, ClockMode
from riftlens.domain.gameplay_source import NATIVE_REPLAY_CAPABILITIES, SourceCapability
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.domain.sync_map import SEEK_LEAD_IN_MS
from riftlens.replay_host.api.live_client import LiveClientDataClient
from riftlens.replay_host.api.models import EventData, PlayerListEntry
from riftlens.replay_host.clock.anchor_matcher import KillEvent
from riftlens.replay_host.clock.calibrator import (
    CalibrationResult,
    calibrate_replay_clock,
    collect_lcd_kills,
    merge_eventdata,
    pause_crosscheck_gamestats,
)
from riftlens.replay_host.lcu.port import LcuReplayPort, NullLcuReplayPort, is_live_gameflow_phase
from riftlens.replay_host.port import ControlOutcome, EnvironmentCheck
from riftlens.replay_host.seek import REAL_SEEK_TOLERANCE_MS, SeekOutcome, verified_seek
from riftlens.replay_host.session import ReplaySessionPhase, ReplaySessionSnapshot
from riftlens.replay_host.supervisor import (
    PlaybackTransport,
    ReplayApiTransport,
    ReplayProcessSupervisor,
    default_api_transport,
)
from riftlens.replay_host.timing import SleepClock, WallClock
from riftlens.replay_host.windows.capability_probe import (
    ReplayApiCapability,
    probe_replay_api_capability,
)
from riftlens.replay_host.windows.game_config import read_game_cfg
from riftlens.replay_host.windows.install_locator import (
    LeagueInstall,
    LeagueInstallResult,
    locate_league_install,
)

LocateFn = Callable[[], LeagueInstallResult]
ProbeFn = Callable[[], ReplayApiCapability]
SupervisorFactory = Callable[[], ReplayProcessSupervisor]


class WindowsReplayHost:
    """In-process Windows ReplayHostPort wrapping R.3–R.6. No remote transport."""

    def __init__(
        self,
        *,
        locate: LocateFn | None = None,
        probe: ProbeFn | None = None,
        supervisor_factory: SupervisorFactory | None = None,
        transport: PlaybackTransport | None = None,
        lcu: LcuReplayPort | None = None,
        clock: SleepClock | None = None,
        landing_tolerance_ms: int = REAL_SEEK_TOLERANCE_MS,
    ) -> None:
        self._locate = locate if locate is not None else locate_league_install
        self._probe = probe if probe is not None else probe_replay_api_capability
        self._transport: PlaybackTransport | None = transport
        self._lcu = lcu if lcu is not None else NullLcuReplayPort()
        self._clock = clock if clock is not None else WallClock()
        self._landing_tolerance_ms = landing_tolerance_ms
        self._supervisor_factory = supervisor_factory
        self._supervisor: ReplayProcessSupervisor | None = None
        self._install: LeagueInstall | None = None

    def platform_supported(self) -> bool:
        return True

    def platform_capabilities(self) -> frozenset[SourceCapability]:
        return NATIVE_REPLAY_CAPABILITIES

    def check_environment(self) -> EnvironmentCheck:
        located = self._locate()
        warnings: list[ReplayError] = []
        if located.install is None:
            error = located.error or ReplayError(ReplayErrorCode.INSTALL_NOT_FOUND)
            return EnvironmentCheck(
                supported=True,
                install_found=False,
                replay_api_documented=False,
                live_game=False,
                error=error,
            )
        self._install = located.install
        cfg_path = located.install.game_cfg
        if cfg_path.is_file():
            state = read_game_cfg(cfg_path)
            if state.enable_replay_api is not True:
                warnings.append(
                    ReplayError(
                        ReplayErrorCode.REPLAY_API_DISABLED,
                        details={"reason": "game_cfg_flag_missing", "path": cfg_path.name},
                    )
                )
        capability = self._probe()
        if capability.error is not None:
            warnings.append(capability.error)
        live_game = is_live_gameflow_phase(self._lcu.gameflow_phase())
        live_error: ReplayError | None = None
        if live_game:
            live_error = ReplayError(
                ReplayErrorCode.LIVE_GAME_IN_PROGRESS,
                details={"reason": "lcu_gameflow", "phase": self._lcu.gameflow_phase()},
            )
        return EnvironmentCheck(
            supported=True,
            install_found=True,
            replay_api_documented=capability.replay_playback_present,
            live_game=live_game,
            error=live_error,
            warnings=tuple(warnings),
        )

    def open_session(self, rofl_path: str) -> ReplaySessionSnapshot:
        env = self.check_environment()
        if env.error is not None and env.error.code is ReplayErrorCode.LIVE_GAME_IN_PROGRESS:
            return ReplaySessionSnapshot(phase=ReplaySessionPhase.FAILED, error=env.error)
        if self._install is None:
            error = env.error or ReplayError(ReplayErrorCode.INSTALL_NOT_FOUND)
            return ReplaySessionSnapshot(phase=ReplaySessionPhase.FAILED, error=error)
        supervisor = self._fresh_supervisor()
        return supervisor.open(rofl_path, self._install)

    def get_state(self) -> ReplaySessionSnapshot:
        if self._supervisor is None:
            return ReplaySessionSnapshot(phase=ReplaySessionPhase.IDLE)
        return self._supervisor.snapshot

    def poll_health(self) -> ReplaySessionSnapshot:
        if self._supervisor is None:
            return ReplaySessionSnapshot(phase=ReplaySessionPhase.IDLE)
        return self._supervisor.poll_health()

    def close_session(self) -> ReplaySessionSnapshot:
        if self._supervisor is None:
            return ReplaySessionSnapshot(phase=ReplaySessionPhase.CLOSED)
        return self._supervisor.close()

    def reveal(
        self,
        game_t_ms: int,
        clock: ClockMap,
        *,
        lead_in_ms: int = SEEK_LEAD_IN_MS,
        match_duration_ms: int | None = None,
    ) -> SeekOutcome:
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
        transport = self._require_transport()
        machine = None if self._supervisor is None else self._supervisor.machine
        return verified_seek(
            transport,
            clock,
            game_t_ms,
            lead_in_ms=lead_in_ms,
            session_ready=True,
            machine=machine,
            sleep_clock=self._clock,
            match_duration_ms=match_duration_ms,
            landing_tolerance_ms=self._landing_tolerance_ms,
        )

    def calibrate(
        self,
        *,
        match_duration_ms: int | None,
        riot_kills: Sequence[KillEvent] = (),
    ) -> CalibrationResult:
        health = self.poll_health()
        if not health.is_active:
            failed = calibrate_replay_clock(
                playback_length_ms=0,
                match_duration_ms=match_duration_ms,
                lcd_available=False,
            )
            return CalibrationResult(
                clock=failed.clock,
                method=failed.method,
                confidence=failed.confidence,
                offset_ms=failed.offset_ms,
                anchor_count=failed.anchor_count,
                residual_ms=failed.residual_ms,
                stdev_ms=failed.stdev_ms,
                duration_delta_ms=failed.duration_delta_ms,
                gamestats_relation=failed.gamestats_relation,
                lcd_available=False,
                error=ReplayError(
                    ReplayErrorCode.SOURCE_NOT_READY,
                    details={"phase": health.phase.value},
                ),
                match=failed.match,
                reason="session_not_ready",
            )
        transport = self._require_transport()
        playback = transport.get_playback()
        length_ms = max(0, int(round(float(playback.length) * 1000.0)))
        live = self._live_client()
        snapshots: list[EventData] = []
        players: list[PlayerListEntry] = []
        stats = None
        lcd_available = False
        playback_time_s = float(playback.time)
        if live is not None:
            try:
                stats = live.get_gamestats()
                lcd_available = True
            except ReplayError:
                stats = None
            try:
                snapshots.append(live.get_eventdata())
                players = live.get_playerlist()
                lcd_available = True
            except ReplayError:
                pass
            probe_clock = ClockMap(
                mode=ClockMode.IDENTITY,
                source_start_ms=0,
                source_end_ms=max(length_ms, 1),
                offset_ms=0,
                confidence=ClockConfidence.DEGRADED,
                verified=False,
            )
            for frac in (0.25, 0.50, 0.75):
                game_ms = min(int(length_ms * frac), max(0, length_ms - 1))
                outcome = verified_seek(
                    transport,
                    probe_clock,
                    game_ms,
                    lead_in_ms=0,
                    then_play=False,
                    session_ready=True,
                    sleep_clock=self._clock,
                    landing_tolerance_ms=self._landing_tolerance_ms,
                )
                if outcome.ok and live is not None:
                    try:
                        snapshots.append(live.get_eventdata())
                        players = live.get_playerlist()
                    except ReplayError:
                        pass
        eventdata = merge_eventdata(snapshots) if snapshots else None
        lcd_kills = () if eventdata is None else collect_lcd_kills(eventdata, players)
        relation = pause_crosscheck_gamestats(
            playback_time_s=playback_time_s,
            stats=stats,
            offset_ms=0,
        )
        del relation
        return calibrate_replay_clock(
            playback_length_ms=length_ms,
            match_duration_ms=match_duration_ms,
            riot_kills=riot_kills,
            lcd_kills=lcd_kills if lcd_available else None,
            lcd_available=lcd_available,
            playback_time_s=playback_time_s,
            gamestats_game_time_s=None if stats is None else stats.gameTime,
        )

    def pause(self) -> ControlOutcome:
        return self._set_playback(paused=True)

    def resume(self) -> ControlOutcome:
        return self._set_playback(paused=False)

    def set_speed(self, speed: float) -> ControlOutcome:
        return self._set_playback(speed=float(speed))

    def capture_interval(self, start_game_ms: int, end_game_ms: int) -> ControlOutcome:
        del start_game_ms, end_game_ms
        return ControlOutcome(
            ok=False,
            error=ReplayError(
                ReplayErrorCode.CAPABILITY_UNSUPPORTED,
                details={"reason": "capture_deferred_r10"},
            ),
        )

    def _set_playback(
        self,
        *,
        paused: bool | None = None,
        speed: float | None = None,
    ) -> ControlOutcome:
        health = self.poll_health()
        if not health.is_active:
            return ControlOutcome(
                ok=False,
                error=ReplayError(
                    ReplayErrorCode.SOURCE_NOT_READY,
                    details={"phase": health.phase.value},
                ),
            )
        try:
            playback = self._require_transport().set_playback(paused=paused, speed=speed)
        except ReplayError as exc:
            return ControlOutcome(ok=False, error=exc)
        state = None if playback is None else playback.to_playback_state()
        return ControlOutcome(ok=True, playback=state)

    def _fresh_supervisor(self) -> ReplayProcessSupervisor:
        if self._supervisor is None or self._supervisor.snapshot.is_terminal:
            if self._supervisor_factory is not None:
                self._supervisor = self._supervisor_factory()
            else:
                if self._transport is None:
                    created = default_api_transport()
                    self._transport = created
                    transport: PlaybackTransport = created
                else:
                    transport = self._transport
                self._supervisor = ReplayProcessSupervisor(
                    transport=transport,
                    live_probe=transport if isinstance(transport, ReplayApiTransport) else None,
                    lcu=self._lcu,
                    clock=self._clock,
                )
        return self._supervisor

    def _require_transport(self) -> PlaybackTransport:
        if self._transport is not None:
            return self._transport
        raise ReplayError(
            ReplayErrorCode.REPLAY_API_UNAVAILABLE,
            details={"reason": "transport_missing"},
        )

    def _live_client(self) -> LiveClientDataClient | None:
        transport = self._transport
        if isinstance(transport, ReplayApiTransport):
            return transport.live
        return None
