"""Provisional C.7 benchmark configuration and quality gates."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class EvaluationConfig:
    """Versioned provisional gates — not scientifically validated."""

    version: str = "c7.0-provisional-1"
    rubric_version: str = "c7.0-rubric-1"
    case_set_version: str = "c7.0-corpus-1"

    # Hard gates (regression corpus)
    max_capability_violations: int = 0
    max_false_progress: int = 0
    max_fact_fabrication: int = 0
    max_decision_overreach: int = 0
    max_causal_overreach: int = 0
    max_longitudinal_false_success: int = 0

    # Human quality gates (NOT_EVALUATED without ratings)
    human_factual_grounding_median_min: float = 2.0
    human_priority_quality_median_min: float = 2.0
    human_actionability_median_min: float = 2.0

    # Agreement reporting
    within_one_tolerance: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "rubric_version": self.rubric_version,
            "case_set_version": self.case_set_version,
            "max_capability_violations": self.max_capability_violations,
            "max_false_progress": self.max_false_progress,
            "human_factual_grounding_median_min": self.human_factual_grounding_median_min,
        }


DEFAULT_EVALUATION_CONFIG = EvaluationConfig()


def with_evaluation_overrides(
    base: EvaluationConfig | None = None,
    **overrides: Any,
) -> EvaluationConfig:
    return replace(base or DEFAULT_EVALUATION_CONFIG, **overrides)
