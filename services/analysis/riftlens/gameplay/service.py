from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from riftlens.domain.capture import (
    CaptureProgress,
    CaptureRequest,
    CaptureResult,
    CaptureStatus,
)
from riftlens.domain.clock_map import ClockConfidence, ClockMap, ClockMode
from riftlens.domain.clock_store import (
    CALIBRATION_METHOD_EVENT_ANCHOR_V1,
    SOURCE_STATUS_LINKED,
    SOURCE_TYPE_ROFL,
    local_display_name,
)
from riftlens.domain.gameplay_source import SourceCapability, SourceKind
from riftlens.domain.ids import new_ulid
from riftlens.domain.ports import (
    GameplayRepository,
    GameplaySourceRecord,
    GameplaySourceSnapshot,
    MatchRepository,
    ReplaySessionAuditRecord,
    RoflSourceDetailRecord,
)
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.domain.sync_map import SEEK_LEAD_IN_MS
from riftlens.gameplay.factory import GameplaySourceFactory
from riftlens.gameplay.kills import riot_kills_from_match
from riftlens.gameplay.outcomes import ImportOutcome, ResolvedSource, RevealOutcome
from riftlens.gameplay.status import compose_gameplay_status, pick_source
from riftlens.replay_host.capture.capture_service import CaptureService
from riftlens.replay_host.clock.anchor_matcher import KillEvent
from riftlens.replay_host.clock.calibrator import CalibrationResult
from riftlens.replay_host.port import EnvironmentCheck, ReplayHostPort
from riftlens.replay_host.session import ReplaySessionPhase, ReplaySessionSnapshot
from riftlens.rofl.identity import RoflIdentity, identify_rofl

KillLoader = Callable[[str], Awaitable[tuple[KillEvent, ...]]]


