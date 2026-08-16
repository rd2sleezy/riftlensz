"""Constrained RANSAC + piecewise slope-1.0 SyncMap fitting (Technical Design §8.3)."""

from __future__ import annotations

import random
import time
from collections.abc import Sequence
from dataclasses import dataclass

from riftlens.domain.clock_map import ClockMap
from riftlens.domain.clock_reading import ClockReading
from riftlens.domain.sync_map import SyncMap, SyncSegment
from riftlens.pipeline.sync.errors import (
    InconsistentOcrStream,
    InsufficientCoverage,
    InsufficientReadings,
    MultipleGamesDetected,
    NoStableModel,
    VerificationFailed,
)
from riftlens.pipeline.sync.filter import (
    CONFIDENCE_GATE,
    AcceptedPoint,
    FilterReport,
    filter_readings,
)
from riftlens.pipeline.sync.quality import MIN_MODEL_READINGS, build_quality
from riftlens.pipeline.sync.segments import (
    detect_multiple_games,
    detect_pauses,
    points_outside_pauses,
    split_linear_groups,
)
from riftlens.pipeline.sync.verify import VerifyResult, split_fit_and_holdout, verify_sync

ALGO_VERSION = "h10.clock_ocr.v1"
RANSAC_SEED = 10
RANSAC_ITERATIONS = 200
SLOPE_TOLERANCE = 0.02
INLIER_TOLERANCE_MS = 400
MIN_COVERAGE = 0.05


@dataclass(frozen=True)
class AutoFitResult:
    """Fitted VIDEO SyncMap plus filter/verify metrics. Not a cache record."""

    sync_map: SyncMap
    clock_map: ClockMap
    filter_report: FilterReport
    verify: VerifyResult
    fit_ms: int
    verify_ms: int
    reasons: tuple[str, ...]


