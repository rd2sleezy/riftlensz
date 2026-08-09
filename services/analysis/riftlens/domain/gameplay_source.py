from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from riftlens.domain.clock_map import ClockConfidence, ClockMap
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.domain.sync_map import SEEK_LEAD_IN_MS, SeekTarget, SyncMap, seek_target


class SourceKind(StrEnum):
    """Playback medium. VIDEO is H.9; NATIVE_REPLAY is the R.0-proven .rofl path."""

    VIDEO = "VIDEO"
    NATIVE_REPLAY = "NATIVE_REPLAY"


class SourceCapability(StrEnum):
    """Operations a gameplay source may expose. Presence is explicit, never assumed."""

    READ_TIME = "READ_TIME"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    SEEK = "SEEK"
    SET_SPEED = "SET_SPEED"
    LIVE_CLIENT_DATA = "LIVE_CLIENT_DATA"
    ACTIVE_PLAYER = "ACTIVE_PLAYER"


# H.9 HTML video element: clock + transport. No Live Client Data.
VIDEO_CAPABILITIES: frozenset[SourceCapability] = frozenset(
    {
        SourceCapability.READ_TIME,
        SourceCapability.PAUSE,
        SourceCapability.RESUME,
        SourceCapability.SEEK,
        SourceCapability.SET_SPEED,
    }
)

# R.0 confirmed native replay surface. activeplayer returned HTTP 400 — omit it.
NATIVE_REPLAY_CAPABILITIES: frozenset[SourceCapability] = frozenset(
    {
        SourceCapability.READ_TIME,
        SourceCapability.PAUSE,
        SourceCapability.RESUME,
        SourceCapability.SEEK,
        SourceCapability.SET_SPEED,
        SourceCapability.LIVE_CLIENT_DATA,
    }
)

_UNCERTAIN_CLOCK = frozenset(
    {ClockConfidence.DEGRADED, ClockConfidence.UNKNOWN, ClockConfidence.FAILED}
)


@dataclass(frozen=True)
class PlaybackState:
    """Snapshot of source transport. Times are integer milliseconds, never seconds."""

    t_source_ms: int
    length_ms: int
    paused: bool
    seeking: bool
    speed_milli: int = 1000
    t_game_ms: int | None = None

    def __post_init__(self) -> None:
        if self.length_ms < 0:
            raise ValueError("length_ms must be >= 0")
        if self.speed_milli < 0:
            raise ValueError("speed_milli must be >= 0")

    def bind_clock(self, clock: ClockMap) -> PlaybackState:
        """Return a copy with ``t_game_ms`` from ``clock``. Unmapped times stay None."""
        return PlaybackState(
            t_source_ms=self.t_source_ms,
            length_ms=self.length_ms,
            paused=self.paused,
            seeking=self.seeking,
            speed_milli=self.speed_milli,
            t_game_ms=clock.source_to_game(self.t_source_ms),
        )


