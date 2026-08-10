from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

SyncMethod = Literal["clock_ocr", "manual", "event_correlation", "hybrid"]
SyncVerdict = Literal["EXCELLENT", "GOOD", "DEGRADED", "FAILED"]
SEEK_LEAD_IN_MS = 8_000
_SLOPE_TOLERANCE = 0.02


class SyncAnchorInconsistent(ValueError):
    """Raised when manual anchors imply a slope outside ``1.0 ± 0.02``."""


@dataclass(frozen=True)
class PauseInterval:
    """A pause where game time is frozen while video time advances."""

    video_start_ms: int
    video_end_ms: int
    t_game_ms: int


@dataclass(frozen=True)
class SyncSegment:
    """One piecewise-linear piece: ``t_game = t_video + offset_ms`` (slope 1.0)."""

    video_start_ms: int
    video_end_ms: int
    offset_ms: int
    n_anchors: int
    residual_p95_ms: float

    def contains_video(self, t_video_ms: int) -> bool:
        """Return True when ``t_video_ms`` is inside this segment (end exclusive)."""
        return self.video_start_ms <= t_video_ms < self.video_end_ms

    def contains_game(self, t_game_ms: int) -> bool:
        """Return True when ``t_game_ms`` falls inside the mapped game range."""
        start = self.video_start_ms + self.offset_ms
        end = self.video_end_ms + self.offset_ms
        return start <= t_game_ms < end


@dataclass(frozen=True)
class SyncQuality:
    """Residual stats and a §8.3 verdict. Assumes counts are non-negative."""

    method: str
    n_readings: int
    n_inliers: int
    inlier_ratio: float
    residual_p50_ms: float
    residual_p95_ms: float
    coverage: float
    n_segments: int
    verdict: SyncVerdict


@dataclass(frozen=True)
class SeekTarget:
    """Review-item → finding ``t_ms`` → VOD time. Missing times stay None."""

    t_game_ms: int
    t_video_ms: int | None
    seek_video_ms: int | None
    covered: bool
    uncertain: bool
    reason: str | None


