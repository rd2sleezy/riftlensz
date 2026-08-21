"""Public C.7 benchmark harness APIs."""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from riftlens.coaching.evaluation.adapters import (
    normalize_cx_candidate,
    normalize_production_baseline,
    normalize_reference_manual,
)
from riftlens.coaching.evaluation.agreement import adjudication_needed, summarize_agreement
from riftlens.coaching.evaluation.blinding import (
    assert_no_gold_leakage,
    build_evaluation_packet,
    recover_systems_from_mapping,
)
from riftlens.coaching.evaluation.config import (
    DEFAULT_EVALUATION_CONFIG,
    EvaluationConfig,
)
from riftlens.coaching.evaluation.corpus import CASE_SET_VERSION, build_initial_corpus
from riftlens.coaching.evaluation.hard_fails import run_automated_checks
from riftlens.coaching.evaluation.models import (
    EVALUATION_SCHEMA_VERSION,
    BenchmarkRun,
    CaseEvaluationResult,
    CaseSourceType,
    CoachingBenchmarkCase,
    EvaluationLevel,
    FailureCategory,
    HumanEvaluation,
    HumanReferenceAnnotation,
    NormalizedCoachingView,
)
from riftlens.coaching.evaluation.ratings import (
    ingest_human_evaluations,
    load_human_evaluations_json,
    rating_template,
)
from riftlens.coaching.evaluation.regression import run_ci_regression_benchmark
from riftlens.coaching.evaluation.report import (
    render_report_markdown,
    summarize_benchmark,
)
from riftlens.domain.fact import Provenance


def build_benchmark_case(
    case_id: str,
    *,
    case_type: str,
    source_type: CaseSourceType,
    evaluation_levels: Sequence[EvaluationLevel],
    match_ref: str,
    system_input: Mapping[str, Any],
    domains: Sequence[str] = (),
    tags: Sequence[str] = (),
    expected_hard_constraints: Mapping[str, Any] | None = None,
    capability_constraints: Sequence[str] = (),
    evaluator_only_notes: str = "",
    human_references: Sequence[HumanReferenceAnnotation] = (),
    role: str | None = None,
    champion: str | None = None,
    limitations: Sequence[str] = (),
) -> CoachingBenchmarkCase:
    """Build a versioned benchmark case with gold separated from system input."""
    return CoachingBenchmarkCase(
        case_id=case_id,
        schema_version=EVALUATION_SCHEMA_VERSION,
        case_type=case_type,
        source_type=source_type,
        evaluation_levels=tuple(evaluation_levels),
        match_ref=match_ref,
        role=role,
        champion=champion,
        domains=tuple(domains),
        tags=tuple(tags),
        system_input=dict(system_input),
        expected_hard_constraints=dict(expected_hard_constraints or {}),
        capability_constraints=tuple(capability_constraints),
        evaluator_only_notes=evaluator_only_notes,
        human_references=tuple(human_references),
        limitations=tuple(limitations),
        provenance=Provenance(
            producer="c7_case_builder",
            producer_version=1,
            upstream=(),
        ),
    )


def evaluate_system_view(
    case: CoachingBenchmarkCase,
    view: NormalizedCoachingView,
) -> CaseEvaluationResult:
    """Run automated hard checks for one system view on one case."""
    assert_no_gold_leakage(case.system_input, case)
    fails = run_automated_checks(
        view, case_constraints=case.expected_hard_constraints
    )
    categories = tuple({item.category for item in fails})
    return CaseEvaluationResult(
        case_id=case.case_id,
        system_id=view.system_id,
        hard_fails=fails,
        automated_notes=tuple(item.detail for item in fails),
        failure_categories=categories,
        passed_hard_gates=len(fails) == 0,
    )


