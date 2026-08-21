"""C.7 coaching quality benchmark and human evaluation framework."""

from __future__ import annotations

from riftlens.coaching.evaluation.adapters import (
    normalize_cx_candidate,
    normalize_production_baseline,
    normalize_reference_manual,
)
from riftlens.coaching.evaluation.agreement import (
    adjudication_needed,
    summarize_agreement,
)
from riftlens.coaching.evaluation.blinding import (
    assert_no_gold_leakage,
    build_evaluation_packet,
    recover_systems_from_mapping,
)
from riftlens.coaching.evaluation.builder import (
    build_benchmark_case,
    build_benchmark_run,
    build_local_real_match_case_stub,
    compare_systems,
    evaluate_system_view,
)
from riftlens.coaching.evaluation.config import (
    DEFAULT_EVALUATION_CONFIG,
    EvaluationConfig,
    with_evaluation_overrides,
)
from riftlens.coaching.evaluation.corpus import (
    CASE_SET_VERSION,
    build_initial_corpus,
    corpus_by_id,
)
from riftlens.coaching.evaluation.hard_fails import run_automated_checks
from riftlens.coaching.evaluation.models import (
    EVALUATION_SCHEMA_VERSION,
    HUMAN_VALIDATION_STATUS,
    AgreementSummary,
    BenchmarkRun,
    BenchmarkSummary,
    BlindMapping,
    CaseEvaluationResult,
    CaseSourceType,
    ClaimOutcome,
    ClaimResult,
    CoachingBenchmarkCase,
    EvaluationLevel,
    EvaluationPacket,
    EvaluatorExpertise,
    FailureCategory,
    GateResult,
    GateStatus,
    HardFailFinding,
    HardFailKind,
    HumanEvaluation,
    HumanReferenceAnnotation,
    NormalizedCoachingView,
    PairwisePreference,
    ReferenceCoachingOutput,
    ReferenceComparisonBand,
    RubricDimension,
    RubricRating,
    RubricScore,
)
from riftlens.coaching.evaluation.ratings import (
    ingest_human_evaluations,
    load_human_evaluations_json,
    parse_human_evaluation,
    rating_template,
)
from riftlens.coaching.evaluation.regression import (
    RegressionBenchmarkResult,
    run_ci_regression_benchmark,
)
from riftlens.coaching.evaluation.report import (
    default_capability_coverage,
    render_report_markdown,
    summarize_benchmark,
)
from riftlens.coaching.evaluation.rubric import (
    get_rubric_definitions,
    is_valid_rubric_score,
    ordinal_value,
)

__all__ = [
    "CASE_SET_VERSION",
    "DEFAULT_EVALUATION_CONFIG",
    "EVALUATION_SCHEMA_VERSION",
    "HUMAN_VALIDATION_STATUS",
    "AgreementSummary",
    "BenchmarkRun",
    "BenchmarkSummary",
    "BlindMapping",
    "CaseEvaluationResult",
    "CaseSourceType",
    "ClaimOutcome",
    "ClaimResult",
    "CoachingBenchmarkCase",
    "EvaluationConfig",
    "EvaluationLevel",
    "EvaluationPacket",
    "EvaluatorExpertise",
    "FailureCategory",
    "GateResult",
    "GateStatus",
    "HardFailFinding",
    "HardFailKind",
    "HumanEvaluation",
    "HumanReferenceAnnotation",
    "NormalizedCoachingView",
    "PairwisePreference",
    "ReferenceCoachingOutput",
    "ReferenceComparisonBand",
    "RegressionBenchmarkResult",
    "RubricDimension",
    "RubricRating",
    "RubricScore",
    "adjudication_needed",
    "assert_no_gold_leakage",
    "build_benchmark_case",
    "build_benchmark_run",
    "build_evaluation_packet",
    "build_initial_corpus",
    "build_local_real_match_case_stub",
    "compare_systems",
    "corpus_by_id",
    "default_capability_coverage",
    "evaluate_system_view",
    "get_rubric_definitions",
    "ingest_human_evaluations",
    "is_valid_rubric_score",
    "load_human_evaluations_json",
    "normalize_cx_candidate",
    "normalize_production_baseline",
    "normalize_reference_manual",
    "ordinal_value",
    "parse_human_evaluation",
    "rating_template",
    "recover_systems_from_mapping",
    "render_report_markdown",
    "run_automated_checks",
    "run_ci_regression_benchmark",
    "summarize_agreement",
    "summarize_benchmark",
    "with_evaluation_overrides",
]
