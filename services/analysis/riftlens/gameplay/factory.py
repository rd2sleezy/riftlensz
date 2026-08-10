from __future__ import annotations

from riftlens.domain.clock_map import ClockMap, ClockMode
from riftlens.domain.clock_store import SOURCE_TYPE_VIDEO
from riftlens.domain.gameplay_source import (
    NATIVE_REPLAY_CAPABILITIES,
    VIDEO_CAPABILITIES,
    GameplaySource,
    SourceCapability,
    SourceKind,
)
from riftlens.domain.ports import GameplaySourceSnapshot
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.gameplay.outcomes import ResolvedSource
from riftlens.replay_host.port import ReplayHostPort


class GameplaySourceFactory:
    """Resolve a persisted descriptor into a live GameplaySource for the current host."""

    def __init__(self, host: ReplayHostPort) -> None:
        self._host = host

    def resolve(self, snapshot: GameplaySourceSnapshot) -> ResolvedSource:
        """Build a GameplaySource. Native replay stays loadable when the host is unsupported."""
        clock = _clock_from_snapshot(snapshot)
        source_type = snapshot.source.source_type
        if source_type == SOURCE_TYPE_VIDEO:
            media_id = snapshot.source.media_asset_id or "video"
            source = GameplaySource.for_video(
                source_id=snapshot.source.id,
                match_id=snapshot.source.match_id,
                media_asset_id=media_id,
                duration_ms=snapshot.source.duration_ms,
                sync_map=None if clock.sync_map is None else clock.sync_map,
            )
            if clock.sync_map is None and clock.mode is not ClockMode.UNMAPPED:
                source = GameplaySource(
                    id=snapshot.source.id,
                    kind=SourceKind.VIDEO,
                    match_id=snapshot.source.match_id,
                    capabilities=VIDEO_CAPABILITIES,
                    clock=clock,
                    duration_ms=snapshot.source.duration_ms,
                    media_asset_id=media_id,
                )
            return ResolvedSource(source=source, available=True, reason=None)
        capabilities = _native_capabilities(self._host)
        source = GameplaySource.for_native_replay(
            source_id=snapshot.source.id,
            match_id=snapshot.source.match_id,
            duration_ms=snapshot.source.duration_ms,
            capabilities=capabilities,
            clock=clock,
        )
        if not self._host.platform_supported():
            return ResolvedSource(
                source=source,
                available=False,
                reason=ReplayError(
                    ReplayErrorCode.PLATFORM_UNSUPPORTED,
                    details={
                        "reason": "native_replay_windows_only",
                        "suggested_action": "attach_video",
                    },
                ),
            )
        if not snapshot.file_present:
            return ResolvedSource(
                source=source,
                available=False,
                reason=ReplayError(
                    ReplayErrorCode.ROFL_MISSING,
                    details={"reason": "source_file_missing", "source_id": snapshot.source.id},
                ),
            )
        return ResolvedSource(source=source, available=True, reason=None)


def _clock_from_snapshot(snapshot: GameplaySourceSnapshot) -> ClockMap:
    if snapshot.clock is not None:
        return snapshot.clock.clock
    return ClockMap.unmapped(duration_ms=snapshot.source.duration_ms)


def _native_capabilities(host: ReplayHostPort) -> frozenset[SourceCapability]:
    if not host.platform_supported():
        return frozenset()
    caps = host.platform_capabilities()
    return caps if caps else NATIVE_REPLAY_CAPABILITIES
