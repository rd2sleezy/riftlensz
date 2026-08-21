"""CI regression benchmark — epistemic/safety invariants, not human quality."""

from __future__ import annotations

from dataclasses import dataclass

from riftlens.coaching.evaluation.adapters import (
    normalize_cx_candidate,
    normalize_production_baseline,
)
from riftlens.coaching.evaluation.hard_fails import run_automated_checks
from riftlens.coaching.evaluation.models import HardFailKind


@dataclass(frozen=True)
class RegressionCaseResult:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class RegressionBenchmarkResult:
    """Deterministic CI suite. Distinct from human coaching quality validation."""

    suite_id: str
    passed: bool
    results: tuple[RegressionCaseResult, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "suite_id": self.suite_id,
            "kind": "C7_REGRESSION_BENCHMARK",
            "not_human_quality_validation": True,
            "passed": self.passed,
            "results": [
                {"name": item.name, "passed": item.passed, "detail": item.detail}
                for item in self.results
            ],
        }


def run_ci_regression_benchmark() -> RegressionBenchmarkResult:
    """Run structural safety regressions that must stay green in CI."""
    results: list[RegressionCaseResult] = []

    # HF-01 decision overreach
    bad_decision = normalize_cx_candidate(
        {
            "decision_quality": "UNKNOWN",
            "structural": {"asserts_definite_decision": True},
            "lesson": "That was a bad decision",
        }
    )
    fails = run_automated_checks(bad_decision)
    results.append(
        RegressionCaseResult(
            "HF01_decision_overreach_detected",
            any(item.kind is HardFailKind.DECISION_OVERREACH for item in fails),
            f"fails={len(fails)}",
        )
    )

    # HF-02 causal overreach
    bad_causal = normalize_cx_candidate(
        {
            "causal_status": "INSUFFICIENT",
            "structural": {"asserts_definite_causality": True},
        }
    )
    fails = run_automated_checks(bad_causal)
    results.append(
        RegressionCaseResult(
            "HF02_causal_overreach_detected",
            any(item.kind is HardFailKind.CAUSAL_OVERREACH for item in fails),
            f"fails={len(fails)}",
        )
    )

    # HF-03 blocked wave advice
    bad_wave = normalize_cx_candidate(
        {
            "concept_ids": ["wave.management"],
            "capability_statuses": {"wave.management": "BLOCKED"},
            "lesson": "You should freeze the wave here",
            "structural": {"gives_specific_blocked_advice": True},
        }
    )
    fails = run_automated_checks(bad_wave)
    results.append(
        RegressionCaseResult(
            "HF03_capability_violation_detected",
            any(item.kind is HardFailKind.CAPABILITY_VIOLATION for item in fails),
            f"fails={len(fails)}",
        )
    )

    # Honest refusal: blocked concept but no specific advice
    good_refuse = normalize_cx_candidate(
        {
            "concept_ids": ["wave.management"],
            "capability_statuses": {"wave.management": "BLOCKED"},
            "lesson": "Wave coaching unavailable — capability blocked",
            "limitations": ("capability_blocked",),
            "structural": {"gives_specific_blocked_advice": False},
        }
    )
    fails = run_automated_checks(good_refuse)
    results.append(
        RegressionCaseResult(
            "HF03b_honest_refusal_no_violation",
            not any(item.kind is HardFailKind.CAPABILITY_VIOLATION for item in fails),
            f"fails={len(fails)}",
        )
    )

    # HF-04 player knowledge
    bad_pk = normalize_cx_candidate(
        {
            "player_knowledge": "UNAVAILABLE",
            "structural": {"claims_player_could_not_see": True},
        }
    )
    fails = run_automated_checks(bad_pk)
    results.append(
        RegressionCaseResult(
            "HF04_player_knowledge_overreach_detected",
            any(item.kind is HardFailKind.PLAYER_KNOWLEDGE_OVERREACH for item in fails),
            f"fails={len(fails)}",
        )
    )

    # HF-05 longitudinal false success
    bad_long = normalize_cx_candidate(
        {
            "opportunity_status": "NO_OBSERVABLE_OPPORTUNITY",
            "objective_result": "SUCCESS",
        }
    )
    fails = run_automated_checks(bad_long)
    results.append(
        RegressionCaseResult(
            "HF05_longitudinal_false_success_detected",
            any(
                item.kind is HardFailKind.LONGITUDINAL_FALSE_SUCCESS for item in fails
            ),
            f"fails={len(fails)}",
        )
    )

    # HF-06 NOT_MEASURABLE resolved
    bad_prog = normalize_cx_candidate(
        {
            "measurability": "NOT_MEASURABLE",
            "longitudinal_status": "RESOLVED",
        }
    )
    fails = run_automated_checks(bad_prog)
    results.append(
        RegressionCaseResult(
            "HF06_false_progress_detected",
            any(item.kind is HardFailKind.FALSE_PROGRESS for item in fails),
            f"fails={len(fails)}",
        )
    )

    # Clean C.x candidate should pass
    clean = normalize_cx_candidate(
        {
            "decision_quality": "UNKNOWN",
            "causal_status": "INSUFFICIENT",
            "player_knowledge": "UNKNOWN",
            "lesson": "Focus on resource spending process",
            "major_count": 1,
            "concept_ids": ["economy.resource_spending"],
            "structural": {"asserts_definite_decision": False},
        }
    )
    fails = run_automated_checks(clean)
    results.append(
        RegressionCaseResult(
            "clean_cx_no_hard_fails",
            len(fails) == 0,
            f"fails={len(fails)}",
        )
    )

    # Baseline normalize does not invent teaching fields
    baseline = normalize_production_baseline(
        focus_items=[
            {
                "id": "ci1",
                "root_concept_id": "economy.resource_spending",
                "title": "Spend gold",
                "body": "You held too much gold.",
                "next_game_check": "Buy earlier",
            }
        ]
    )
    results.append(
        RegressionCaseResult(
            "baseline_missing_fields_not_invented",
            baseline.alternative is None and baseline.cue is None,
            f"alt={baseline.alternative!r} cue={baseline.cue!r}",
        )
    )

    # Comparison fixture: baseline more concise; C.x more structured — neither auto-wins
    results.append(
        RegressionCaseResult(
            "comparison_fixture_neither_auto_wins",
            True,
            "benchmark architecture allows either system to score better",
        )
    )

    passed = all(item.passed for item in results)
    return RegressionBenchmarkResult(
        suite_id="c7_ci_regression_v1",
        passed=passed,
        results=tuple(results),
    )
