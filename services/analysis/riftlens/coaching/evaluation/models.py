"""C.7 coaching quality benchmark schema (c7.0).

Laws:
- Passing unit tests does not prove coaching quality.
- Fluent language cannot compensate for incorrect coaching logic.
- Human disagreement is data, not noise to erase.
- Gold/reference annotations must never leak into the system being evaluated.
- A benchmark can only support claims within the domains and cases it actually tests.
- BLOCKED capabilities are evaluated on honest refusal, not on fabricated coaching.
- C.7 must be capable of detecting regressions in newer coaching systems.
- Benchmark infrastructure completion does not equal human quality validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from riftlens.domain.fact import Provenance

EVALUATION_SCHEMA_VERSION = "c7.0"
EVALUATION_METHOD = "c7_quality_benchmark"
EVALUATION_METHOD_VERSION = 1
EVALUATION_PRODUCER = "c7_benchmark_harness"
EVALUATION_PRODUCER_VERSION = 1

HUMAN_VALIDATION_STATUS = "NOT_YET_PERFORMED"


class CaseSourceType(StrEnum):
    SYNTHETIC_EDGE_CASE = "SYNTHETIC_EDGE_CASE"
    REPO_FIXTURE = "REPO_FIXTURE"
    REAL_MATCH_LOCAL = "REAL_MATCH_LOCAL"
    HUMAN_CURATED = "HUMAN_CURATED"
    EXTERNAL_REFERENCE_MANUAL = "EXTERNAL_REFERENCE_MANUAL"


class EvaluationLevel(StrEnum):
    FACT_INTERPRETATION = "LEVEL_1_FACT_INTERPRETATION"
    CONCEPT_CAUSAL = "LEVEL_2_CONCEPT_CAUSAL"
    PRIORITIZATION = "LEVEL_3_PRIORITIZATION"
    TEACHING = "LEVEL_4_TEACHING"
    LONGITUDINAL = "LEVEL_5_LONGITUDINAL"
    END_TO_END = "LEVEL_6_END_TO_END"


class RubricScore(StrEnum):
    FAIL = "0_FAIL"
    POOR = "1_POOR"
    ACCEPTABLE = "2_ACCEPTABLE"
    GOOD = "3_GOOD"
    EXCELLENT = "4_EXCELLENT"
    NA = "N/A"
    UNJUDGEABLE = "UNJUDGEABLE"


class RubricDimension(StrEnum):
    Q1_FACTUAL_GROUNDING = "Q1_FACTUAL_GROUNDING"
    Q2_EPISTEMIC_CALIBRATION = "Q2_EPISTEMIC_CALIBRATION"
    Q3_CONCEPT_CORRECTNESS = "Q3_CONCEPT_CORRECTNESS"
    Q4_CAUSAL_DISCIPLINE = "Q4_CAUSAL_DISCIPLINE"
    Q5_PRIORITY_QUALITY = "Q5_PRIORITY_QUALITY"
    Q6_NON_REDUNDANCY = "Q6_NON_REDUNDANCY"
    Q7_RELEVANCE_SPECIFICITY = "Q7_RELEVANCE_SPECIFICITY"
    Q8_ACTIONABILITY = "Q8_ACTIONABILITY"
    Q9_RECOGNITION_CUE_QUALITY = "Q9_RECOGNITION_CUE_QUALITY"
    Q10_ALTERNATIVE_QUALITY = "Q10_ALTERNATIVE_QUALITY"
    Q11_DRILL_QUALITY = "Q11_DRILL_QUALITY"
    Q12_OBJECTIVE_QUALITY = "Q12_OBJECTIVE_QUALITY"
    Q13_COGNITIVE_LOAD = "Q13_COGNITIVE_LOAD"
    Q14_LONGITUDINAL_QUALITY = "Q14_LONGITUDINAL_QUALITY"
    Q15_OVERALL_COACHING_VALUE = "Q15_OVERALL_COACHING_VALUE"
    LANGUAGE_CLARITY = "LANGUAGE_CLARITY"  # separate from coaching logic


class FailureCategory(StrEnum):
    FACTUAL_ERROR = "FACTUAL_ERROR"
    UNSUPPORTED_INFERENCE = "UNSUPPORTED_INFERENCE"
    DECISION_OVERREACH = "DECISION_OVERREACH"
    CAUSAL_OVERREACH = "CAUSAL_OVERREACH"
    PLAYER_KNOWLEDGE_OVERREACH = "PLAYER_KNOWLEDGE_OVERREACH"
    CAPABILITY_VIOLATION = "CAPABILITY_VIOLATION"
    PRIORITY_MISS = "PRIORITY_MISS"
    REDUNDANT_COACHING = "REDUNDANT_COACHING"
    TOO_GENERIC = "TOO_GENERIC"
    TOO_SPECIFIC_FOR_EVIDENCE = "TOO_SPECIFIC_FOR_EVIDENCE"
    UNACTIONABLE = "UNACTIONABLE"
    BAD_RECOGNITION_CUE = "BAD_RECOGNITION_CUE"
    BAD_ALTERNATIVE = "BAD_ALTERNATIVE"
    BAD_DRILL = "BAD_DRILL"
    UNMEASURABLE_OBJECTIVE = "UNMEASURABLE_OBJECTIVE"
    COGNITIVE_OVERLOAD = "COGNITIVE_OVERLOAD"
    FALSE_LONGITUDINAL_PATTERN = "FALSE_LONGITUDINAL_PATTERN"
    FALSE_PROGRESS = "FALSE_PROGRESS"
    FOCUS_FLAPPING = "FOCUS_FLAPPING"
    MISSED_IMPORTANT_LESSON = "MISSED_IMPORTANT_LESSON"
    OTHER = "OTHER"


class HardFailKind(StrEnum):
    FACT_FABRICATION = "FACT_FABRICATION"
    DECISION_OVERREACH = "DECISION_OVERREACH"
    CAUSAL_OVERREACH = "CAUSAL_OVERREACH"
    PLAYER_KNOWLEDGE_OVERREACH = "PLAYER_KNOWLEDGE_OVERREACH"
    CAPABILITY_VIOLATION = "CAPABILITY_VIOLATION"
    RESULT_BIAS = "RESULT_BIAS"
    LONGITUDINAL_FALSE_SUCCESS = "LONGITUDINAL_FALSE_SUCCESS"
    FALSE_PROGRESS = "FALSE_PROGRESS"


class PairwisePreference(StrEnum):
    A_CLEARLY_BETTER = "A_CLEARLY_BETTER"
    A_SLIGHTLY_BETTER = "A_SLIGHTLY_BETTER"
    APPROXIMATELY_EQUAL = "APPROXIMATELY_EQUAL"
    B_SLIGHTLY_BETTER = "B_SLIGHTLY_BETTER"
    B_CLEARLY_BETTER = "B_CLEARLY_BETTER"
    UNJUDGEABLE = "UNJUDGEABLE"


class EvaluatorExpertise(StrEnum):
    PLAYER = "PLAYER"
    HIGH_ELO_PLAYER = "HIGH_ELO_PLAYER"
    COACH = "COACH"
    EXPERT_COACH = "EXPERT_COACH"
    DOMAIN_REVIEWER = "DOMAIN_REVIEWER"


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"


class CapabilityCoverage(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    UNTESTED = "UNTESTED"


class ClaimOutcome(StrEnum):
    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_EVALUATED = "NOT_EVALUATED"


class ReferenceComparisonBand(StrEnum):
    BELOW_REFERENCE = "BELOW_REFERENCE"
    APPROACHING_REFERENCE = "APPROACHING_REFERENCE"
    COMPARABLE_ON_THIS_CASESET = "COMPARABLE_ON_THIS_CASESET"
    EXCEEDS_BASELINE = "EXCEEDS_BASELINE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class ReasonCode:
    code: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class NormalizedCoachingView:
    """Common comparison surface for baseline vs candidate.

    Missing fields remain missing — never invented.
    """

    system_id: str
    observation: str | None = None
    lesson: str | None = None
    why: str | None = None
    alternative: str | None = None
    cue: str | None = None
    drill: str | None = None
    objective: str | None = None
    limitations: tuple[str, ...] = ()
    concept_ids: tuple[str, ...] = ()
    major_count: int = 0
    decision_quality: str | None = None
    causal_status: str | None = None
    player_knowledge: str | None = None
    capability_statuses: dict[str, str] = field(default_factory=dict)
    longitudinal_status: str | None = None
    opportunity_status: str | None = None
    objective_result: str | None = None
    measurability: str | None = None
    language_text: str | None = None
    structural: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_id": self.system_id,
            "observation": self.observation,
            "lesson": self.lesson,
            "why": self.why,
            "alternative": self.alternative,
            "cue": self.cue,
            "drill": self.drill,
            "objective": self.objective,
            "limitations": list(self.limitations),
            "concept_ids": list(self.concept_ids),
            "major_count": self.major_count,
            "decision_quality": self.decision_quality,
            "causal_status": self.causal_status,
            "player_knowledge": self.player_knowledge,
            "capability_statuses": dict(self.capability_statuses),
            "longitudinal_status": self.longitudinal_status,
            "opportunity_status": self.opportunity_status,
            "objective_result": self.objective_result,
            "measurability": self.measurability,
            "language_text": self.language_text,
            "structural": dict(self.structural),
        }


@dataclass(frozen=True)
class HumanReferenceAnnotation:
    """Evaluator-only reference. Never an input to the system under test."""

    preferred_primary_lesson: str | None = None
    secondary_lessons: tuple[str, ...] = ()
    reasoning: str = ""
    alternative: str | None = None
    recognition_cue: str | None = None
    drill: str | None = None
    confidence: float = 0.0
    missing_information: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "preferred_primary_lesson": self.preferred_primary_lesson,
            "secondary_lessons": list(self.secondary_lessons),
            "reasoning": self.reasoning,
            "alternative": self.alternative,
            "recognition_cue": self.recognition_cue,
            "drill": self.drill,
            "confidence": self.confidence,
            "missing_information": list(self.missing_information),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ReferenceCoachingOutput:
    """Manual external reference only — no scraping/adapters for competitors."""

    source_label: str
    case_id: str
    observations: tuple[str, ...] = ()
    primary_lesson: str | None = None
    secondary_lessons: tuple[str, ...] = ()
    teaching: str | None = None
    limitations: tuple[str, ...] = ()
    provenance_note: str = "manual_entry"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_label": self.source_label,
            "case_id": self.case_id,
            "observations": list(self.observations),
            "primary_lesson": self.primary_lesson,
            "secondary_lessons": list(self.secondary_lessons),
            "teaching": self.teaching,
            "limitations": list(self.limitations),
            "provenance_note": self.provenance_note,
        }


@dataclass(frozen=True)
class CoachingBenchmarkCase:
    """Versioned benchmark case. Gold references are evaluator-only."""

    case_id: str
    schema_version: str
    case_type: str
    source_type: CaseSourceType
    evaluation_levels: tuple[EvaluationLevel, ...]
    match_ref: str
    role: str | None = None
    champion: str | None = None
    domains: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    system_input: dict[str, Any] = field(default_factory=dict)
    expected_hard_constraints: dict[str, Any] = field(default_factory=dict)
    capability_constraints: tuple[str, ...] = ()
    evaluator_only_notes: str = ""
    human_references: tuple[HumanReferenceAnnotation, ...] = ()
    comparison_systems: tuple[str, ...] = ("production_h8", "cx_candidate")
    limitations: tuple[str, ...] = ()
    provenance: Provenance | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "schema_version": self.schema_version,
            "case_type": self.case_type,
            "source_type": self.source_type.value,
            "evaluation_levels": [item.value for item in self.evaluation_levels],
            "match_ref": self.match_ref,
            "role": self.role,
            "champion": self.champion,
            "domains": list(self.domains),
            "tags": list(self.tags),
            "system_input": dict(self.system_input),
            "expected_hard_constraints": dict(self.expected_hard_constraints),
            "capability_constraints": list(self.capability_constraints),
            # Explicitly separate: never fed to coaching engines
            "evaluator_only": {
                "notes": self.evaluator_only_notes,
                "human_references": [item.to_dict() for item in self.human_references],
            },
            "comparison_systems": list(self.comparison_systems),
            "limitations": list(self.limitations),
        }

    def system_facing_payload(self) -> dict[str, Any]:
        """Payload safe to feed systems under test (no gold leakage)."""
        return {
            "case_id": self.case_id,
            "match_ref": self.match_ref,
            "role": self.role,
            "champion": self.champion,
            "system_input": dict(self.system_input),
            "capability_constraints": list(self.capability_constraints),
        }


@dataclass(frozen=True)
class HardFailFinding:
    kind: HardFailKind
    category: FailureCategory
    detail: str
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "category": self.category.value,
            "detail": self.detail,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class RubricRating:
    dimension: RubricDimension
    score: RubricScore
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "score": self.score.value,
            "note": self.note,
        }

    def ordinal(self) -> int | None:
        if self.score in {RubricScore.NA, RubricScore.UNJUDGEABLE}:
            return None
        return int(self.score.value[0])


@dataclass(frozen=True)
class HumanEvaluation:
    evaluator_id: str
    expertise: EvaluatorExpertise
    case_id: str
    system_label_shown: str
    evaluated_at_ms: int
    rubric_scores: tuple[RubricRating, ...]
    hard_fail_flags: tuple[HardFailKind, ...] = ()
    pairwise: PairwisePreference | None = None
    pairwise_question: str | None = None
    confidence: float = 0.5
    notes: str = ""
    unjudgeable_reasons: tuple[str, ...] = ()
    adjudication_of: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluator_id": self.evaluator_id,
            "expertise": self.expertise.value,
            "case_id": self.case_id,
            "system_label_shown": self.system_label_shown,
            "evaluated_at_ms": self.evaluated_at_ms,
            "rubric_scores": [item.to_dict() for item in self.rubric_scores],
            "hard_fail_flags": [item.value for item in self.hard_fail_flags],
            "pairwise": self.pairwise.value if self.pairwise else None,
            "pairwise_question": self.pairwise_question,
            "confidence": self.confidence,
            "notes": self.notes,
            "unjudgeable_reasons": list(self.unjudgeable_reasons),
            "adjudication_of": list(self.adjudication_of),
        }


@dataclass(frozen=True)
class BlindMapping:
    seed: int
    case_id: str
    label_a_system_id: str
    label_b_system_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "case_id": self.case_id,
            "label_a_system_id": self.label_a_system_id,
            "label_b_system_id": self.label_b_system_id,
        }


@dataclass(frozen=True)
class EvaluationPacket:
    packet_id: str
    case_id: str
    instructions: str
    context_for_evaluator: dict[str, Any]
    system_a: dict[str, Any]
    system_b: dict[str, Any]
    rubric_dimensions: tuple[str, ...]
    pairwise_questions: tuple[str, ...]
    blind: bool
    seed: int
    # Mapping is NOT included in evaluator-facing export
    mapping: BlindMapping

    def evaluator_facing_dict(self) -> dict[str, Any]:
        """Export without revealing system identities."""
        return {
            "packet_id": self.packet_id,
            "case_id": self.case_id,
            "instructions": self.instructions,
            "context": self.context_for_evaluator,
            "system_a": self.system_a,
            "system_b": self.system_b,
            "rubric_dimensions": list(self.rubric_dimensions),
            "pairwise_questions": list(self.pairwise_questions),
            "blind": self.blind,
            "seed": self.seed,
        }

    def to_dict(self) -> dict[str, Any]:
        out = self.evaluator_facing_dict()
        out["mapping"] = self.mapping.to_dict()
        return out


@dataclass(frozen=True)
class CaseEvaluationResult:
    case_id: str
    system_id: str
    hard_fails: tuple[HardFailFinding, ...]
    automated_notes: tuple[str, ...] = ()
    failure_categories: tuple[FailureCategory, ...] = ()
    passed_hard_gates: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "system_id": self.system_id,
            "hard_fails": [item.to_dict() for item in self.hard_fails],
            "automated_notes": list(self.automated_notes),
            "failure_categories": [item.value for item in self.failure_categories],
            "passed_hard_gates": self.passed_hard_gates,
        }


@dataclass(frozen=True)
class AgreementSummary:
    exact_agreement_rate: float | None
    within_one_agreement_rate: float | None
    pairwise_agreement_rate: float | None
    hard_fail_agreement_rate: float | None
    n_pairs: int
    caveats: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "exact_agreement_rate": self.exact_agreement_rate,
            "within_one_agreement_rate": self.within_one_agreement_rate,
            "pairwise_agreement_rate": self.pairwise_agreement_rate,
            "hard_fail_agreement_rate": self.hard_fail_agreement_rate,
            "n_pairs": self.n_pairs,
            "caveats": list(self.caveats),
        }


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    status: GateStatus
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "status": self.status.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ClaimResult:
    claim_id: str
    statement: str
    outcome: ClaimOutcome
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "outcome": self.outcome.value,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class BenchmarkSummary:
    case_count: int
    source_type_counts: dict[str, int]
    domain_counts: dict[str, int]
    hard_fail_counts: dict[str, int]
    failure_taxonomy_counts: dict[str, int]
    capability_coverage: dict[str, str]
    gate_results: tuple[GateResult, ...]
    claim_results: tuple[ClaimResult, ...]
    agreement: AgreementSummary | None
    reference_band: ReferenceComparisonBand
    human_validation_status: str
    caveats: tuple[str, ...]
    rubric_score_counts: dict[str, int] = field(default_factory=dict)
    pairwise_preference_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_count": self.case_count,
            "source_type_counts": dict(self.source_type_counts),
            "domain_counts": dict(self.domain_counts),
            "hard_fail_counts": dict(self.hard_fail_counts),
            "failure_taxonomy_counts": dict(self.failure_taxonomy_counts),
            "capability_coverage": dict(self.capability_coverage),
            "gate_results": [item.to_dict() for item in self.gate_results],
            "claim_results": [item.to_dict() for item in self.claim_results],
            "agreement": self.agreement.to_dict() if self.agreement else None,
            "reference_band": self.reference_band.value,
            "human_validation_status": self.human_validation_status,
            "caveats": list(self.caveats),
            "rubric_score_counts": dict(self.rubric_score_counts),
            "pairwise_preference_counts": dict(self.pairwise_preference_counts),
        }


@dataclass(frozen=True)
class BenchmarkRun:
    run_id: str
    schema_version: str
    config_version: str
    rubric_version: str
    case_set_version: str
    git_commit: str
    system_under_test: str
    baseline_system: str
    seed: int
    cases: tuple[str, ...]
    automated_results: tuple[CaseEvaluationResult, ...]
    human_evaluations: tuple[HumanEvaluation, ...]
    summary: BenchmarkSummary
    created_at_ms: int
    environment: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "config_version": self.config_version,
            "rubric_version": self.rubric_version,
            "case_set_version": self.case_set_version,
            "git_commit": self.git_commit,
            "system_under_test": self.system_under_test,
            "baseline_system": self.baseline_system,
            "seed": self.seed,
            "cases": list(self.cases),
            "automated_results": [item.to_dict() for item in self.automated_results],
            "human_evaluations": [item.to_dict() for item in self.human_evaluations],
            "summary": self.summary.to_dict(),
            "created_at_ms": self.created_at_ms,
            "environment": dict(self.environment),
            "human_validation_status": HUMAN_VALIDATION_STATUS,
        }
