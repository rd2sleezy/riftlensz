"""Separate H.9.1 / H.10 / H.12 VIDEO verdicts. Do not collapse them."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from riftlens.validation.vod_corpus.h10_eval import VodH10Result
from riftlens.validation.vod_corpus.kinds import MediaKind
from riftlens.validation.vod_corpus.manifest import VodEntry

H91Verdict = Literal["PASS", "PARTIAL", "FAIL", "BLOCKED_INSUFFICIENT_CORPUS"]
H10Verdict = Literal["PASS", "PARTIAL", "FAIL", "BLOCKED_INSUFFICIENT_CORPUS"]
H12Verdict = Literal["READY", "PARTIAL", "BLOCKED"]

H10_N_ACCEPTANCE = 10
H10_N_ENGINEERING = 5
H10_MIN_SUCCESS = 9
H10_P95_MS = 500.0


@dataclass(frozen=True)
class CorpusVerdicts:
    """Three independent VIDEO-validation verdicts."""

    h9_1_real_corpus: H91Verdict
    h10_real_vod_acceptance: H10Verdict
    h12_video_readiness: H12Verdict
    n_real_catalogued: int
    n_real_evaluated: int
    n_real_sync_ok: int
    aggregate_checkpoint_p95_ms: float | None
    h10_engineering_5vod_met: bool
    h12_1_runnable: bool
    h12_5_runnable: bool
    h12_6_runnable: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready verdict block."""
        return {
            "H9_1_REAL_CORPUS": self.h9_1_real_corpus,
            "H10_REAL_VOD_ACCEPTANCE": self.h10_real_vod_acceptance,
            "H12_VIDEO_READINESS": self.h12_video_readiness,
            "n_real_catalogued": self.n_real_catalogued,
            "n_real_evaluated": self.n_real_evaluated,
            "n_real_sync_ok": self.n_real_sync_ok,
            "aggregate_checkpoint_p95_ms": self.aggregate_checkpoint_p95_ms,
            "h10_engineering_5vod_met": self.h10_engineering_5vod_met,
            "h12_1_runnable": self.h12_1_runnable,
            "h12_5_runnable": self.h12_5_runnable,
            "h12_6_runnable": self.h12_6_runnable,
            "reasons": list(self.reasons),
        }


def h9_1_verdict(
    *,
    n_real_clean: int,
    n_held_out_clean: int,
    n_matches: int,
    n_resolutions: int,
    has_early: bool,
    has_late: bool,
    confident_wrong: int,
    held_out_accuracy: float | None,
) -> tuple[H91Verdict, str]:
    """Score REAL clock-crop generalization. Atlas-match crops are not held-out."""
    if confident_wrong > 0:
        return "FAIL", "confidently wrong REAL clock reads are present"
    if n_real_clean <= 0:
        return "BLOCKED_INSUFFICIENT_CORPUS", "no REAL labelled clock crops"
    diverse = n_matches >= 2 and n_resolutions >= 2 and has_early and has_late
    if n_held_out_clean <= 0 or not diverse:
        return (
            "PARTIAL",
            "REAL crops exist but held-out match/resolution/phase coverage is incomplete",
        )
    if held_out_accuracy is not None and held_out_accuracy >= 0.99:
        return "PASS", "held-out REAL accuracy meets the product gate"
    return "PARTIAL", "held-out REAL accuracy is below the 99% product gate"


