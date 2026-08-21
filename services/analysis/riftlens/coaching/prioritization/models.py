"""C.4 learning-value prioritization schema (c4.0).

Laws:
- The number of major lessons is evidence-driven, not fixed.
- Impact is not the same as learning value.
- Frequency is not the same as learning value.
- An unfavorable outcome does not prove a poor decision.
- Unsupported specificity must not outrank supported generality.
- A blocked capability cannot become high-confidence coaching merely because
  it sounds useful.
- Withholding a weak lesson is preferable to filling a quota.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from riftlens.domain.fact import Provenance

PRIORITIZATION_SCHEMA_VERSION = "c4.0"
PRIORITIZATION_METHOD = "c4_learning_value"
PRIORITIZATION_METHOD_VERSION = 1
PRIORITIZATION_PRODUCER = "c4_lesson_prioritizer"
PRIORITIZATION_PRODUCER_VERSION = 1
TEACHING_OUTPUT = "NOT_IMPLEMENTED"


class LessonTier(StrEnum):
    """Promotion tier. Rank does not imply causal certainty."""

    MAJOR = "MAJOR"
    SECONDARY = "SECONDARY"
    STRENGTH = "STRENGTH"
    WITHHELD = "WITHHELD"


class OverlapRelation(StrEnum):
    """Evidence overlap between two lesson candidates. Not a merge."""

    DISTINCT = "DISTINCT"
    RELATED = "RELATED"
    HIGH_OVERLAP = "HIGH_OVERLAP"
    DUPLICATIVE = "DUPLICATIVE"


class ActionabilityHint(StrEnum):
    """Optional C.2-derived actionability input. UNKNOWN ≠ actionable."""

    ACTIONABLE = "ACTIONABLE"
    NOT_ACTIONABLE = "NOT_ACTIONABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ReasonCode:
    code: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class PriorityFactors:
    """Machine-readable learning-value factor breakdown (provisional units)."""

    evidence_support: float = 0.0
    within_match_recurrence: float = 0.0
    impact: float = 0.0
    causal_leverage: float = 0.0
    actionability: float = 0.0
    teachability: float = 0.0
    specificity: float = 0.0
    capability_readiness: float = 0.0
    conflict_penalty: float = 0.0
    gap_penalty: float = 0.0
    resolution_penalty: float = 0.0
    redundancy_penalty: float = 0.0
    role_relevance: float = 0.0
    rank_relevance: float = 0.0

    def total(self) -> float:
        """Sum all factor contributions."""
        return (
            self.evidence_support
            + self.within_match_recurrence
            + self.impact
            + self.causal_leverage
            + self.actionability
            + self.teachability
            + self.specificity
            + self.capability_readiness
            + self.conflict_penalty
            + self.gap_penalty
            + self.resolution_penalty
            + self.redundancy_penalty
            + self.role_relevance
            + self.rank_relevance
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "evidence_support": self.evidence_support,
            "within_match_recurrence": self.within_match_recurrence,
            "impact": self.impact,
            "causal_leverage": self.causal_leverage,
            "actionability": self.actionability,
            "teachability": self.teachability,
            "specificity": self.specificity,
            "capability_readiness": self.capability_readiness,
            "conflict_penalty": self.conflict_penalty,
            "gap_penalty": self.gap_penalty,
            "resolution_penalty": self.resolution_penalty,
            "redundancy_penalty": self.redundancy_penalty,
            "role_relevance": self.role_relevance,
            "rank_relevance": self.rank_relevance,
            "total": self.total(),
        }

    def with_updates(self, **kwargs: float) -> PriorityFactors:
        """Return a copy with selected fields replaced."""
        data = self.to_dict()
        data.pop("total", None)
        data.update(kwargs)
        return PriorityFactors(**{k: float(v) for k, v in data.items()})


@dataclass(frozen=True)
class PrioritizedLesson:
    """One scored/ranked lesson candidate with explainable factors."""

    id: str
    lesson_candidate_id: str
    concept_id: str
    rank: int | None
    tier: LessonTier
    learning_value: float
    factors: PriorityFactors
    polarity: str
    support_level: str
    occurrences: int
    specificity: str
    capability_status: str
    conflicts: int
    gaps: tuple[str, ...]
    reason_codes: tuple[ReasonCode, ...]
    exclusion_reason: str | None = None
    overlap_with: tuple[str, ...] = ()
    provenance: Provenance | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "lesson_candidate_id": self.lesson_candidate_id,
            "concept_id": self.concept_id,
            "rank": self.rank,
            "tier": self.tier.value,
            "learning_value": self.learning_value,
            "factors": self.factors.to_dict(),
            "polarity": self.polarity,
            "support_level": self.support_level,
            "occurrences": self.occurrences,
            "specificity": self.specificity,
            "capability_status": self.capability_status,
            "conflicts": self.conflicts,
            "gaps": list(self.gaps),
            "reason_codes": [item.to_dict() for item in self.reason_codes],
            "exclusion_reason": self.exclusion_reason,
            "overlap_with": list(self.overlap_with),
            "provenance": (
                {
                    "producer": self.provenance.producer,
                    "producer_version": self.provenance.producer_version,
                    "upstream": list(self.provenance.upstream),
                }
                if self.provenance is not None
                else None
            ),
        }


@dataclass(frozen=True)
class PrioritizedLessonSet:
    """Deterministic learning-value prioritization over one match's lessons."""

    schema_version: str
    match_id: str
    participant_id: int
    method: str
    method_version: int
    config_version: str
    ranked: tuple[PrioritizedLesson, ...]
    major: tuple[PrioritizedLesson, ...]
    secondary: tuple[PrioritizedLesson, ...]
    strengths: tuple[PrioritizedLesson, ...]
    withheld: tuple[PrioritizedLesson, ...]
    selection_notes: tuple[ReasonCode, ...] = ()
    provenance: Provenance | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "match_id": self.match_id,
            "participant_id": self.participant_id,
            "method": self.method,
            "method_version": self.method_version,
            "config_version": self.config_version,
            "ranked": [item.to_dict() for item in self.ranked],
            "major": [item.to_dict() for item in self.major],
            "secondary": [item.to_dict() for item in self.secondary],
            "strengths": [item.to_dict() for item in self.strengths],
            "withheld": [item.to_dict() for item in self.withheld],
            "selection_notes": [item.to_dict() for item in self.selection_notes],
            "provenance": (
                {
                    "producer": self.provenance.producer,
                    "producer_version": self.provenance.producer_version,
                    "upstream": list(self.provenance.upstream),
                }
                if self.provenance is not None
                else None
            ),
        }