def fit_auto_sync(
    readings: Sequence[ClockReading],
    *,
    match_id: str,
    media_asset_id: str = "",
    video_duration_ms: int,
    match_duration_ms: int | None = None,
    pause_end_game_ms: Sequence[int] = (),
    confidence_gate: float = CONFIDENCE_GATE,
    seed: int = RANSAC_SEED,
) -> AutoFitResult:
    """Fit a piecewise slope-1.0 SyncMap from OCR readings. Does not persist."""
    if video_duration_ms <= 0:
        raise NoStableModel("video_duration_ms must be positive")
    started = time.perf_counter()
    accepted, report = filter_readings(readings, confidence_gate=confidence_gate)
    if report.reason_counts.get("non_monotonic_video", 0) > max(3, report.accepted // 4):
        raise InconsistentOcrStream(
            "OCR stream is not monotonically increasing in video time.",
            details={"filter": report.reason_counts},
        )
    if len(accepted) < MIN_MODEL_READINGS:
        raise InsufficientReadings(
            f"Need at least {MIN_MODEL_READINGS} confident clock readings; got {len(accepted)}.",
            details={"filter": report.reason_counts, "accepted": report.accepted},
        )
    detect_multiple_games(accepted)
    pauses = detect_pauses(accepted)
    linear_points = points_outside_pauses(accepted, pauses)
    if len(linear_points) < MIN_MODEL_READINGS:
        raise InsufficientReadings(
            "Pause-dominated OCR stream does not leave enough linear samples.",
            details={"accepted": report.accepted, "pauses": len(pauses)},
        )
    groups = split_linear_groups(linear_points)
    fit_points, holdout = split_fit_and_holdout(linear_points)
    rng = random.Random(seed)
    segments, inliers, residuals = _fit_groups(groups, fit_points, rng)
    if not segments:
        raise NoStableModel("No stable slope-constrained model from OCR readings.")
    overlap_at = _segment_game_overlap(segments)
    if overlap_at is not None:
        raise MultipleGamesDetected(
            "Piecewise offsets imply overlapping League games in one video.",
            boundaries_video_ms=(overlap_at,),
        )
    linear_video = {item.t_video_ms for item in linear_points}
    scored_inliers = list(inliers) + [
        item for item in accepted if item.t_video_ms not in linear_video
    ]
    coverage = _coverage(segments, video_duration_ms, match_duration_ms)
    if coverage < MIN_COVERAGE:
        raise InsufficientCoverage(
            "Automatic sync covers too little of the recording.",
            details={"coverage": coverage},
        )
    residual_p50 = _percentile(residuals, 50)
    residual_p95 = _percentile(residuals, 95)
    fit_ms = max(0, int(round((time.perf_counter() - started) * 1000.0)))
    draft = SyncMap(
        segments=tuple(segments),
        pauses=pauses,
        quality=build_quality(
            method="clock_ocr",
            accepted=accepted,
            inliers=scored_inliers,
            segments=segments,
            residual_p50_ms=residual_p50,
            residual_p95_ms=residual_p95,
            coverage=coverage,
            verified=False,
            filter_report=report,
            verify_ok=True,
            sparse=len(accepted) < 10,
            pause_crosschecked=not pauses,
        ),
        media_asset_id=media_asset_id,
        match_id=match_id,
        version=1,
        verified=False,
    )
    verify_started = time.perf_counter()
    verify = verify_sync(
        draft, holdout, pauses=pauses, pause_end_game_ms=pause_end_game_ms
    )
    verify_ms = max(0, int(round((time.perf_counter() - verify_started) * 1000.0)))
    if not verify.ok:
        raise VerificationFailed(
            "Independent verification rejected the automatic sync.",
            details={"reasons": list(verify.reasons)},
        )
    sparse = len(accepted) < 10
    quality = build_quality(
        method="clock_ocr",
        accepted=accepted,
        inliers=scored_inliers,
        segments=segments,
        residual_p50_ms=residual_p50,
        residual_p95_ms=residual_p95,
        coverage=coverage,
        verified=verify.verified,
        filter_report=report,
        verify_ok=verify.ok,
        sparse=sparse,
        pause_crosschecked=verify.pause_gst_crosschecked,
    )
    if quality.verdict == "FAILED":
        raise NoStableModel(
            "Automatic sync did not meet minimum quality.",
            details={"residual_p95_ms": residual_p95, "inlier_ratio": quality.inlier_ratio},
        )
    sync = SyncMap(
        segments=tuple(segments),
        pauses=pauses,
        quality=quality,
        media_asset_id=media_asset_id,
        match_id=match_id,
        version=1,
        verified=verify.verified,
    )
    return AutoFitResult(
        sync_map=sync,
        clock_map=ClockMap.from_sync_map(sync),
        filter_report=report,
        verify=verify,
        fit_ms=fit_ms,
        verify_ms=verify_ms,
        reasons=verify.reasons,
    )


def _fit_groups(
    groups: Sequence[Sequence[AcceptedPoint]],
    fit_points: Sequence[AcceptedPoint],
    rng: random.Random,
) -> tuple[list[SyncSegment], list[AcceptedPoint], list[float]]:
    fit_ids = {(item.t_video_ms, item.t_game_ms) for item in fit_points}
    segments: list[SyncSegment] = []
    all_inliers: list[AcceptedPoint] = []
    residuals: list[float] = []
    for group in groups:
        if len(group) < 3:
            continue
        working = [item for item in group if (item.t_video_ms, item.t_game_ms) in fit_ids]
        if len(working) < 2:
            working = list(group)
        inliers = constrained_ransac(working, rng=rng)
        if len(inliers) < 3:
            continue
        offset, p95, group_residuals = _fit_offset(inliers)
        span = [
            item
            for item in group
            if abs((item.t_game_ms - item.t_video_ms) - offset) <= INLIER_TOLERANCE_MS
        ]
        if not span:
            span = inliers
        start = min(item.t_video_ms for item in span)
        end = max(item.t_video_ms for item in span) + 1
        segments.append(
            SyncSegment(
                video_start_ms=start,
                video_end_ms=end,
                offset_ms=offset,
                n_anchors=len(inliers),
                residual_p95_ms=p95,
            )
        )
        all_inliers.extend(span)
        residuals.extend(group_residuals)
    segments.sort(key=lambda item: item.video_start_ms)
    return segments, all_inliers, residuals


def _segment_game_overlap(segments: Sequence[SyncSegment]) -> int | None:
    """Return a video-ms boundary when fitted segments cover overlapping game times."""
    last_end = -1
    for segment in segments:
        start = segment.video_start_ms + segment.offset_ms
        end = segment.video_end_ms + segment.offset_ms
        if start < last_end:
            return segment.video_start_ms
        last_end = max(last_end, end)
    return None


def constrained_ransac(
    points: Sequence[AcceptedPoint],
    *,
    rng: random.Random,
    iterations: int = RANSAC_ITERATIONS,
    inlier_ms: int = INLIER_TOLERANCE_MS,
    slope_tol: float = SLOPE_TOLERANCE,
) -> list[AcceptedPoint]:
    """Fit ``t_game ≈ a * t_video + b`` with ``|a-1| <= 0.02``. Deterministic given ``rng``."""
    if len(points) <= 2:
        return list(points)
    best: list[AcceptedPoint] = []
    for _ in range(iterations):
        first, second = rng.sample(list(points), 2)
        delta_video = second.t_video_ms - first.t_video_ms
        if delta_video == 0:
            continue
        slope = (second.t_game_ms - first.t_game_ms) / delta_video
        if abs(slope - 1.0) > slope_tol:
            continue
        intercept = first.t_game_ms - slope * first.t_video_ms
        inliers = [
            point
            for point in points
            if abs(point.t_game_ms - (slope * point.t_video_ms + intercept)) <= inlier_ms
        ]
        if len(inliers) > len(best):
            best = inliers
    if best:
        return best
    return _slope_one_inliers(points, inlier_ms=inlier_ms)


def _slope_one_inliers(
    points: Sequence[AcceptedPoint], *, inlier_ms: int
) -> list[AcceptedPoint]:
    offset = _median_int([item.t_game_ms - item.t_video_ms for item in points])
    return [
        item for item in points if abs((item.t_game_ms - item.t_video_ms) - offset) <= inlier_ms
    ]


def _fit_offset(inliers: Sequence[AcceptedPoint]) -> tuple[int, float, list[float]]:
    offsets = [item.t_game_ms - item.t_video_ms for item in inliers]
    offset = _median_int(offsets)
    residuals = sorted(abs(value - offset) for value in offsets)
    return offset, _percentile(residuals, 95), [float(item) for item in residuals]


def _coverage(
    segments: Sequence[SyncSegment],
    video_duration_ms: int,
    match_duration_ms: int | None,
) -> float:
    mapped = sum(max(0, item.video_end_ms - item.video_start_ms) for item in segments)
    video_cov = mapped / max(1, video_duration_ms)
    if match_duration_ms is None or match_duration_ms <= 0:
        return max(0.0, min(1.0, video_cov))
    overlap = 0
    for item in segments:
        start = item.video_start_ms + item.offset_ms
        end = item.video_end_ms + item.offset_ms
        overlap += max(0, min(end, match_duration_ms) - max(start, 0))
    match_cov = overlap / match_duration_ms
    return max(0.0, min(1.0, max(video_cov, match_cov * 0.5 + video_cov * 0.5)))


def _median_int(values: Sequence[int]) -> int:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return int(round((ordered[mid - 1] + ordered[mid]) / 2.0))


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
