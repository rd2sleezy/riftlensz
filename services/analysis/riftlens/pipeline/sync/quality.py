"""SyncQuality verdict policy. Does not claim EXCELLENT on sparse evidence."""

from __future__ import annotations

from collections.abc import Sequence

from riftlens.domain.sync_map import SyncQuality, SyncSegment, SyncVerdict
from riftlens.pipeline.sync.filter import AcceptedPoint, FilterReport

MIN_EXCELLENT_READINGS = 30
MIN_GOOD_READINGS = 10
MIN_MODEL_READINGS = 3


def build_quality(
    *,
    method: str,
    accepted: Sequence[AcceptedPoint],
    inliers: Sequence[AcceptedPoint],
    segments: Sequence[SyncSegment],
    residual_p50_ms: float,
    residual_p95_ms: float,
    coverage: float,
    verified: bool,
    filter_report: FilterReport,
    verify_ok: bool,
    sparse: bool,
    pause_crosschecked: bool,
) -> SyncQuality:
    """Return residual stats plus a transparent verdict."""
    n_readings = filter_report.accepted + filter_report.rejected
    n_inliers = len(inliers)
    ratio = 0.0 if not accepted else n_inliers / max(1, len(accepted))
    verdict = _verdict(
        n_accepted=len(accepted),
        inlier_ratio=ratio,
        residual_p95_ms=residual_p95_ms,
        coverage=coverage,
        verified=verified,
        verify_ok=verify_ok,
        sparse=sparse,
        pause_crosschecked=pause_crosschecked,
        n_segments=len(segments),
    )
    return SyncQuality(
        method=method,
        n_readings=n_readings,
        n_inliers=n_inliers,
        inlier_ratio=ratio,
        residual_p50_ms=residual_p50_ms,
        residual_p95_ms=residual_p95_ms,
        coverage=coverage,
        n_segments=len(segments),
        verdict=verdict,
    )


def _verdict(
    *,
    n_accepted: int,
    inlier_ratio: float,
    residual_p95_ms: float,
    coverage: float,
    verified: bool,
    verify_ok: bool,
    sparse: bool,
    pause_crosschecked: bool,
    n_segments: int,
) -> SyncVerdict:
    if n_accepted < MIN_MODEL_READINGS or n_segments < 1 or not verify_ok:
        return "FAILED"
    if residual_p95_ms >= 700 or inlier_ratio < 0.5:
        return "FAILED"
    excellent = (
        n_accepted >= MIN_EXCELLENT_READINGS
        and inlier_ratio >= 0.9
        and residual_p95_ms < 200
        and coverage >= 0.8
        and verified
        and not sparse
        and pause_crosschecked
    )
    if excellent:
        return "EXCELLENT"
    good = (
        n_accepted >= MIN_GOOD_READINGS
        and inlier_ratio >= 0.8
        and residual_p95_ms < 400
        and coverage >= 0.4
        and verify_ok
        and not sparse
    )
    if good:
        return "GOOD"
    return "DEGRADED"
