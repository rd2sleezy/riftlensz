"""Pre-fit ClockReading filters. Does not repair OCR values."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from riftlens.domain.clock_reading import ClockReading

CONFIDENCE_GATE = 0.8
MAX_GAME_MS = 90 * 60 * 1000


@dataclass(frozen=True)
class AcceptedPoint:
    """One confident integer-ms (video, game) pair used by the fitter."""

    t_video_ms: int
    t_game_ms: int
    confidence: float


@dataclass(frozen=True)
class FilterReport:
    """Accepted/rejected counts. Reasons are fail-closed labels, not repairs."""

    accepted: int
    rejected: int
    reason_counts: dict[str, int]


def filter_readings(
    readings: Sequence[ClockReading],
    *,
    confidence_gate: float = CONFIDENCE_GATE,
) -> tuple[list[AcceptedPoint], FilterReport]:
    """Return confident monotonic-video points. Repeated game times are kept."""
    reasons: Counter[str] = Counter()
    accepted: list[AcceptedPoint] = []
    last_video: int | None = None
    for reading in readings:
        reason = _reject_reason(reading, last_video=last_video, gate=confidence_gate)
        if reason is not None:
            reasons[reason] += 1
            continue
        assert reading.t_game_ms is not None
        accepted.append(
            AcceptedPoint(
                t_video_ms=int(reading.t_video_ms),
                t_game_ms=int(reading.t_game_ms),
                confidence=float(reading.confidence),
            )
        )
        last_video = int(reading.t_video_ms)
    accepted.sort(key=lambda item: item.t_video_ms)
    report = FilterReport(
        accepted=len(accepted),
        rejected=sum(reasons.values()),
        reason_counts=dict(reasons),
    )
    return accepted, report


def _reject_reason(
    reading: ClockReading,
    *,
    last_video: int | None,
    gate: float,
) -> str | None:
    if reading.t_game_ms is None:
        return "missing_game"
    if reading.confidence < gate:
        return "low_confidence"
    if reading.t_video_ms < 0 or reading.t_game_ms < 0:
        return "negative_time"
    if reading.t_game_ms > MAX_GAME_MS:
        return "over_90_min"
    if last_video is not None and reading.t_video_ms < last_video:
        return "non_monotonic_video"
    return None
