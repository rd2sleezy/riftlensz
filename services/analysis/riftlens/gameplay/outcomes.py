from __future__ import annotations

from dataclasses import dataclass

from riftlens.domain.clock_map import ClockMap
from riftlens.domain.gameplay_source import (
    GameplaySource,
    PlaybackState,
    SourceCapability,
    SourceKind,
)
from riftlens.domain.ports import GameplaySourceSnapshot
from riftlens.domain.replay_errors import ReplayError
from riftlens.domain.sync_map import SeekTarget
from riftlens.replay_host.seek import SeekOutcome
from riftlens.replay_host.session import ReplaySessionSnapshot
from riftlens.rofl.identity import RoflIdentity


@dataclass(frozen=True)
class ImportOutcome:
    """Result of linking a .rofl to a persisted GameplaySource. No UI prompts."""

    ok: bool
    source_id: str | None
    match_id: str | None
    identity: RoflIdentity | None
    snapshot: GameplaySourceSnapshot | None
    error: ReplayError | None
    warnings: tuple[ReplayError, ...] = ()


@dataclass(frozen=True)
class RevealOutcome:
    """Application-facing click-to-replay result. Identical shape for VIDEO and ROFL."""

    ok: bool
    source_id: str
    kind: SourceKind
    target_game_ms: int
    lead_in_ms: int
    target_source_ms: int | None
    landed_source_ms: int | None
    playback: PlaybackState | None
    clock: ClockMap | None
    clock_verified: bool
    capabilities: frozenset[SourceCapability]
    error: ReplayError | None
    warnings: tuple[ReplayError, ...] = ()
    video_seek: SeekTarget | None = None
    native_seek: SeekOutcome | None = None


@dataclass(frozen=True)
class ResolvedSource:
    """Descriptor plus runtime availability. Persisted ROFL may load on macOS as unavailable."""

    source: GameplaySource
    available: bool
    reason: ReplayError | None
    session: ReplaySessionSnapshot | None = None