@dataclass(frozen=True)
class SyncMap:
    """Piecewise video↔game mapping. Times are integer milliseconds."""

    segments: tuple[SyncSegment, ...]
    pauses: tuple[PauseInterval, ...]
    quality: SyncQuality
    media_asset_id: str
    match_id: str
    version: int
    verified: bool = False

    def video_to_game(self, t_video_ms: int) -> int | None:
        """Return game ms for a video timestamp, or None when uncovered."""
        segment = self._segment_for_video(t_video_ms)
        if segment is None:
            return None
        return int(t_video_ms) + segment.offset_ms

    def game_to_video(self, t_game_ms: int) -> int | None:
        """Return video ms for a game timestamp, or None when uncovered."""
        segment = self._segment_for_game(t_game_ms)
        if segment is None:
            return None
        return int(t_game_ms) - segment.offset_ms

    def covers_game(self, t_game_ms: int) -> bool:
        """Return True when ``game_to_video`` would succeed."""
        return self._segment_for_game(t_game_ms) is not None

    def covers_video(self, t_video_ms: int) -> bool:
        """Return True when ``video_to_game`` would succeed."""
        return self._segment_for_video(t_video_ms) is not None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready mapping. Assumes segments are already validated."""
        return {
            "segments": [
                {
                    "video_start_ms": item.video_start_ms,
                    "video_end_ms": item.video_end_ms,
                    "offset_ms": item.offset_ms,
                    "n_anchors": item.n_anchors,
                    "residual_p95_ms": item.residual_p95_ms,
                }
                for item in self.segments
            ],
            "pauses": [
                {
                    "video_start_ms": item.video_start_ms,
                    "video_end_ms": item.video_end_ms,
                    "t_game_ms": item.t_game_ms,
                }
                for item in self.pauses
            ],
            "quality": {
                "method": self.quality.method,
                "n_readings": self.quality.n_readings,
                "n_inliers": self.quality.n_inliers,
                "inlier_ratio": self.quality.inlier_ratio,
                "residual_p50_ms": self.quality.residual_p50_ms,
                "residual_p95_ms": self.quality.residual_p95_ms,
                "coverage": self.quality.coverage,
                "n_segments": self.quality.n_segments,
                "verdict": self.quality.verdict,
            },
            "media_asset_id": self.media_asset_id,
            "match_id": self.match_id,
            "version": self.version,
            "verified": self.verified,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SyncMap:
        """Parse a mapping produced by ``to_dict``. Assumes keys are complete."""
        segments = tuple(
            SyncSegment(
                video_start_ms=int(item["video_start_ms"]),
                video_end_ms=int(item["video_end_ms"]),
                offset_ms=int(item["offset_ms"]),
                n_anchors=int(item["n_anchors"]),
                residual_p95_ms=float(item["residual_p95_ms"]),
            )
            for item in payload["segments"]
        )
        pauses = tuple(
            PauseInterval(
                video_start_ms=int(item["video_start_ms"]),
                video_end_ms=int(item["video_end_ms"]),
                t_game_ms=int(item["t_game_ms"]),
            )
            for item in payload.get("pauses", ())
        )
        quality_raw = payload["quality"]
        quality = SyncQuality(
            method=str(quality_raw["method"]),
            n_readings=int(quality_raw["n_readings"]),
            n_inliers=int(quality_raw["n_inliers"]),
            inlier_ratio=float(quality_raw["inlier_ratio"]),
            residual_p50_ms=float(quality_raw["residual_p50_ms"]),
            residual_p95_ms=float(quality_raw["residual_p95_ms"]),
            coverage=float(quality_raw["coverage"]),
            n_segments=int(quality_raw["n_segments"]),
            verdict=cast(SyncVerdict, str(quality_raw["verdict"])),
        )
        return cls(
            segments=segments,
            pauses=pauses,
            quality=quality,
            media_asset_id=str(payload["media_asset_id"]),
            match_id=str(payload["match_id"]),
            version=int(payload["version"]),
            verified=bool(payload.get("verified", False)),
        )

    def _segment_for_video(self, t_video_ms: int) -> SyncSegment | None:
        for segment in self.segments:
            if segment.contains_video(t_video_ms):
                return segment
        return None

    def _segment_for_game(self, t_game_ms: int) -> SyncSegment | None:
        for segment in self.segments:
            if segment.contains_game(t_game_ms):
                return segment
        return None


def build_manual_sync(
    anchors: Sequence[tuple[int, int]],
    *,
    video_duration_ms: int,
    match_id: str,
    media_asset_id: str = "",
    match_duration_ms: int | None = None,
) -> SyncMap:
    """Build a slope-1.0 SyncMap from ``(t_video_ms, t_game_ms)`` anchors.

    Assumes times are integer milliseconds. One anchor yields a single segment
    spanning the video. Two or more must imply slope within ``1.0 ± 0.02``.
    """
    if video_duration_ms <= 0:
        raise ValueError("video_duration_ms must be positive")
    if not anchors:
        raise ValueError("at least one sync anchor is required")
    cleaned = _sorted_unique_anchors(anchors)
    offset, residual_p50, residual_p95 = _fit_fixed_slope(cleaned)
    if len(cleaned) >= 2:
        _assert_slope_near_one(cleaned)
    coverage = _manual_coverage(offset, video_duration_ms, match_duration_ms)
    verdict = _manual_verdict(len(cleaned), residual_p95, coverage)
    quality = SyncQuality(
        method="manual",
        n_readings=len(cleaned),
        n_inliers=len(cleaned),
        inlier_ratio=1.0,
        residual_p50_ms=residual_p50,
        residual_p95_ms=residual_p95,
        coverage=coverage,
        n_segments=1,
        verdict=verdict,
    )
    segment = SyncSegment(
        video_start_ms=0,
        video_end_ms=int(video_duration_ms),
        offset_ms=offset,
        n_anchors=len(cleaned),
        residual_p95_ms=residual_p95,
    )
    return SyncMap(
        segments=(segment,),
        pauses=(),
        quality=quality,
        media_asset_id=media_asset_id,
        match_id=match_id,
        version=1,
        verified=False,
    )


def seek_target(
    sync: SyncMap | None,
    t_game_ms: int,
    *,
    lead_in_ms: int = SEEK_LEAD_IN_MS,
) -> SeekTarget:
    """Map a finding ``t_ms`` to VOD time. Does not invent uncovered timestamps."""
    if sync is None:
        return SeekTarget(
            t_game_ms=t_game_ms,
            t_video_ms=None,
            seek_video_ms=None,
            covered=False,
            uncertain=True,
            reason="No sync map — VOD time is unknown until you set a clock anchor.",
        )
    if not sync.covers_game(t_game_ms):
        return SeekTarget(
            t_game_ms=t_game_ms,
            t_video_ms=None,
            seek_video_ms=None,
            covered=False,
            uncertain=True,
            reason="Recording does not cover this game time.",
        )
    t_video = sync.game_to_video(t_game_ms)
    if t_video is None:
        return SeekTarget(
            t_game_ms=t_game_ms,
            t_video_ms=None,
            seek_video_ms=None,
            covered=False,
            uncertain=True,
            reason="Recording does not cover this game time.",
        )
    uncertain = sync.quality.verdict in {"DEGRADED", "FAILED"} or not sync.verified
    reason = None
    if uncertain:
        reason = _uncertainty_reason(sync)
    seek_at = max(0, t_video - max(0, lead_in_ms))
    return SeekTarget(
        t_game_ms=t_game_ms,
        t_video_ms=t_video,
        seek_video_ms=seek_at,
        covered=True,
        uncertain=uncertain,
        reason=reason,
    )


def _sorted_unique_anchors(anchors: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    cleaned = [(int(video), int(game)) for video, game in anchors]
    cleaned.sort(key=lambda pair: pair[0])
    return cleaned


def _assert_slope_near_one(anchors: Sequence[tuple[int, int]]) -> None:
    first_video, first_game = anchors[0]
    last_video, last_game = anchors[-1]
    delta_video = last_video - first_video
    if delta_video == 0:
        raise SyncAnchorInconsistent("anchors share the same video time; cannot check slope")
    slope = (last_game - first_game) / delta_video
    if abs(slope - 1.0) > _SLOPE_TOLERANCE:
        raise SyncAnchorInconsistent(
            f"anchors imply slope {slope:.4f}, outside 1.0 ± {_SLOPE_TOLERANCE}"
        )


def _fit_fixed_slope(anchors: Sequence[tuple[int, int]]) -> tuple[int, float, float]:
    offsets = [game - video for video, game in anchors]
    offset = int(round(sum(offsets) / len(offsets)))
    residuals = sorted(abs((game - video) - offset) for video, game in anchors)
    return offset, _percentile(residuals, 50), _percentile(residuals, 95)


def _percentile(sorted_values: Sequence[float], pct: int) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    frac = rank - lower
    return float(sorted_values[lower] * (1.0 - frac) + sorted_values[upper] * frac)


def _manual_coverage(
    offset_ms: int, video_duration_ms: int, match_duration_ms: int | None
) -> float:
    if match_duration_ms is None or match_duration_ms <= 0:
        return 1.0
    game_start = offset_ms
    game_end = offset_ms + video_duration_ms
    overlap = max(0, min(game_end, match_duration_ms) - max(game_start, 0))
    return max(0.0, min(1.0, overlap / match_duration_ms))


def _manual_verdict(n_anchors: int, residual_p95_ms: float, coverage: float) -> SyncVerdict:
    if n_anchors < 1:
        return "FAILED"
    if n_anchors == 1:
        return "DEGRADED"
    if residual_p95_ms < 300 and coverage > 0.9:
        return "GOOD"
    if residual_p95_ms < 700:
        return "DEGRADED"
    return "FAILED"


def _uncertainty_reason(sync: SyncMap) -> str:
    if sync.quality.verdict == "FAILED":
        return "Sync failed quality checks — do not treat VOD times as exact."
    if sync.quality.n_readings < 2:
        return "Single-anchor sync is approximate. A second clock reading would confirm it."
    if not sync.verified:
        return "Sync is not independently verified against in-game events."
    return "Sync confidence is limited."
