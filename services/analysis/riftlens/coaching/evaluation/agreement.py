"""Lightweight inter-rater agreement summaries (no extra dependencies)."""

from __future__ import annotations

from collections.abc import Sequence

from riftlens.coaching.evaluation.models import (
    AgreementSummary,
    HardFailKind,
    HumanEvaluation,
    PairwisePreference,
    RubricDimension,
)
from riftlens.coaching.evaluation.rubric import ordinal_value


def summarize_agreement(
    evaluations: Sequence[HumanEvaluation],
    *,
    within_one: int = 1,
) -> AgreementSummary:
    """Compute exact / within-one / pairwise / hard-fail agreement rates."""
    by_case: dict[str, list[HumanEvaluation]] = {}
    for item in evaluations:
        by_case.setdefault(item.case_id, []).append(item)

    exact_hits = 0
    exact_total = 0
    within_hits = 0
    within_total = 0
    pairwise_hits = 0
    pairwise_total = 0
    hf_hits = 0
    hf_total = 0
    pairs = 0

    for group in by_case.values():
        if len(group) < 2:
            continue
        # Compare first two (and note adjudication seam for more)
        left, right = group[0], group[1]
        pairs += 1
        for dim in RubricDimension:
            lo = _score_for(left, dim)
            ro = _score_for(right, dim)
            if lo is None or ro is None:
                continue
            exact_total += 1
            within_total += 1
            if lo == ro:
                exact_hits += 1
                within_hits += 1
            elif abs(lo - ro) <= within_one:
                within_hits += 1

        if left.pairwise is not None and right.pairwise is not None:
            pairwise_total += 1
            if _pairwise_agree(left.pairwise, right.pairwise):
                pairwise_hits += 1

        hf_total += 1
        if set(left.hard_fail_flags) == set(right.hard_fail_flags):
            hf_hits += 1

    caveats = (
        "Small-N agreement is descriptive only; not statistically validated.",
        "Only first two raters per case compared in this lightweight summary.",
    )
    return AgreementSummary(
        exact_agreement_rate=_rate(exact_hits, exact_total),
        within_one_agreement_rate=_rate(within_hits, within_total),
        pairwise_agreement_rate=_rate(pairwise_hits, pairwise_total),
        hard_fail_agreement_rate=_rate(hf_hits, hf_total),
        n_pairs=pairs,
        caveats=caveats,
    )


def adjudication_needed(
    left: HumanEvaluation,
    right: HumanEvaluation,
    *,
    score_delta: int = 2,
) -> bool:
    """Return True when hard-fail disagreement or large ordinal disagreement."""
    if set(left.hard_fail_flags) != set(right.hard_fail_flags):
        return True
    for dim in RubricDimension:
        lo = _score_for(left, dim)
        ro = _score_for(right, dim)
        if lo is None or ro is None:
            continue
        if abs(lo - ro) >= score_delta:
            return True
    return False


def _score_for(evaluation: HumanEvaluation, dim: RubricDimension) -> int | None:
    for rating in evaluation.rubric_scores:
        if rating.dimension is dim:
            return ordinal_value(rating.score)
    return None


def _pairwise_agree(a: PairwisePreference, b: PairwisePreference) -> bool:
    if a is b:
        return True
    # Treat slight/clear same direction as agreement for lightweight summary
    a_side = _side(a)
    b_side = _side(b)
    return a_side is not None and a_side == b_side


def _side(pref: PairwisePreference) -> str | None:
    if pref in {
        PairwisePreference.A_CLEARLY_BETTER,
        PairwisePreference.A_SLIGHTLY_BETTER,
    }:
        return "A"
    if pref in {
        PairwisePreference.B_CLEARLY_BETTER,
        PairwisePreference.B_SLIGHTLY_BETTER,
    }:
        return "B"
    if pref is PairwisePreference.APPROXIMATELY_EQUAL:
        return "EQ"
    return None


def _rate(hits: int, total: int) -> float | None:
    if total <= 0:
        return None
    return hits / total


def hard_fail_set(flags: Sequence[HardFailKind]) -> frozenset[HardFailKind]:
    return frozenset(flags)
