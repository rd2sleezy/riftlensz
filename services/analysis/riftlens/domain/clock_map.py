from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from riftlens.domain.sync_map import SyncMap, SyncVerdict


class ClockMode(StrEnum):
    """How source playback time relates to canonical game time (``t_ms``)."""

    IDENTITY = "IDENTITY"
    OFFSET = "OFFSET"
    SYNC_MAP = "SYNC_MAP"
    UNMAPPED = "UNMAPPED"


class ClockConfidence(StrEnum):
    """Confidence that source↔game conversion is trustworthy."""

    EXACT = "EXACT"
    GOOD = "GOOD"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"
    FAILED = "FAILED"


_VERDICT_TO_CONFIDENCE: dict[SyncVerdict, ClockConfidence] = {
    "EXCELLENT": ClockConfidence.EXACT,
    "GOOD": ClockConfidence.GOOD,
    "DEGRADED": ClockConfidence.DEGRADED,
    "FAILED": ClockConfidence.FAILED,
}


@dataclass(frozen=True)
class ClockMap:
    """Integer-ms map between a gameplay source clock and game time.

    Source time is video ms for H.9 VODs and Replay API ms for native .rofl.
    Game time is always ``t_ms`` since in-game 00:00. Uncovered times stay None.
    """

    mode: ClockMode
    source_start_ms: int
    source_end_ms: int
    offset_ms: int
    confidence: ClockConfidence
    verified: bool = False
    sync_map: SyncMap | None = None

    def __post_init__(self) -> None:
        if self.source_end_ms < self.source_start_ms:
            raise ValueError("source_end_ms must be >= source_start_ms")
        if self.mode is ClockMode.SYNC_MAP and self.sync_map is None:
            raise ValueError("SYNC_MAP clock requires a SyncMap")
        if self.mode is ClockMode.UNMAPPED and self.sync_map is not None:
            raise ValueError("UNMAPPED clock cannot carry a SyncMap")

    @classmethod
    def identity(cls, *, duration_ms: int, verified: bool = True) -> ClockMap:
        """Return a 1:1 map. Assumes Replay API time is already game time."""
        if duration_ms < 0:
            raise ValueError("duration_ms must be >= 0")
        return cls(
            mode=ClockMode.IDENTITY,
            source_start_ms=0,
            source_end_ms=int(duration_ms),
            offset_ms=0,
            confidence=ClockConfidence.EXACT,
            verified=verified,
        )

    @classmethod
    def offset(
        cls,
        *,
        offset_ms: int,
        source_start_ms: int,
        source_end_ms: int,
        confidence: ClockConfidence = ClockConfidence.GOOD,
        verified: bool = False,
    ) -> ClockMap:
        """Return ``t_game = t_source + offset_ms`` on ``[start, end)``."""
        return cls(
            mode=ClockMode.OFFSET,
            source_start_ms=int(source_start_ms),
            source_end_ms=int(source_end_ms),
            offset_ms=int(offset_ms),
            confidence=confidence,
            verified=verified,
        )

    @classmethod
    def unmapped(cls, *, duration_ms: int) -> ClockMap:
        """Return a clock that never converts. Assumes duration is source length."""
        if duration_ms < 0:
            raise ValueError("duration_ms must be >= 0")
        return cls(
            mode=ClockMode.UNMAPPED,
            source_start_ms=0,
            source_end_ms=int(duration_ms),
            offset_ms=0,
            confidence=ClockConfidence.UNKNOWN,
            verified=False,
        )

    @classmethod
    def from_sync_map(cls, sync_map: SyncMap) -> ClockMap:
        """Wrap an H.9 SyncMap without changing its conversion behavior."""
        if sync_map.segments:
            start = min(item.video_start_ms for item in sync_map.segments)
            end = max(item.video_end_ms for item in sync_map.segments)
        else:
            start, end = 0, 0
        offset = sync_map.segments[0].offset_ms if len(sync_map.segments) == 1 else 0
        return cls(
            mode=ClockMode.SYNC_MAP,
            source_start_ms=start,
            source_end_ms=end,
            offset_ms=offset,
            confidence=_VERDICT_TO_CONFIDENCE[sync_map.quality.verdict],
            verified=sync_map.verified,
            sync_map=sync_map,
        )

    def contains_source(self, t_source_ms: int) -> bool:
        """Return True when ``t_source_ms`` is inside the half-open source span."""
        return self.source_start_ms <= int(t_source_ms) < self.source_end_ms

    def contains_game(self, t_game_ms: int) -> bool:
        """Return True when ``game_to_source`` would succeed."""
        return self.game_to_source(t_game_ms) is not None

    def clamp_source_ms(self, t_source_ms: int) -> int:
        """Return ``t_source_ms`` clamped into the source span. Empty span yields start."""
        if self.source_end_ms <= self.source_start_ms:
            return self.source_start_ms
        last = self.source_end_ms - 1
        return min(max(int(t_source_ms), self.source_start_ms), last)

    def clamp_game_ms(self, t_game_ms: int) -> int:
        """Return ``t_game_ms`` clamped into the mapped game span when bounds exist."""
        start = self.source_start_ms + self.offset_ms
        end = self.source_end_ms + self.offset_ms
        if end <= start:
            return start
        return min(max(int(t_game_ms), start), end - 1)

    def source_to_game(self, t_source_ms: int) -> int | None:
        """Return game ms, or None when uncovered. Does not invent a mapping."""
        if self.mode is ClockMode.UNMAPPED:
            return None
        if self.sync_map is not None:
            return self.sync_map.video_to_game(int(t_source_ms))
        if not self.contains_source(t_source_ms):
            return None
        return int(t_source_ms) + self.offset_ms

    def game_to_source(self, t_game_ms: int) -> int | None:
        """Return source ms, or None when uncovered. Does not invent a mapping."""
        if self.mode is ClockMode.UNMAPPED:
            return None
        if self.sync_map is not None:
            return self.sync_map.game_to_video(int(t_game_ms))
        t_source = int(t_game_ms) - self.offset_ms
        if not self.contains_source(t_source):
            return None
        return t_source

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready mapping. Assumes the clock was already validated."""
        return {
            "mode": self.mode.value,
            "source_start_ms": self.source_start_ms,
            "source_end_ms": self.source_end_ms,
            "offset_ms": self.offset_ms,
            "confidence": self.confidence.value,
            "verified": self.verified,
            "sync_map": None if self.sync_map is None else self.sync_map.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ClockMap:
        """Parse a mapping produced by ``to_dict``. Assumes keys are complete."""
        sync_raw = payload.get("sync_map")
        sync_map = None if sync_raw is None else SyncMap.from_dict(sync_raw)
        return cls(
            mode=ClockMode(str(payload["mode"])),
            source_start_ms=int(payload["source_start_ms"]),
            source_end_ms=int(payload["source_end_ms"]),
            offset_ms=int(payload["offset_ms"]),
            confidence=ClockConfidence(str(payload["confidence"])),
            verified=bool(payload.get("verified", False)),
            sync_map=sync_map,
        )