class GameplaySourceService:
    """Public orchestration surface. Callers speak game time and GameplaySource only."""

    def __init__(
        self,
        *,
        host: ReplayHostPort,
        gameplay: GameplayRepository,
        matches: MatchRepository,
        factory: GameplaySourceFactory | None = None,
        kill_loader: KillLoader | None = None,
        captures: CaptureService | None = None,
    ) -> None:
        self._host = host
        self._gameplay = gameplay
        self._matches = matches
        self._factory = factory if factory is not None else GameplaySourceFactory(host)
        self._kill_loader = kill_loader
        self._captures = captures

    async def import_rofl(
        self,
        path: str,
        *,
        now_ms: int,
        match_id: str | None = None,
    ) -> ImportOutcome:
        """Validate, identify, correlate, and persist a native replay source. Does not launch."""
        identified = identify_rofl(path)
        warnings = tuple(identified.warnings)
        if identified.error is not None:
            return ImportOutcome(
                ok=False,
                source_id=None,
                match_id=None,
                identity=identified.identity,
                snapshot=None,
                error=identified.error,
                warnings=warnings,
            )
        identity = identified.identity
        resolved_match = match_id or identity.match_id_hint
        if resolved_match is None:
            return ImportOutcome(
                ok=False,
                source_id=None,
                match_id=None,
                identity=identity,
                snapshot=None,
                error=ReplayError(
                    ReplayErrorCode.MATCH_ID_UNRESOLVED,
                    details={"suggested_action": "pick_match"},
                ),
                warnings=warnings,
            )
        match = await self._matches.get_match(resolved_match)
        if match is None:
            return ImportOutcome(
                ok=False,
                source_id=None,
                match_id=resolved_match,
                identity=identity,
                snapshot=None,
                error=ReplayError(
                    ReplayErrorCode.MATCH_NOT_INGESTED,
                    details={
                        "match_id": resolved_match,
                        "suggested_action": "ingest_match",
                    },
                ),
                warnings=warnings,
            )
        duration = identity.declared_length_ms
        if duration is None or duration <= 0:
            duration = match.game_duration_ms
        source_id = new_ulid()
        stored_id = await self._gameplay.upsert_source(
            GameplaySourceRecord(
                id=source_id,
                match_id=match.match_id,
                source_type=SOURCE_TYPE_ROFL,
                source_uri=path,
                content_hash=None,
                display_name=local_display_name(path),
                duration_ms=int(duration),
                status=SOURCE_STATUS_LINKED,
                platform_scope="windows",
                created_at=now_ms,
                updated_at=now_ms,
            ),
            rofl=_rofl_detail(source_id, identity, identified.raw_metadata_json),
        )
        snapshot = await self._gameplay.get_source(stored_id)
        return ImportOutcome(
            ok=True,
            source_id=stored_id,
            match_id=match.match_id,
            identity=identity,
            snapshot=snapshot,
            error=None,
            warnings=warnings,
        )

    async def resolve_source(self, source_id: str) -> ResolvedSource | None:
        """Load a persisted descriptor. Missing ids return None."""
        snapshot = await self._gameplay.get_source(source_id)
        if snapshot is None:
            return None
        return self._factory.resolve(snapshot)

    async def reveal(
        self,
        source_id: str,
        game_t_ms: int,
        *,
        lead_in_ms: int = SEEK_LEAD_IN_MS,
        now_ms: int = 0,
    ) -> RevealOutcome:
        """Clamp lead-in, ensure READY for native replay, convert clocks, verified-seek."""
        snapshot = await self._gameplay.get_source(source_id)
        if snapshot is None:
            return _failed_reveal(
                source_id,
                SourceKind.NATIVE_REPLAY,
                game_t_ms,
                lead_in_ms,
                ReplayError(ReplayErrorCode.ROFL_MISSING, details={"reason": "unknown_source"}),
            )
        resolved = self._factory.resolve(snapshot)
        if resolved.source.kind is SourceKind.VIDEO:
            return self._reveal_video(resolved, game_t_ms, lead_in_ms)
        if not resolved.available:
            error = resolved.reason or ReplayError(ReplayErrorCode.PLATFORM_UNSUPPORTED)
            return _failed_reveal(
                source_id,
                SourceKind.NATIVE_REPLAY,
                game_t_ms,
                lead_in_ms,
                error,
                capabilities=resolved.source.capabilities,
                clock=resolved.source.clock,
            )
        if not snapshot.file_present:
            await self._gameplay.revalidate_source(
                source_id, updated_at=now_ms or snapshot.source.updated_at
            )
            return _failed_reveal(
                source_id,
                SourceKind.NATIVE_REPLAY,
                game_t_ms,
                lead_in_ms,
                ReplayError(
                    ReplayErrorCode.ROFL_MISSING,
                    details={"reason": "source_file_missing", "source_id": source_id},
                ),
                clock=resolved.source.clock,
            )
        session = self._ensure_ready(snapshot.source.source_uri)
        if session.error is not None and not session.is_active:
            return _failed_reveal(
                source_id,
                SourceKind.NATIVE_REPLAY,
                game_t_ms,
                lead_in_ms,
                session.error,
                clock=resolved.source.clock,
                capabilities=resolved.source.capabilities,
            )
        if not session.is_active:
            return _failed_reveal(
                source_id,
                SourceKind.NATIVE_REPLAY,
                game_t_ms,
                lead_in_ms,
                ReplayError(
                    ReplayErrorCode.SOURCE_NOT_READY,
                    details={"phase": session.phase.value},
                ),
                clock=resolved.source.clock,
                capabilities=resolved.source.capabilities,
            )
        clock, warnings = await self._obtain_clock(
            source_id, snapshot, match_id=snapshot.source.match_id, now_ms=now_ms
        )
        if clock.mode is ClockMode.UNMAPPED:
            return _failed_reveal(
                source_id,
                SourceKind.NATIVE_REPLAY,
                game_t_ms,
                lead_in_ms,
                ReplayError(ReplayErrorCode.CLOCK_UNMAPPED),
                clock=clock,
                capabilities=resolved.source.capabilities,
                warnings=warnings,
            )
        match = await self._matches.get_match(snapshot.source.match_id)
        duration = None if match is None else match.game_duration_ms
        seek = self._host.reveal(
            game_t_ms,
            clock,
            lead_in_ms=lead_in_ms,
            match_duration_ms=duration,
        )
        return RevealOutcome(
            ok=seek.ok,
            source_id=source_id,
            kind=SourceKind.NATIVE_REPLAY,
            target_game_ms=seek.target_game_ms,
            lead_in_ms=lead_in_ms,
            target_source_ms=seek.target_source_ms,
            landed_source_ms=seek.landed_source_ms,
            playback=seek.playback,
            clock=clock,
            clock_verified=clock.verified,
            capabilities=resolved.source.capabilities,
            error=seek.error,
            warnings=warnings,
            native_seek=seek,
        )

    async def request_capture(
        self, request: CaptureRequest, *, now_ms: int = 0
    ) -> CaptureResult:
        """Ensure session + clock, then start an explicit R.10 capture. Never called by reveal."""
        captures = self._require_captures()
        if captures is None:
            return _failed_capture(
                ReplayError(
                    ReplayErrorCode.CAPABILITY_UNSUPPORTED,
                    details={"reason": "capture_service_unavailable"},
                )
            )
        stamp = now_ms or self.now_ms()
        snapshot = await self._gameplay.get_source(request.source_id)
        if snapshot is None:
            return _failed_capture(
                ReplayError(ReplayErrorCode.ROFL_MISSING, details={"reason": "unknown_source"})
            )
        resolved = self._factory.resolve(snapshot)
        if resolved.source.kind is SourceKind.VIDEO:
            return _failed_capture(
                ReplayError(
                    ReplayErrorCode.CAPABILITY_UNSUPPORTED,
                    details={"reason": "video_sources_cannot_capture"},
                )
            )
        if not resolved.available:
            return _failed_capture(
                resolved.reason or ReplayError(ReplayErrorCode.PLATFORM_UNSUPPORTED)
            )
        if not snapshot.file_present:
            await self._gameplay.revalidate_source(request.source_id, updated_at=stamp)
            return _failed_capture(
                ReplayError(
                    ReplayErrorCode.ROFL_MISSING,
                    details={"reason": "source_file_missing", "source_id": request.source_id},
                )
            )
        session = self._ensure_ready(snapshot.source.source_uri)
        if not session.is_active:
            return _failed_capture(
                session.error
                or ReplayError(
                    ReplayErrorCode.SOURCE_NOT_READY, details={"phase": session.phase.value}
                )
            )
        clock, _warnings = await self._obtain_clock(
            request.source_id,
            snapshot,
            match_id=snapshot.source.match_id,
            now_ms=stamp,
        )
        if clock.mode is ClockMode.UNMAPPED:
            return _failed_capture(ReplayError(ReplayErrorCode.CLOCK_UNMAPPED))
        return await captures.start_capture(request, now_ms=stamp)

    async def get_capture(self, capture_id: str) -> CaptureResult:
        """Return the persisted capture view. Unknown ids yield a typed failure result."""
        captures = self._require_captures()
        if captures is None:
            return _failed_capture(
                ReplayError(
                    ReplayErrorCode.CAPABILITY_UNSUPPORTED,
                    details={"reason": "capture_service_unavailable"},
                )
            )
        return await captures.get_result(capture_id)

    async def cancel_capture(self, capture_id: str) -> CaptureResult:
        """Cancel a running capture and remove its partials."""
        captures = self._require_captures()
        if captures is None:
            return _failed_capture(
                ReplayError(
                    ReplayErrorCode.CAPABILITY_UNSUPPORTED,
                    details={"reason": "capture_service_unavailable"},
                )
            )
        return await captures.cancel(capture_id)

    async def capture_progress(self, capture_id: str) -> CaptureProgress | None:
        """Return live progress for a capture, or None when the service is not wired."""
        captures = self._require_captures()
        if captures is None:
            return None
        try:
            return await captures.get_progress(capture_id)
        except ReplayError:
            return None

    async def close_session(self, source_id: str, *, now_ms: int) -> None:
        """Close the live host session and append an audit row. ClockMap stays persisted."""
        snap = self._host.close_session()
        await self._gameplay.record_session(
            ReplaySessionAuditRecord(
                id=new_ulid(),
                gameplay_source_id=source_id,
                replay_api_base=None,
                replay_api_port=2999,
                state=snap.phase.value.lower(),
                last_error=None if snap.error is None else snap.error.code.value,
                started_at=now_ms,
                ended_at=now_ms,
            )
        )

    async def open_linked_source(self, source_id: str) -> ReplaySessionSnapshot:
        """Establish a fresh host session for a persisted source. Does not reveal."""
        snapshot = await self._gameplay.get_source(source_id)
        if snapshot is None:
            return ReplaySessionSnapshot(
                phase=ReplaySessionPhase.FAILED,
                error=ReplayError(
                    ReplayErrorCode.ROFL_MISSING, details={"reason": "unknown_source"}
                ),
            )
        resolved = self._factory.resolve(snapshot)
        if not resolved.available:
            return ReplaySessionSnapshot(
                phase=ReplaySessionPhase.FAILED,
                error=resolved.reason
                or ReplayError(ReplayErrorCode.PLATFORM_UNSUPPORTED),
            )
        if not snapshot.file_present:
            return ReplaySessionSnapshot(
                phase=ReplaySessionPhase.FAILED,
                error=ReplayError(
                    ReplayErrorCode.ROFL_MISSING,
                    details={"reason": "source_file_missing", "source_id": source_id},
                ),
            )
        return await asyncio.to_thread(self._host.open_session, snapshot.source.source_uri)

    async def status_for_match(
        self,
        match_id: str,
        *,
        source_id: str | None = None,
        poll: bool = True,
    ) -> dict[str, Any]:
        """Compose R.9 status from persisted sources + live session. Never infers READY."""
        snapshots = list(await self._gameplay.list_sources_for_match(match_id))
        chosen, resolved = pick_source(snapshots, self._factory, source_id)
        session = self._host.poll_health() if poll else self._host.get_state()
        return compose_gameplay_status(
            match_id=match_id,
            native_supported=self._host.platform_supported(),
            snapshots=snapshots,
            chosen=chosen,
            resolved=resolved,
            session=session,
            factory=self._factory,
        )

    def check_environment(self) -> EnvironmentCheck:
        """Delegate install/Replay-API probe. Does not launch."""
        return self._host.check_environment()

    def now_ms(self) -> int:
        """Wall-clock milliseconds for persistence timestamps."""
        return int(time.time() * 1000)

    def _require_captures(self) -> CaptureService | None:
        return self._captures

    def _ensure_ready(self, rofl_path: str) -> ReplaySessionSnapshot:
        state = self._host.poll_health()
        if state.error is not None and state.error.code is ReplayErrorCode.SESSION_LOST:
            return state
        if state.is_active:
            return state
        if state.phase is ReplaySessionPhase.FAILED:
            return state
        return self._host.open_session(rofl_path)

    async def _obtain_clock(
        self,
        source_id: str,
        snapshot: GameplaySourceSnapshot,
        *,
        match_id: str,
        now_ms: int,
    ) -> tuple[ClockMap, tuple[ReplayError, ...]]:
        active = snapshot.clock
        if active is not None and _reusable_verified(active.clock):
            return active.clock, ()
        match = await self._matches.get_match(match_id)
        duration = None if match is None else match.game_duration_ms
        kills = await self._load_kills(match_id)
        result = self._host.calibrate(match_duration_ms=duration, riot_kills=kills)
        await self._persist_calibration(
            source_id, result, now_ms=now_ms or snapshot.source.updated_at
        )
        warnings: list[ReplayError] = []
        if result.error is not None:
            warnings.append(result.error)
        elif not result.clock.verified:
            warnings.append(
                ReplayError(
                    ReplayErrorCode.CLOCK_CALIBRATION_FAILED,
                    details={"method": result.method, "reason": result.reason},
                )
            )
        return result.clock, tuple(warnings)

    async def _persist_calibration(
        self, source_id: str, result: CalibrationResult, *, now_ms: int
    ) -> None:
        residual = None if result.residual_ms is None else int(round(result.residual_ms))
        method = result.method
        if method == "event_anchor":
            method = CALIBRATION_METHOD_EVENT_ANCHOR_V1
        await self._gameplay.replace_clock(
            source_id,
            result.clock,
            method=method,
            created_at=now_ms,
            anchor_count=result.anchor_count,
            residual_ms=residual,
            stdev_ms=result.stdev_ms,
            warning=None if result.error is None else result.error.code.value,
        )

    async def _load_kills(self, match_id: str) -> tuple[KillEvent, ...]:
        if self._kill_loader is not None:
            return await self._kill_loader(match_id)
        return await riot_kills_from_match(self._matches, match_id)

    def _reveal_video(
        self, resolved: ResolvedSource, game_t_ms: int, lead_in_ms: int
    ) -> RevealOutcome:
        target = resolved.source.seek_for_game(game_t_ms, lead_in_ms=lead_in_ms)
        error = None
        if not target.covered:
            error = ReplayError(
                ReplayErrorCode.CLOCK_UNMAPPED
                if resolved.source.clock.confidence is ClockConfidence.UNKNOWN
                else ReplayErrorCode.CLOCK_OUT_OF_BOUNDS,
                details={"reason": target.reason},
            )
        return RevealOutcome(
            ok=target.covered,
            source_id=resolved.source.id,
            kind=SourceKind.VIDEO,
            target_game_ms=target.t_game_ms,
            lead_in_ms=lead_in_ms,
            target_source_ms=target.seek_video_ms,
            landed_source_ms=target.t_video_ms,
            playback=None,
            clock=resolved.source.clock,
            clock_verified=resolved.source.clock.verified,
            capabilities=resolved.source.capabilities,
            error=error,
            video_seek=target,
        )


