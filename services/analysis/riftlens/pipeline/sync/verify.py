"""Independent H.10 verification. Does not re-run RANSAC."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from riftlens.domain.sync_map import PauseInterval, SyncMap
from riftlens.pipeline.sync.filter import AcceptedPoint

HOLDOUT_TOLERANCE_MS = 400
HOLDOUT_FAIL_RATIO = 0.2
PAUSE_GST_TOLERANCE_MS = 5_000


@dataclass(frozen=True)
class VerifyResult:
    """Independent checks that may downgrade or fail a fitted SyncMap."""

    ok: bool
    verified: bool
    reasons: tuple[str, ...]
    holdout_p95_ms: float
    pause_gst_crosschecked: bool


def verify_sync(
    sync: SyncMap,
    holdout: Sequence[AcceptedPoint],
    *,
    pauses: Sequence[PauseInterval],
    pause_end_game_ms: Sequence[int] = (),
) -> VerifyResult:
    """Validate hold-out OCR, residuals, monotonicity, coverage, and pause hints."""
    reasons: list[str] = []
    holdout_p95 = _holdout_p95(sync, holdout, reasons)
    _check_segments(sync, reasons)
    _check_monotonicity(sync, reasons)
    pause_cross = _check_pauses(pauses, pause_end_game_ms, reasons)
    hard_fail = any(
        item.startswith("fail:") for item in reasons
    )
    ok = not hard_fail
    verified = ok and holdout_p95 <= HOLDOUT_TOLERANCE_MS and bool(holdout)
    if not holdout:
        reasons.append("holdout_skipped_sparse")
    if pause_end_game_ms and not pause_cross and pauses:
        reasons.append("pause_gst_unconfirmed")
    return VerifyResult(
        ok=ok,
        verified=verified,
        reasons=tuple(reasons),
        holdout_p95_ms=holdout_p95,
        pause_gst_crosschecked=pause_cross or not pauses,
    )


def split_fit_and_holdout(
    points: Sequence[AcceptedPoint],
    *,
    stride: int = 5,
) -> tuple[list[AcceptedPoint], list[AcceptedPoint]]:
    """Deterministically hold out every ``stride``th point. Does not shuffle."""
    if stride < 2 or len(points) < 10:
        return list(points), []
    fit: list[AcceptedPoint] = []
    hold: list[AcceptedPoint] = []
    for index, point in enumerate(points):
        if index % stride == 0:
            hold.append(point)
        else:
            fit.append(point)
    if len(fit) < 3:
        return list(points), []
    return fit, hold


def _holdout_p95(
    sync: SyncMap,
    holdout: Sequence[AcceptedPoint],
    reasons: list[str],
) -> float:
    if not holdout:
        return 0.0
    residuals: list[float] = []
    misses = 0
    for point in holdout:
        predicted = sync.video_to_game(point.t_video_ms)
        if predicted is None:
            misses += 1
            continue
        residuals.append(float(abs(predicted - point.t_game_ms)))
    if not residuals and holdout:
        reasons.append("fail:holdout_uncovered")
        return 10_000.0
    inliers = [item for item in residuals if item <= HOLDOUT_TOLERANCE_MS]
    denom = max(1, len(holdout))
    inlier_ratio = len(inliers) / denom
    miss_ratio = misses / denom
    if miss_ratio > HOLDOUT_FAIL_RATIO:
        reasons.append("fail:holdout_uncovered")
    if inlier_ratio < (1.0 - HOLDOUT_FAIL_RATIO - 0.05):
        reasons.append("fail:holdout_ratio")
        return 10_000.0 if not inliers else _percentile(sorted(inliers), 95)
    if not inliers:
        return 0.0
    p95 = _percentile(sorted(inliers), 95)
    if p95 > HOLDOUT_TOLERANCE_MS:
        reasons.append("holdout_residual_elevated")
    return p95


def _check_segments(sync: SyncMap, reasons: list[str]) -> None:
    if not sync.segments:
        reasons.append("fail:no_segments")
        return
    last_end = -1
    for segment in sync.segments:
        if segment.video_end_ms <= segment.video_start_ms:
            reasons.append("fail:empty_segment")
        if segment.video_start_ms < last_end:
            reasons.append("fail:overlapping_video_segments")
        last_end = segment.video_end_ms


def _check_monotonicity(sync: SyncMap, reasons: list[str]) -> None:
    last_game: int | None = None
    for segment in sync.segments:
        start_game = segment.video_start_ms + segment.offset_ms
        if last_game is not None and start_game < last_game:
            reasons.append("fail:non_monotonic_mapping")
            return
        last_game = segment.video_end_ms + segment.offset_ms - 1


def _check_pauses(
    pauses: Sequence[PauseInterval],
    pause_end_game_ms: Sequence[int],
    reasons: list[str],
) -> bool:
    if not pauses:
        return True
    if not pause_end_game_ms:
        reasons.append("pause_without_gst")
        return False
    matched = 0
    for pause in pauses:
        if any(
            abs(pause.t_game_ms - end_ms) <= PAUSE_GST_TOLERANCE_MS
            for end_ms in pause_end_game_ms
        ):
            matched += 1
    if matched == 0:
        reasons.append("pause_gst_mismatch")
        return False
    return True


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