@dataclass(frozen=True)
class GameplaySource:
    """Cross-platform description of where review playback comes from.

    Does not launch clients, touch the filesystem, or speak HTTP. Adapters live later.
    """

    id: str
    kind: SourceKind
    match_id: str
    capabilities: frozenset[SourceCapability]
    clock: ClockMap
    duration_ms: int
    media_asset_id: str | None = None

    def __post_init__(self) -> None:
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be >= 0")
        if self.kind is SourceKind.VIDEO and not self.media_asset_id:
            raise ValueError("VIDEO source requires media_asset_id")
        if self.kind is SourceKind.NATIVE_REPLAY and self.media_asset_id is not None:
            raise ValueError("NATIVE_REPLAY source does not use media_asset_id")

    @classmethod
    def for_video(
        cls,
        *,
        source_id: str,
        match_id: str,
        media_asset_id: str,
        duration_ms: int,
        sync_map: SyncMap | None,
        capabilities: frozenset[SourceCapability] | None = None,
    ) -> GameplaySource:
        """Represent an H.9 VOD. ``sync_map`` None means seek stays uncovered."""
        clock = (
            ClockMap.unmapped(duration_ms=duration_ms)
            if sync_map is None
            else ClockMap.from_sync_map(sync_map)
        )
        return cls(
            id=source_id,
            kind=SourceKind.VIDEO,
            match_id=match_id,
            capabilities=capabilities if capabilities is not None else VIDEO_CAPABILITIES,
            clock=clock,
            duration_ms=int(duration_ms),
            media_asset_id=media_asset_id,
        )

    @classmethod
    def for_native_replay(
        cls,
        *,
        source_id: str,
        match_id: str,
        duration_ms: int,
        capabilities: frozenset[SourceCapability] | None = None,
        clock: ClockMap | None = None,
    ) -> GameplaySource:
        """Represent a native .rofl source. Assumes Replay API time is game time."""
        return cls(
            id=source_id,
            kind=SourceKind.NATIVE_REPLAY,
            match_id=match_id,
            capabilities=(
                capabilities if capabilities is not None else NATIVE_REPLAY_CAPABILITIES
            ),
            clock=clock if clock is not None else ClockMap.identity(duration_ms=duration_ms),
            duration_ms=int(duration_ms),
            media_asset_id=None,
        )

    def supports(self, capability: SourceCapability) -> bool:
        """Return True when ``capability`` is advertised. Assumes the set is explicit."""
        return capability in self.capabilities

    def require(self, capability: SourceCapability) -> None:
        """Raise ``ReplayError`` when ``capability`` is missing. Does not probe a client."""
        if not self.supports(capability):
            raise ReplayError(
                ReplayErrorCode.CAPABILITY_UNSUPPORTED,
                details={"capability": capability.value, "kind": self.kind.value},
            )

    def seek_for_game(
        self, t_game_ms: int, *, lead_in_ms: int = SEEK_LEAD_IN_MS
    ) -> SeekTarget:
        """Map a finding ``t_ms`` onto this source. VIDEO delegates to H.9 ``seek_target``."""
        if self.kind is SourceKind.VIDEO:
            return seek_target(self.clock.sync_map, t_game_ms, lead_in_ms=lead_in_ms)
        return _native_seek_target(self.clock, t_game_ms, lead_in_ms=lead_in_ms)


def _native_seek_target(clock: ClockMap, t_game_ms: int, *, lead_in_ms: int) -> SeekTarget:
    """Build a SeekTarget for identity/offset clocks. Does not invent uncovered times."""
    t_source = clock.game_to_source(t_game_ms)
    if t_source is None:
        reason = (
            "No sync map — VOD time is unknown until you set a clock anchor."
            if clock.confidence is ClockConfidence.UNKNOWN
            else "Recording does not cover this game time."
        )
        return SeekTarget(
            t_game_ms=t_game_ms,
            t_video_ms=None,
            seek_video_ms=None,
            covered=False,
            uncertain=True,
            reason=reason,
        )
    uncertain = clock.confidence in _UNCERTAIN_CLOCK or not clock.verified
    seek_at = clock.clamp_source_ms(t_source - max(0, lead_in_ms))
    return SeekTarget(
        t_game_ms=t_game_ms,
        t_video_ms=t_source,
        seek_video_ms=seek_at,
        covered=True,
        uncertain=uncertain,
        reason=_native_uncertainty_reason(clock) if uncertain else None,
    )


def _native_uncertainty_reason(clock: ClockMap) -> str:
    """Return why a native seek is uncertain. Assumes the caller already flagged uncertain."""
    if clock.confidence is ClockConfidence.FAILED:
        return "Sync failed quality checks — do not treat VOD times as exact."
    if clock.confidence is ClockConfidence.DEGRADED:
        return "Single-anchor sync is approximate. A second clock reading would confirm it."
    if not clock.verified:
        return "Sync is not independently verified against in-game events."
    return "Sync confidence is limited."