@dataclass(frozen=True)
class ScoringContext:
    """Optional single-match scoring inputs. Extensible for future C.6 factors.

    C.4 never reads DB/history. Callers may supply deterministic priors.
    Missing maps default to neutral (no bonus/penalty).
    """

    impact_by_lesson_id: Mapping[str, float] = field(default_factory=dict)
    teachability_by_concept: Mapping[str, float] = field(default_factory=dict)
    rank_relevance_by_concept: Mapping[str, float] = field(default_factory=dict)
    role_relevance_by_concept: Mapping[str, float] = field(default_factory=dict)
    causal_plausible_by_lesson_id: Mapping[str, int] = field(default_factory=dict)
    causal_supported_by_lesson_id: Mapping[str, int] = field(default_factory=dict)
    actionability_by_lesson_id: Mapping[str, ActionabilityHint] = field(
        default_factory=dict
    )
    # Reserved seams for C.6 (must remain unused / empty in C.4):
    cross_game_recurrence: Mapping[str, int] = field(default_factory=dict)
    active_focus: tuple[str, ...] = ()
    trend_by_concept: Mapping[str, str] = field(default_factory=dict)


def prioritized_lesson_id(lesson_candidate_id: str, method_version: int) -> str:
    """Stable prioritized-lesson id."""
    payload = json.dumps(
        {
            "schema": PRIORITIZATION_SCHEMA_VERSION,
            "method": PRIORITIZATION_METHOD,
            "method_version": method_version,
            "lesson_candidate_id": lesson_candidate_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"c4p_{digest}"


def empty_prioritized_set(
    match_id: str = "",
    participant_id: int = 0,
    *,
    config_version: str = "c4.0-provisional-1",
) -> PrioritizedLessonSet:
    """Return an empty prioritization result."""
    return PrioritizedLessonSet(
        schema_version=PRIORITIZATION_SCHEMA_VERSION,
        match_id=match_id,
        participant_id=participant_id,
        method=PRIORITIZATION_METHOD,
        method_version=PRIORITIZATION_METHOD_VERSION,
        config_version=config_version,
        ranked=(),
        major=(),
        secondary=(),
        strengths=(),
        withheld=(),
        selection_notes=(ReasonCode("EMPTY_INPUT", "no lesson candidates"),),
        provenance=Provenance(
            producer=PRIORITIZATION_PRODUCER,
            producer_version=PRIORITIZATION_PRODUCER_VERSION,
            upstream=(),
        ),
    )