def compare_systems(
    case: CoachingBenchmarkCase,
    baseline: NormalizedCoachingView,
    candidate: NormalizedCoachingView,
    *,
    seed: int = 7,
) -> dict[str, Any]:
    """Compare baseline vs candidate: automated checks + blind packet."""
    base_result = evaluate_system_view(case, baseline)
    cand_result = evaluate_system_view(case, candidate)
    packet = build_evaluation_packet(case, baseline, candidate, seed=seed, blind=True)
    return {
        "case_id": case.case_id,
        "baseline_result": base_result.to_dict(),
        "candidate_result": cand_result.to_dict(),
        "packet": packet.evaluator_facing_dict(),
        "mapping": packet.mapping.to_dict(),
        "note": (
            "Neither system auto-wins; human pairwise ratings required for preference claims"
        ),
    }


def build_benchmark_run(
    *,
    automated_results: Sequence[CaseEvaluationResult],
    cases: Sequence[CoachingBenchmarkCase] | None = None,
    human_evaluations: Sequence[HumanEvaluation] = (),
    git_commit: str = "unknown",
    system_under_test: str = "cx_candidate",
    baseline_system: str = "production_h8",
    seed: int = 7,
    config: EvaluationConfig | None = None,
) -> BenchmarkRun:
    cfg = config or DEFAULT_EVALUATION_CONFIG
    case_list = tuple(cases or build_initial_corpus())
    summary = summarize_benchmark(
        case_list, automated_results, human_evaluations, config=cfg
    )
    return BenchmarkRun(
        run_id=f"c7run_{uuid.uuid4().hex[:12]}",
        schema_version=EVALUATION_SCHEMA_VERSION,
        config_version=cfg.version,
        rubric_version=cfg.rubric_version,
        case_set_version=cfg.case_set_version,
        git_commit=git_commit,
        system_under_test=system_under_test,
        baseline_system=baseline_system,
        seed=seed,
        cases=tuple(item.case_id for item in case_list),
        automated_results=tuple(automated_results),
        human_evaluations=tuple(human_evaluations),
        summary=summary,
        created_at_ms=int(time.time() * 1000),
        environment={"harness": "c7_pure"},
    )


def build_local_real_match_case_stub(
    match_ref: str,
    review_payload: Mapping[str, Any],
    *,
    case_id: str | None = None,
) -> CoachingBenchmarkCase:
    """Read-only seam: build a local REAL_MATCH_LOCAL case from anonymized payload.

    Does not write files. Callers must not commit private identifiers.
    Strip PUUID/display names before passing review_payload.
    """
    safe_input = {
        "focus_items": review_payload.get("focus_items") or [],
        "secondary_items": review_payload.get("secondary_items") or [],
        "strengths": review_payload.get("strengths") or [],
        "anonymized": True,
    }
    # Reject obvious PII keys if present
    for banned in ("puuid", "PUUID", "summoner_name", "riot_id", "local_path"):
        if banned in review_payload:
            raise ValueError(f"Refusing to embed private field: {banned}")

    return build_benchmark_case(
        case_id or f"local_{match_ref}",
        case_type="real_match_local",
        source_type=CaseSourceType.REAL_MATCH_LOCAL,
        evaluation_levels=(EvaluationLevel.END_TO_END,),
        match_ref=match_ref,
        system_input=safe_input,
        domains=("local",),
        tags=("real-match-local", "do-not-commit-raw"),
        limitations=(
            "local_only",
            "do_not_commit_private_data",
        ),
    )


# Re-export helpers for package surface
__all_helpers__ = (
    normalize_cx_candidate,
    normalize_production_baseline,
    normalize_reference_manual,
    run_automated_checks,
    build_evaluation_packet,
    recover_systems_from_mapping,
    ingest_human_evaluations,
    load_human_evaluations_json,
    rating_template,
    summarize_benchmark,
    render_report_markdown,
    run_ci_regression_benchmark,
    summarize_agreement,
    adjudication_needed,
    build_initial_corpus,
    CASE_SET_VERSION,
    FailureCategory,
    Provenance,
)