def _failed_capture(error: ReplayError) -> CaptureResult:
    return CaptureResult(ok=False, capture_id="", status=CaptureStatus.FAILED, error=error)


def _reusable_verified(clock: ClockMap) -> bool:
    if not clock.verified:
        return False
    return clock.confidence in {ClockConfidence.EXACT, ClockConfidence.GOOD}


def _rofl_detail(
    source_id: str, identity: RoflIdentity, raw_metadata_json: str | None
) -> RoflSourceDetailRecord:
    return RoflSourceDetailRecord(
        gameplay_source_id=source_id,
        platform_id=identity.platform_id,
        game_id=identity.game_id,
        declared_patch=identity.declared_patch,
        declared_length_ms=identity.declared_length_ms,
        identify_method=identity.identify_method.value,
        header_parse_status=identity.header_parse_status.value,
        file_size_bytes=identity.file_size_bytes,
        magic=identity.magic,
        raw_metadata_json=raw_metadata_json,
    )


def _failed_reveal(
    source_id: str,
    kind: SourceKind,
    game_t_ms: int,
    lead_in_ms: int,
    error: ReplayError,
    *,
    clock: ClockMap | None = None,
    capabilities: frozenset[SourceCapability] = frozenset(),
    warnings: tuple[ReplayError, ...] = (),
) -> RevealOutcome:
    return RevealOutcome(
        ok=False,
        source_id=source_id,
        kind=kind,
        target_game_ms=int(game_t_ms),
        lead_in_ms=lead_in_ms,
        target_source_ms=None,
        landed_source_ms=None,
        playback=None,
        clock=clock,
        clock_verified=False if clock is None else clock.verified,
        capabilities=capabilities,
        error=error,
        warnings=warnings,
    )