def h10_verdict(results: Sequence[VodH10Result]) -> tuple[H10Verdict, bool, str]:
    """Score REAL VOD auto-sync. R10-CLIP / synthetic rows are ignored."""
    real = [row for row in results if row.counts_toward_acceptance and row.media_resolved]
    n = len(real)
    successes = [row for row in real if row.sync_ok and row.failure_class != "wrong_sync"]
    p95s = [row.checkpoint_p95_ms for row in successes if row.checkpoint_p95_ms is not None]
    agg_ok = (max(p95s) <= H10_P95_MS) if p95s else False
    engineering = (
        n >= H10_N_ENGINEERING
        and len(successes) == n
        and all(row.verified for row in successes)
        and agg_ok
    )
    if n < H10_N_ENGINEERING:
        return (
            "BLOCKED_INSUFFICIENT_CORPUS",
            False,
            f"REAL VODs evaluated: {n} "
            f"(need ≥{H10_N_ENGINEERING} engineering / ≥{H10_N_ACCEPTANCE} acceptance)",
        )
    if n < H10_N_ACCEPTANCE:
        status: H10Verdict = "PARTIAL" if engineering else "BLOCKED_INSUFFICIENT_CORPUS"
        if not engineering and n >= H10_N_ENGINEERING:
            status = "PARTIAL"
        return status, engineering, f"REAL VODs evaluated: {n} of {H10_N_ACCEPTANCE} required"
    if len(successes) >= H10_MIN_SUCCESS and agg_ok:
        return (
            "PASS",
            True,
            f"{len(successes)}/{n} REAL auto-sync with checkpoint p95 ≤ {H10_P95_MS} ms",
        )
    if len(successes) == 0:
        return "FAIL", False, "no REAL auto-sync succeeded"
    return (
        "PARTIAL",
        engineering,
        f"{len(successes)}/{n} REAL auto-sync; acceptance needs ≥{H10_MIN_SUCCESS}/10",
    )


def h12_readiness(
    *,
    h9: H91Verdict,
    h10: H10Verdict,
    n_real: int,
    has_30min: bool,
    bench_passed: bool | None,
) -> tuple[H12Verdict, bool, bool, bool, str]:
    """Whether H.12 VIDEO gates #1, #5, #6 can be attempted honestly."""
    gate1 = n_real >= 10 and h9 in {"PASS", "PARTIAL"}
    gate5 = n_real >= 10
    gate6 = has_30min
    if h10 == "PASS" and gate1 and gate6 and bench_passed:
        return "READY", True, True, True, "H.12 VIDEO gates 1/5/6 are runnable with a real corpus"
    if n_real == 0 and not has_30min:
        return (
            "BLOCKED",
            False,
            False,
            False,
            "no REAL full/partial user VODs; H.12 #1 #5 #6 cannot be attempted",
        )
    return (
        "PARTIAL",
        gate1,
        gate5,
        gate6,
        "some VIDEO evidence exists but H.12 DoD is not fully unblocked",
    )


def compute_verdicts(
    *,
    entries: Sequence[VodEntry],
    h10_results: Sequence[VodH10Result],
    n_real_clean: int,
    n_held_out_clean: int,
    n_matches: int,
    n_resolutions: int,
    has_early: bool,
    has_late: bool,
    confident_wrong: int,
    held_out_accuracy: float | None,
    has_30min: bool,
    bench_passed: bool | None,
) -> CorpusVerdicts:
    """Combine OCR + H.10 + 30-minute evidence into three verdicts."""
    h9, h9_reason = h9_1_verdict(
        n_real_clean=n_real_clean,
        n_held_out_clean=n_held_out_clean,
        n_matches=n_matches,
        n_resolutions=n_resolutions,
        has_early=has_early,
        has_late=has_late,
        confident_wrong=confident_wrong,
        held_out_accuracy=held_out_accuracy,
    )
    h10, engineering, h10_reason = h10_verdict(h10_results)
    real_n = sum(1 for item in entries if item.kind is MediaKind.REAL)
    evaluated = [row for row in h10_results if row.counts_toward_acceptance and row.media_resolved]
    ok = [row for row in evaluated if row.sync_ok and row.failure_class != "wrong_sync"]
    p95s = [row.checkpoint_p95_ms for row in ok if row.checkpoint_p95_ms is not None]
    h12, g1, g5, g6, h12_reason = h12_readiness(
        h9=h9,
        h10=h10,
        n_real=real_n,
        has_30min=has_30min,
        bench_passed=bench_passed,
    )
    return CorpusVerdicts(
        h9_1_real_corpus=h9,
        h10_real_vod_acceptance=h10,
        h12_video_readiness=h12,
        n_real_catalogued=real_n,
        n_real_evaluated=len(evaluated),
        n_real_sync_ok=len(ok),
        aggregate_checkpoint_p95_ms=max(p95s) if p95s else None,
        h10_engineering_5vod_met=engineering,
        h12_1_runnable=g1,
        h12_5_runnable=g5,
        h12_6_runnable=g6,
        reasons=(h9_reason, h10_reason, h12_reason),
    )
