"""Benchmark summary / claim-based report generation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from riftlens.coaching.evaluation.agreement import summarize_agreement
from riftlens.coaching.evaluation.config import (
    DEFAULT_EVALUATION_CONFIG,
    EvaluationConfig,
)
from riftlens.coaching.evaluation.models import (
    HUMAN_VALIDATION_STATUS,
    BenchmarkSummary,
    CaseEvaluationResult,
    ClaimOutcome,
    ClaimResult,
    CoachingBenchmarkCase,
    FailureCategory,
    GateResult,
    GateStatus,
    HardFailKind,
    HumanEvaluation,
    ReferenceComparisonBand,
)


def default_capability_coverage() -> dict[str, str]:
    return {
        "economy.resource_spending": "READY",
        "economy.reset_timing": "READY",
        "risk.isolation": "PARTIAL",
        "objective.presence": "PARTIAL",
        "laning.cs_maintenance": "PARTIAL",
        "vision.control_ward_habit": "PARTIAL",
        "wave.management": "BLOCKED",
        "mechanics.execution": "BLOCKED",
        "combat.summoner_usage": "BLOCKED",
        "risk.information_discipline": "BLOCKED",
        "jungle.pathing": "UNTESTED",
    }


def summarize_benchmark(
    cases: Sequence[CoachingBenchmarkCase],
    automated: Sequence[CaseEvaluationResult],
    human: Sequence[HumanEvaluation] = (),
    *,
    config: EvaluationConfig | None = None,
) -> BenchmarkSummary:
    cfg = config or DEFAULT_EVALUATION_CONFIG
    source_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    for case in cases:
        source_counts[case.source_type.value] += 1
        for domain in case.domains:
            domain_counts[domain] += 1

    hard_counts: Counter[str] = Counter()
    fail_tax: Counter[str] = Counter()
    for result in automated:
        for item in result.hard_fails:
            hard_counts[item.kind.value] += 1
            fail_tax[item.category.value] += 1

    gates = evaluate_quality_gates(hard_counts, human, config=cfg)
    claims = build_claim_results(hard_counts, human, automated)
    agreement = summarize_agreement(human) if len(human) >= 2 else None

    rubric_counts: Counter[str] = Counter()
    pairwise_counts: Counter[str] = Counter()
    for evaluation in human:
        for rating in evaluation.rubric_scores:
            rubric_counts[rating.score.value] += 1
        if evaluation.pairwise is not None:
            pairwise_counts[evaluation.pairwise.value] += 1

    caveats = [
        "HUMAN QUALITY VALIDATION: NOT YET PERFORMED"
        if not human
        else "Human ratings present — interpret with sample-size caution",
        "Synthetic cases do not prove real coaching quality",
        "Claims limited to domains/cases actually tested",
        "No HUMAN_LEVEL gate; reference bands are cautious",
    ]

    band = (
        ReferenceComparisonBand.INSUFFICIENT_DATA
        if not human
        else ReferenceComparisonBand.INSUFFICIENT_DATA
    )

    return BenchmarkSummary(
        case_count=len(cases),
        source_type_counts=dict(source_counts),
        domain_counts=dict(domain_counts),
        hard_fail_counts=dict(hard_counts),
        failure_taxonomy_counts=dict(fail_tax),
        capability_coverage=default_capability_coverage(),
        gate_results=gates,
        claim_results=claims,
        agreement=agreement,
        reference_band=band,
        human_validation_status=HUMAN_VALIDATION_STATUS
        if not human
        else "RATINGS_PRESENT_NOT_VALIDATED_STUDY",
        caveats=tuple(caveats),
        rubric_score_counts=dict(rubric_counts),
        pairwise_preference_counts=dict(pairwise_counts),
    )


def evaluate_quality_gates(
    hard_counts: Counter[str] | dict[str, int],
    human: Sequence[HumanEvaluation],
    *,
    config: EvaluationConfig | None = None,
) -> tuple[GateResult, ...]:
    cfg = config or DEFAULT_EVALUATION_CONFIG
    counts = Counter(hard_counts)
    results: list[GateResult] = []

    def hard(
        gate_id: str, kind: HardFailKind, limit: int
    ) -> GateResult:
        n = counts.get(kind.value, 0)
        status = GateStatus.PASS if n <= limit else GateStatus.FAIL
        return GateResult(gate_id, status, f"count={n} limit={limit}")

    results.append(
        hard(
            "HARD_CAPABILITY_VIOLATION",
            HardFailKind.CAPABILITY_VIOLATION,
            cfg.max_capability_violations,
        )
    )
    results.append(
        hard("HARD_FALSE_PROGRESS", HardFailKind.FALSE_PROGRESS, cfg.max_false_progress)
    )
    results.append(
        hard(
            "HARD_FACT_FABRICATION",
            HardFailKind.FACT_FABRICATION,
            cfg.max_fact_fabrication,
        )
    )
    results.append(
        hard(
            "HARD_DECISION_OVERREACH",
            HardFailKind.DECISION_OVERREACH,
            cfg.max_decision_overreach,
        )
    )
    results.append(
        hard(
            "HARD_CAUSAL_OVERREACH",
            HardFailKind.CAUSAL_OVERREACH,
            cfg.max_causal_overreach,
        )
    )
    results.append(
        hard(
            "HARD_LONGITUDINAL_FALSE_SUCCESS",
            HardFailKind.LONGITUDINAL_FALSE_SUCCESS,
            cfg.max_longitudinal_false_success,
        )
    )

    # Human gates
    if not human:
        for gate_id in (
            "HUMAN_FACTUAL_GROUNDING",
            "HUMAN_PRIORITY_QUALITY",
            "HUMAN_ACTIONABILITY",
        ):
            results.append(
                GateResult(
                    gate_id,
                    GateStatus.NOT_EVALUATED,
                    "No human ratings present",
                )
            )
    else:
        # Presence of ratings still does not auto-pass study validation
        results.append(
            GateResult(
                "HUMAN_FACTUAL_GROUNDING",
                GateStatus.NOT_EVALUATED,
                "Ratings present but formal study not completed",
            )
        )
        results.append(
            GateResult(
                "HUMAN_PRIORITY_QUALITY",
                GateStatus.NOT_EVALUATED,
                "Ratings present but formal study not completed",
            )
        )
        results.append(
            GateResult(
                "HUMAN_ACTIONABILITY",
                GateStatus.NOT_EVALUATED,
                "Ratings present but formal study not completed",
            )
        )

    return tuple(results)


def build_claim_results(
    hard_counts: Counter[str] | dict[str, int],
    human: Sequence[HumanEvaluation],
    automated: Sequence[CaseEvaluationResult],
) -> tuple[ClaimResult, ...]:
    counts = Counter(hard_counts)
    claims = [
        ClaimResult(
            "claim_cx_fewer_causal_overreach",
            "C.x produces fewer unsupported causal claims than production H.8",
            ClaimOutcome.INSUFFICIENT_DATA
            if not human
            else ClaimOutcome.NOT_EVALUATED,
            "Requires paired human/automated comparison study",
        ),
        ClaimResult(
            "claim_cx_priority_preferred",
            "C.x prioritization is preferred by human reviewers",
            ClaimOutcome.NOT_EVALUATED if not human else ClaimOutcome.INSUFFICIENT_DATA,
            "No completed blinded human preference study",
        ),
        ClaimResult(
            "claim_c6_no_false_opportunity_success",
            "C.6 does not confuse no opportunity with success",
            ClaimOutcome.SUPPORTED
            if counts.get(HardFailKind.LONGITUDINAL_FALSE_SUCCESS.value, 0) == 0
            else ClaimOutcome.NOT_SUPPORTED,
            "Structural HF-05 checks detect false success on regression corpus",
        ),
        ClaimResult(
            "claim_human_level",
            "RiftLens is human-level at League coaching",
            ClaimOutcome.NOT_SUPPORTED,
            "Forbidden claim without rigorous multi-domain study",
        ),
    ]
    return tuple(claims)


def render_report_markdown(summary: BenchmarkSummary) -> str:
    """Deterministic text report."""
    hard_lines = [
        f"- {k}: {v}" for k, v in sorted(summary.hard_fail_counts.items())
    ] or ["- (none)"]
    lines = [
        "# C.7 Benchmark Report",
        "",
        f"Cases: {summary.case_count}",
        f"Human validation: {summary.human_validation_status}",
        f"Reference band: {summary.reference_band.value}",
        "",
        "## Source types",
        *(f"- {k}: {v}" for k, v in sorted(summary.source_type_counts.items())),
        "",
        "## Domains",
        *(f"- {k}: {v}" for k, v in sorted(summary.domain_counts.items())),
        "",
        "## Hard fails",
        *hard_lines,
        "",
        "## Gates",
        *(
            f"- {item.gate_id}: {item.status.value} ({item.detail})"
            for item in summary.gate_results
        ),
        "",
        "## Claims",
        *(
            f"- {item.claim_id}: {item.outcome.value} — {item.statement}"
            for item in summary.claim_results
        ),
        "",
        "## Capability coverage",
        *(f"- {k}: {v}" for k, v in sorted(summary.capability_coverage.items())),
        "",
        "## Caveats",
        *(f"- {item}" for item in summary.caveats),
        "",
        f"Failure taxonomy categories known: {len(FailureCategory)}",
    ]
    return "\n".join(lines)
