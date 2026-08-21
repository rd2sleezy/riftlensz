"""Initial committed C.7 synthetic benchmark corpus."""

from __future__ import annotations

from typing import Any

from riftlens.coaching.evaluation.models import (
    EVALUATION_SCHEMA_VERSION,
    CaseSourceType,
    CoachingBenchmarkCase,
    EvaluationLevel,
    HumanReferenceAnnotation,
)
from riftlens.domain.fact import Provenance

CASE_SET_VERSION = "c7.0-corpus-1"


def _case(
    case_id: str,
    *,
    case_type: str,
    domains: tuple[str, ...],
    tags: tuple[str, ...],
    levels: tuple[EvaluationLevel, ...],
    system_input: dict[str, Any],
    constraints: dict[str, Any] | None = None,
    capability_constraints: tuple[str, ...] = (),
    evaluator_notes: str = "",
    human_refs: tuple[HumanReferenceAnnotation, ...] = (),
    limitations: tuple[str, ...] = ("synthetic_not_real_quality_proof",),
) -> CoachingBenchmarkCase:
    return CoachingBenchmarkCase(
        case_id=case_id,
        schema_version=EVALUATION_SCHEMA_VERSION,
        case_type=case_type,
        source_type=CaseSourceType.SYNTHETIC_EDGE_CASE,
        evaluation_levels=levels,
        match_ref=f"synthetic:{case_id}",
        role="MID",
        champion="AnonChamp",
        domains=domains,
        tags=tags,
        system_input=system_input,
        expected_hard_constraints=constraints or {},
        capability_constraints=capability_constraints,
        evaluator_only_notes=evaluator_notes,
        human_references=human_refs,
        limitations=limitations,
        provenance=Provenance(
            producer="c7_corpus",
            producer_version=1,
            upstream=(CASE_SET_VERSION,),
        ),
    )


def build_initial_corpus() -> tuple[CoachingBenchmarkCase, ...]:
    """Compact synthetic corpus covering core edge domains. Not all of League."""
    L1 = EvaluationLevel.FACT_INTERPRETATION
    L2 = EvaluationLevel.CONCEPT_CAUSAL
    L3 = EvaluationLevel.PRIORITIZATION
    L4 = EvaluationLevel.TEACHING
    L5 = EvaluationLevel.LONGITUDINAL
    L6 = EvaluationLevel.END_TO_END

    return (
        _case(
            "c7_economy_reset",
            case_type="economy_reset",
            domains=("economy",),
            tags=("economy", "reset"),
            levels=(L3, L4, L6),
            system_input={
                "primary_concept": "economy.reset_timing",
                "findings": ["R-006"],
                "scenario": "high_unspent_gold_before_objective",
            },
            evaluator_notes="Preferred lesson: reset timing before objective.",
            human_refs=(
                HumanReferenceAnnotation(
                    preferred_primary_lesson="economy.reset_timing",
                    reasoning="Gold banked into a high-stakes window.",
                    confidence=0.7,
                ),
            ),
        ),
        _case(
            "c7_death_risk_unknown_decision",
            case_type="epistemic_death",
            domains=("risk",),
            tags=("risk", "ambiguous", "decision_unknown"),
            levels=(L1, L2),
            system_input={
                "outcome": "death",
                "decision_quality": "UNKNOWN",
                "player_knowledge": "UNKNOWN",
            },
            constraints={"claimed_decision_quality_must_not_be": "POOR"},
            evaluator_notes="Death ≠ poor decision without more evidence.",
        ),
        _case(
            "c7_objective_presence",
            case_type="objective",
            domains=("objective",),
            tags=("objective",),
            levels=(L3, L4),
            system_input={"primary_concept": "objective.presence"},
        ),
        _case(
            "c7_laning_cs",
            case_type="laning",
            domains=("laning",),
            tags=("laning", "cs"),
            levels=(L3, L4),
            system_input={"primary_concept": "laning.cs_maintenance"},
        ),
        _case(
            "c7_blocked_wave",
            case_type="blocked_capability",
            domains=("wave",),
            tags=("blocked-capability", "wave"),
            levels=(L2, L4),
            system_input={"concept": "wave.management"},
            capability_constraints=("wave.management",),
            constraints={"must_refuse_specific_wave_advice": True},
        ),
        _case(
            "c7_blocked_mechanics",
            case_type="blocked_capability",
            domains=("mechanics",),
            tags=("blocked-capability", "mechanics"),
            levels=(L2, L4),
            system_input={"concept": "mechanics.execution"},
            capability_constraints=("mechanics.execution",),
        ),
        _case(
            "c7_player_knowledge_ambiguity",
            case_type="epistemic_fog",
            domains=("risk",),
            tags=("player-knowledge", "ambiguous"),
            levels=(L1, L2),
            system_input={
                "player_knowledge": "UNAVAILABLE",
                "system_knows_enemy_position": True,
            },
            constraints={"must_not_claim_player_could_not_see": True},
        ),
        _case(
            "c7_strength_resets",
            case_type="strength",
            domains=("strength",),
            tags=("strength",),
            levels=(L3, L4),
            system_input={"primary_concept": "strength.efficient_resets"},
        ),
        _case(
            "c7_zero_major",
            case_type="prioritization_empty",
            domains=("general",),
            tags=("zero-finding", "zero-major"),
            levels=(L3,),
            system_input={"lesson_candidates": [], "expected_major_count": 0},
        ),
        _case(
            "c7_longitudinal_five_game",
            case_type="longitudinal",
            domains=("economy", "longitudinal"),
            tags=("longitudinal", "economy"),
            levels=(L5, L6),
            system_input={
                "games_metrics": [3, 2, 2, 1, 0],
                "active_focus": "economy.resource_spending",
                "opportunities": ["OBSERVED"] * 5,
            },
            evaluator_notes="Process improving; win/loss irrelevant.",
        ),
        _case(
            "c7_prio_strong_plus_noise",
            case_type="prioritization_p1",
            domains=("economy",),
            tags=("prioritization", "p1"),
            levels=(L3,),
            system_input={
                "strong_lesson": "economy.resource_spending",
                "weak_symptoms": ["symptom_a", "symptom_b", "symptom_c"],
                "expected_major_count_max": 1,
            },
        ),
        _case(
            "c7_longitudinal_no_opportunity",
            case_type="longitudinal_opportunity",
            domains=("economy", "longitudinal"),
            tags=("longitudinal", "no-opportunity"),
            levels=(L5,),
            system_input={
                "opportunity_status": "NO_OBSERVABLE_OPPORTUNITY",
                "objective_result_must_not_be": "SUCCESS",
            },
        ),
        _case(
            "c7_kill_decision_unknown",
            case_type="epistemic_kill",
            domains=("combat",),
            tags=("positive-outcome", "decision_unknown"),
            levels=(L1,),
            system_input={"outcome": "kill", "decision_quality": "UNKNOWN"},
        ),
        _case(
            "c7_baseline_vs_cx_compare",
            case_type="system_comparison",
            domains=("economy",),
            tags=("comparison", "baseline"),
            levels=(L6,),
            system_input={
                "scenario": "resource_spending_major",
                "baseline_may_be_more_concise": True,
            },
            evaluator_notes=(
                "Honest comparison case: baseline may be more concise; "
                "C.x may withhold unsupported certainty."
            ),
        ),
    )


def corpus_by_id() -> dict[str, CoachingBenchmarkCase]:
    return {item.case_id: item for item in build_initial_corpus()}
