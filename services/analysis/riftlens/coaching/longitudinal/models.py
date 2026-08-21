"""C.6 longitudinal coaching schema (c6.0).

Laws:
- One game does not establish a recurring habit.
- Absence of a Finding does not establish successful behavior.
- Improvement requires observable, comparable evidence.
- Win/loss is not the primary measure of coaching progress.
- A blocked or non-measurable capability cannot be declared improved or resolved.
- The active focus should not switch merely because a different mistake was louder
  in one recent game.
- A player should normally carry one primary deliberate-practice focus at a time.
- RESOLVED means sufficient recent evidence supports moving on; not perfection.
- Longitudinal coaching state is an inference, never a GST fact.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from riftlens.coaching.teaching.models import (
    Measurability,
    MemorableRule,
    PracticeDrill,
    PracticeObjective,
    RecognitionCue,
)
from riftlens.domain.fact import Provenance

LONGITUDINAL_SCHEMA_VERSION = "c6.0"
LONGITUDINAL_METHOD = "c6_longitudinal_engine"
LONGITUDINAL_METHOD_VERSION = 1
LONGITUDINAL_PRODUCER = "c6_state_builder"
LONGITUDINAL_PRODUCER_VERSION = 1


class OpportunityStatus(StrEnum):
    """Whether the target behavior could be observed in a game."""

    OBSERVED_OPPORTUNITY = "OBSERVED_OPPORTUNITY"
    NO_OBSERVABLE_OPPORTUNITY = "NO_OBSERVABLE_OPPORTUNITY"
    UNKNOWN_OPPORTUNITY = "UNKNOWN_OPPORTUNITY"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class PatternStatus(StrEnum):
    """Evidence-history status for a concept. Not a permanent player trait."""

    NEW = "NEW"
    EMERGING = "EMERGING"
    RECURRING = "RECURRING"
    ACTIVE_FOCUS = "ACTIVE_FOCUS"
    IMPROVING = "IMPROVING"
    STABLE = "STABLE"
    REGRESSING = "REGRESSING"
    RESOLVED = "RESOLVED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class TrendState(StrEnum):
    IMPROVING = "IMPROVING"
    STABLE = "STABLE"
    REGRESSING = "REGRESSING"
    UNKNOWN = "UNKNOWN"


class ObjectiveResult(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILURE = "FAILURE"
    NOT_EVALUATED = "NOT_EVALUATED"
    UNKNOWN = "UNKNOWN"


class ScopeLevel(StrEnum):
    GLOBAL = "GLOBAL"
    ROLE = "ROLE"
    CHAMPION = "CHAMPION"


class FocusDecision(StrEnum):
    KEEP_FOCUS = "KEEP_FOCUS"
    SWITCH_FOCUS = "SWITCH_FOCUS"
    RESOLVE_FOCUS = "RESOLVE_FOCUS"
    ACTIVATE_FOCUS = "ACTIVATE_FOCUS"
    REACTIVATE_FOCUS = "REACTIVATE_FOCUS"
    NO_NEW_FOCUS = "NO_NEW_FOCUS"
    NO_CHANGE = "NO_CHANGE"


class StrengthStatus(StrEnum):
    POSITIVE_SIGNAL = "POSITIVE_SIGNAL"
    EMERGING_STRENGTH = "EMERGING_STRENGTH"
    CONSISTENT_STRENGTH = "CONSISTENT_STRENGTH"


@dataclass(frozen=True)
class ReasonCode:
    code: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class CoachingScope:
    """Deterministic scope for longitudinal aggregation."""

    level: ScopeLevel
    role: str | None = None
    champion: str | None = None
    queue_type: str | None = None

    def key(self) -> str:
        return "|".join(
            [
                self.level.value,
                self.role or "",
                self.champion or "",
                self.queue_type or "",
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "role": self.role,
            "champion": self.champion,
            "queue_type": self.queue_type,
            "key": self.key(),
        }


@dataclass(frozen=True)
class HistoricalCoachingGame:
    """One game's structured C.x coaching inputs for longitudinal analysis.

    Prefer explicit structured history over DB queries inside the engine.
    """

    match_id: str
    played_at_ms: int
    patch: str
    role: str
    champion: str
    queue_type: str = "RANKED_SOLO"
    won: bool | None = None  # context only — never defines habit success
    concept_observations: tuple[ConceptGameObservation, ...] = ()
    major_concept_ids: tuple[str, ...] = ()
    secondary_concept_ids: tuple[str, ...] = ()
    strength_concept_ids: tuple[str, ...] = ()
    teaching_by_concept: dict[str, dict[str, Any]] = field(default_factory=dict)
    learning_value_by_concept: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "played_at_ms": self.played_at_ms,
            "patch": self.patch,
            "role": self.role,
            "champion": self.champion,
            "queue_type": self.queue_type,
            "won": self.won,
            "concept_observations": [item.to_dict() for item in self.concept_observations],
            "major_concept_ids": list(self.major_concept_ids),
            "secondary_concept_ids": list(self.secondary_concept_ids),
            "strength_concept_ids": list(self.strength_concept_ids),
            "teaching_by_concept": dict(self.teaching_by_concept),
            "learning_value_by_concept": dict(self.learning_value_by_concept),
        }


@dataclass(frozen=True)
class ConceptGameObservation:
    """Per-concept observation for one game."""

    match_id: str
    concept_id: str
    scope: CoachingScope
    opportunity_status: OpportunityStatus
    polarity: str = "UNKNOWN"
    support_level: str = "INSUFFICIENT"
    occurrence_count: int = 0
    lesson_tier: str | None = None
    learning_value: float = 0.0
    measurable_metric: float | None = None
    opportunity_denominator: float | None = None
    gaps: tuple[str, ...] = ()
    reason_codes: tuple[ReasonCode, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "concept_id": self.concept_id,
            "scope": self.scope.to_dict(),
            "opportunity_status": self.opportunity_status.value,
            "polarity": self.polarity,
            "support_level": self.support_level,
            "occurrence_count": self.occurrence_count,
            "lesson_tier": self.lesson_tier,
            "learning_value": self.learning_value,
            "measurable_metric": self.measurable_metric,
            "opportunity_denominator": self.opportunity_denominator,
            "gaps": list(self.gaps),
            "reason_codes": [item.to_dict() for item in self.reason_codes],
        }


@dataclass(frozen=True)
class ObjectiveEvaluation:
    """Evaluation of a C.5 PracticeObjective against one game."""

    objective_concept_id: str
    prior_lesson_id: str
    match_id: str
    result: ObjectiveResult
    opportunity_status: OpportunityStatus
    measurability: Measurability
    method: str
    confidence: float
    evidence: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    reason_codes: tuple[ReasonCode, ...]
    metric_value: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective_concept_id": self.objective_concept_id,
            "prior_lesson_id": self.prior_lesson_id,
            "match_id": self.match_id,
            "result": self.result.value,
            "opportunity_status": self.opportunity_status.value,
            "measurability": self.measurability.value,
            "method": self.method,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "missing_evidence": list(self.missing_evidence),
            "reason_codes": [item.to_dict() for item in self.reason_codes],
            "metric_value": self.metric_value,
        }


@dataclass(frozen=True)
class ConceptHistory:
    """Cross-game history for one concept within a scope."""

    concept_id: str
    scope: CoachingScope
    status: PatternStatus
    trend: TrendState
    games_observed: int
    games_with_opportunity: int
    negative_games: int
    positive_games: int
    mixed_games: int
    unknown_games: int
    total_occurrences: int
    support_level: str
    confidence: float
    first_match_id: str | None
    latest_match_id: str | None
    observations: tuple[ConceptGameObservation, ...]
    evaluations: tuple[ObjectiveEvaluation, ...]
    reason_codes: tuple[ReasonCode, ...]
    gaps: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "scope": self.scope.to_dict(),
            "status": self.status.value,
            "trend": self.trend.value,
            "games_observed": self.games_observed,
            "games_with_opportunity": self.games_with_opportunity,
            "negative_games": self.negative_games,
            "positive_games": self.positive_games,
            "mixed_games": self.mixed_games,
            "unknown_games": self.unknown_games,
            "total_occurrences": self.total_occurrences,
            "support_level": self.support_level,
            "confidence": self.confidence,
            "first_match_id": self.first_match_id,
            "latest_match_id": self.latest_match_id,
            "observations": [item.to_dict() for item in self.observations],
            "evaluations": [item.to_dict() for item in self.evaluations],
            "reason_codes": [item.to_dict() for item in self.reason_codes],
            "gaps": list(self.gaps),
        }


@dataclass(frozen=True)
class ActiveFocus:
    """Primary deliberate-practice focus for the player."""

    concept_id: str
    scope: CoachingScope
    status: PatternStatus
    started_match_id: str
    started_at_ms: int
    prior_lesson_id: str
    objective: PracticeObjective | None
    recognition_cue: RecognitionCue | None
    memorable_rule: MemorableRule | None
    drill: PracticeDrill | None
    recent_evaluations: tuple[ObjectiveEvaluation, ...]
    continuity_games: int
    confidence: float
    reason_codes: tuple[ReasonCode, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "scope": self.scope.to_dict(),
            "status": self.status.value,
            "started_match_id": self.started_match_id,
            "started_at_ms": self.started_at_ms,
            "prior_lesson_id": self.prior_lesson_id,
            "objective": self.objective.to_dict() if self.objective else None,
            "recognition_cue": (
                self.recognition_cue.to_dict() if self.recognition_cue else None
            ),
            "memorable_rule": (
                self.memorable_rule.to_dict() if self.memorable_rule else None
            ),
            "drill": self.drill.to_dict() if self.drill else None,
            "recent_evaluations": [item.to_dict() for item in self.recent_evaluations],
            "continuity_games": self.continuity_games,
            "confidence": self.confidence,
            "reason_codes": [item.to_dict() for item in self.reason_codes],
        }


@dataclass(frozen=True)
class PreGameFocus:
    """Structured pre-game reminder packet (not UI-wired)."""

    concept_id: str
    recognition_cue: RecognitionCue | None
    memorable_rule: MemorableRule | None
    drill_reminder: str
    objective_summary: str
    why_still_active: str
    recent_progress_summary: str
    confidence: float
    reason_codes: tuple[ReasonCode, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "recognition_cue": (
                self.recognition_cue.to_dict() if self.recognition_cue else None
            ),
            "memorable_rule": (
                self.memorable_rule.to_dict() if self.memorable_rule else None
            ),
            "drill_reminder": self.drill_reminder,
            "objective_summary": self.objective_summary,
            "why_still_active": self.why_still_active,
            "recent_progress_summary": self.recent_progress_summary,
            "confidence": self.confidence,
            "reason_codes": [item.to_dict() for item in self.reason_codes],
        }


@dataclass(frozen=True)
class FocusUpdate:
    """Post-game focus transition result."""

    before_concept_id: str | None
    after_concept_id: str | None
    decision: FocusDecision
    objective_evaluation: ObjectiveEvaluation | None
    trend_after: TrendState
    evidence_summary: tuple[str, ...]
    reason_codes: tuple[ReasonCode, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "before_concept_id": self.before_concept_id,
            "after_concept_id": self.after_concept_id,
            "decision": self.decision.value,
            "objective_evaluation": (
                self.objective_evaluation.to_dict()
                if self.objective_evaluation
                else None
            ),
            "trend_after": self.trend_after.value,
            "evidence_summary": list(self.evidence_summary),
            "reason_codes": [item.to_dict() for item in self.reason_codes],
        }


@dataclass(frozen=True)
class StrengthHistory:
    concept_id: str
    status: StrengthStatus
    positive_games: int
    reason_codes: tuple[ReasonCode, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "status": self.status.value,
            "positive_games": self.positive_games,
            "reason_codes": [item.to_dict() for item in self.reason_codes],
        }


@dataclass(frozen=True)
class CoachingProfile:
    """Compact coaching state summary — not a psychological identity profile."""

    active_focus_concept_id: str | None
    recurring_concepts: tuple[str, ...]
    improving_concepts: tuple[str, ...]
    resolved_concepts: tuple[str, ...]
    watchlist_concepts: tuple[str, ...]
    persistent_strengths: tuple[str, ...]
    insufficient_evidence_concepts: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_focus_concept_id": self.active_focus_concept_id,
            "recurring_concepts": list(self.recurring_concepts),
            "improving_concepts": list(self.improving_concepts),
            "resolved_concepts": list(self.resolved_concepts),
            "watchlist_concepts": list(self.watchlist_concepts),
            "persistent_strengths": list(self.persistent_strengths),
            "insufficient_evidence_concepts": list(self.insufficient_evidence_concepts),
        }


@dataclass(frozen=True)
class PlayerCoachingState:
    """Longitudinal coaching state for one player/account view."""

    schema_version: str
    player_key: str
    scope: CoachingScope
    active_focus: ActiveFocus | None
    concept_histories: tuple[ConceptHistory, ...]
    strengths: tuple[StrengthHistory, ...]
    profile: CoachingProfile
    recent_match_ids: tuple[str, ...]
    config_version: str
    reason_codes: tuple[ReasonCode, ...]
    gaps: tuple[str, ...]
    provenance: Provenance
    resolved_cooldown_concepts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "player_key": self.player_key,
            "scope": self.scope.to_dict(),
            "active_focus": self.active_focus.to_dict() if self.active_focus else None,
            "concept_histories": [item.to_dict() for item in self.concept_histories],
            "strengths": [item.to_dict() for item in self.strengths],
            "profile": self.profile.to_dict(),
            "recent_match_ids": list(self.recent_match_ids),
            "config_version": self.config_version,
            "reason_codes": [item.to_dict() for item in self.reason_codes],
            "gaps": list(self.gaps),
            "resolved_cooldown_concepts": list(self.resolved_cooldown_concepts),
            "provenance": {
                "producer": self.provenance.producer,
                "producer_version": self.provenance.producer_version,
                "upstream": list(self.provenance.upstream),
            },
        }


def empty_player_state(
    player_key: str = "",
    *,
    scope: CoachingScope | None = None,
    config_version: str = "c6.0-provisional-1",
) -> PlayerCoachingState:
    """Return empty longitudinal state."""
    sc = scope or CoachingScope(level=ScopeLevel.ROLE, role=None)
    return PlayerCoachingState(
        schema_version=LONGITUDINAL_SCHEMA_VERSION,
        player_key=player_key,
        scope=sc,
        active_focus=None,
        concept_histories=(),
        strengths=(),
        profile=CoachingProfile(
            active_focus_concept_id=None,
            recurring_concepts=(),
            improving_concepts=(),
            resolved_concepts=(),
            watchlist_concepts=(),
            persistent_strengths=(),
            insufficient_evidence_concepts=(),
        ),
        recent_match_ids=(),
        config_version=config_version,
        reason_codes=(ReasonCode("EMPTY_HISTORY"),),
        gaps=("no_historical_games",),
        provenance=Provenance(
            producer=LONGITUDINAL_PRODUCER,
            producer_version=LONGITUDINAL_PRODUCER_VERSION,
            upstream=(),
        ),
    )


def state_id(player_key: str, scope_key: str) -> str:
    payload = json.dumps(
        {
            "schema": LONGITUDINAL_SCHEMA_VERSION,
            "player_key": player_key,
            "scope": scope_key,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"c6s_{digest}"
