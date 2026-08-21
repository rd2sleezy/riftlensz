"""C.5 coaching teaching & practice design schema (c5.0).

Laws:
- Teaching specificity may never exceed evidence specificity.
- A coaching concept can be taught even when the exact decision cannot be judged.
- General game knowledge must not be presented as evidence from the analyzed match.
- A recognition cue must use information the player can reasonably observe.
- An alternative must not be stated as certain when decision evidence is unavailable.
- A drill should train a decision process, not merely tell the player to play more games.
- A practice objective should target behavior, not merely match outcome.
- Blocked capabilities must remain blocked in teaching.
- The LLM is a narrator, not the source of coaching logic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from riftlens.domain.fact import Provenance

TEACHING_SCHEMA_VERSION = "c5.0"
TEACHING_METHOD = "c5_playbook_teacher"
TEACHING_METHOD_VERSION = 1
TEACHING_PRODUCER = "c5_teaching_builder"
TEACHING_PRODUCER_VERSION = 1


class TeachingSpecificity(StrEnum):
    """How specific teaching claims may be relative to available evidence."""

    EVENT_SPECIFIC = "EVENT_SPECIFIC"
    CONTEXTUAL = "CONTEXTUAL"
    CONCEPT_GENERAL = "CONCEPT_GENERAL"
    UNAVAILABLE = "UNAVAILABLE"


class ContentOrigin(StrEnum):
    """Origin of a teaching statement. Must not be mixed invisibly."""

    MATCH_EVIDENCE = "MATCH_EVIDENCE"
    GENERAL_GAME_PRINCIPLE = "GENERAL_GAME_PRINCIPLE"
    COACHING_INFERENCE = "COACHING_INFERENCE"
    PRACTICE_INSTRUCTION = "PRACTICE_INSTRUCTION"


class AlternativeCertainty(StrEnum):
    """How certain an alternative recommendation may be."""

    SUPPORTED = "SUPPORTED"
    PLAUSIBLE = "PLAUSIBLE"
    GENERAL_ONLY = "GENERAL_ONLY"
    UNAVAILABLE = "UNAVAILABLE"


class Measurability(StrEnum):
    """Whether a practice objective can be checked later (C.6 seam)."""

    MEASURABLE_NOW = "MEASURABLE_NOW"
    PARTIALLY_MEASURABLE = "PARTIALLY_MEASURABLE"
    NOT_MEASURABLE = "NOT_MEASURABLE"


class DrillKind(StrEnum):
    VERBAL_CUE = "VERBAL_CUE"
    REVIEW = "REVIEW"
    TRACKING = "TRACKING"
    PAUSE_CHECK = "PAUSE_CHECK"
    REINFORCEMENT = "REINFORCEMENT"
    UNAVAILABLE = "UNAVAILABLE"


class TeachingDepth(StrEnum):
    FULL = "FULL"
    LIGHT = "LIGHT"
    REINFORCEMENT = "REINFORCEMENT"
    NONE = "NONE"


@dataclass(frozen=True)
class ReasonCode:
    code: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class TeachingStatement:
    """One teaching statement with explicit origin and specificity."""

    text: str
    origin: ContentOrigin
    specificity: TeachingSpecificity
    reason_codes: tuple[ReasonCode, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "origin": self.origin.value,
            "specificity": self.specificity.value,
            "reason_codes": [item.to_dict() for item in self.reason_codes],
        }


@dataclass(frozen=True)
class RecognitionCue:
    """Player-observable trigger for remembering the concept mid-game."""

    trigger: str
    intended_check: str
    required_conditions: tuple[str, ...] = ()
    optional_conditions: tuple[str, ...] = ()
    unavailable_conditions: tuple[str, ...] = ()
    specificity: TeachingSpecificity = TeachingSpecificity.CONCEPT_GENERAL
    player_observable: bool = True
    reason_codes: tuple[ReasonCode, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "intended_check": self.intended_check,
            "required_conditions": list(self.required_conditions),
            "optional_conditions": list(self.optional_conditions),
            "unavailable_conditions": list(self.unavailable_conditions),
            "specificity": self.specificity.value,
            "player_observable": self.player_observable,
            "reason_codes": [item.to_dict() for item in self.reason_codes],
        }


@dataclass(frozen=True)
class MemorableRule:
    """Compact WHEN → THEN decision check."""

    when_trigger: str
    then_response: str
    qualifier: str = "reassess"
    absolute: bool = False
    specificity: TeachingSpecificity = TeachingSpecificity.CONCEPT_GENERAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "when_trigger": self.when_trigger,
            "then_response": self.then_response,
            "qualifier": self.qualifier,
            "absolute": self.absolute,
            "specificity": self.specificity.value,
            "compact": f"WHEN {self.when_trigger} THEN {self.qualifier} {self.then_response}",
        }


@dataclass(frozen=True)
class Alternative:
    """Conservative alternative behavior with certainty."""

    action: str
    certainty: AlternativeCertainty
    alternative_type: str = "BEHAVIOR_CHECK"
    limitations: tuple[str, ...] = ()
    evidence_contract: str = ""
    reason_codes: tuple[ReasonCode, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "certainty": self.certainty.value,
            "alternative_type": self.alternative_type,
            "limitations": list(self.limitations),
            "evidence_contract": self.evidence_contract,
            "reason_codes": [item.to_dict() for item in self.reason_codes],
        }


@dataclass(frozen=True)
class PracticeDrill:
    """Deliberate practice that trains recognition/decision — not 'play more'."""

    id: str
    concept_id: str
    kind: DrillKind
    instruction: str
    repetition_target: str
    observation_target: str
    success_condition: str
    supported_scope: TeachingSpecificity = TeachingSpecificity.CONCEPT_GENERAL
    safe: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "concept_id": self.concept_id,
            "kind": self.kind.value,
            "instruction": self.instruction,
            "repetition_target": self.repetition_target,
            "observation_target": self.observation_target,
            "success_condition": self.success_condition,
            "supported_scope": self.supported_scope.value,
            "safe": self.safe,
        }


@dataclass(frozen=True)
class PracticeObjective:
    """Process objective for future C.6 measurement. Not an outcome goal."""

    concept_id: str
    target_behavior: str
    observable: str
    evaluation_mode: str
    success_definition: str
    required_future_evidence: tuple[str, ...]
    measurability: Measurability
    outcome_goal: bool = False  # must remain False for valid C.5 objectives
    prior_lesson_id: str = ""
    reason_codes: tuple[ReasonCode, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "target_behavior": self.target_behavior,
            "observable": self.observable,
            "evaluation_mode": self.evaluation_mode,
            "success_definition": self.success_definition,
            "required_future_evidence": list(self.required_future_evidence),
            "measurability": self.measurability.value,
            "outcome_goal": self.outcome_goal,
            "prior_lesson_id": self.prior_lesson_id,
            "reason_codes": [item.to_dict() for item in self.reason_codes],
        }


@dataclass(frozen=True)
class TeachingLesson:
    """Structured teaching package for one C.4 prioritized lesson."""

    id: str
    schema_version: str
    prioritized_lesson_id: str
    lesson_candidate_id: str
    concept_id: str
    tier: str
    rank: int | None
    teaching_specificity: TeachingSpecificity
    teaching_depth: TeachingDepth
    evidence_summary: tuple[TeachingStatement, ...]
    concept_explanation: TeachingStatement | None
    why_it_matters: TeachingStatement | None
    alternative: Alternative | None
    recognition_cue: RecognitionCue | None
    memorable_rule: MemorableRule | None
    drill: PracticeDrill | None
    objective: PracticeObjective | None
    limitations: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
    selection_reason_codes: tuple[ReasonCode, ...]
    reason_codes: tuple[ReasonCode, ...]
    provenance: Provenance
    support_level: str = ""
    polarity: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "schema_version": self.schema_version,
            "prioritized_lesson_id": self.prioritized_lesson_id,
            "lesson_candidate_id": self.lesson_candidate_id,
            "concept_id": self.concept_id,
            "tier": self.tier,
            "rank": self.rank,
            "teaching_specificity": self.teaching_specificity.value,
            "teaching_depth": self.teaching_depth.value,
            "evidence_summary": [item.to_dict() for item in self.evidence_summary],
            "concept_explanation": (
                self.concept_explanation.to_dict() if self.concept_explanation else None
            ),
            "why_it_matters": self.why_it_matters.to_dict() if self.why_it_matters else None,
            "alternative": self.alternative.to_dict() if self.alternative else None,
            "recognition_cue": (
                self.recognition_cue.to_dict() if self.recognition_cue else None
            ),
            "memorable_rule": (
                self.memorable_rule.to_dict() if self.memorable_rule else None
            ),
            "drill": self.drill.to_dict() if self.drill else None,
            "objective": self.objective.to_dict() if self.objective else None,
            "limitations": list(self.limitations),
            "forbidden_claims": list(self.forbidden_claims),
            "selection_reason_codes": [item.to_dict() for item in self.selection_reason_codes],
            "reason_codes": [item.to_dict() for item in self.reason_codes],
            "support_level": self.support_level,
            "polarity": self.polarity,
            "confidence": self.confidence,
            "provenance": {
                "producer": self.provenance.producer,
                "producer_version": self.provenance.producer_version,
                "upstream": list(self.provenance.upstream),
            },
        }


@dataclass(frozen=True)
class TeachingLessonSet:
    """Deterministic teaching output for one prioritized set."""

    schema_version: str
    match_id: str
    participant_id: int
    method: str
    method_version: int
    lessons: tuple[TeachingLesson, ...]
    skipped_withheld: tuple[str, ...] = ()
    notes: tuple[ReasonCode, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "match_id": self.match_id,
            "participant_id": self.participant_id,
            "method": self.method,
            "method_version": self.method_version,
            "lessons": [item.to_dict() for item in self.lessons],
            "skipped_withheld": list(self.skipped_withheld),
            "notes": [item.to_dict() for item in self.notes],
        }


@dataclass(frozen=True)
class ConceptPlaybook:
    """Curated deterministic teaching knowledge for one concept."""

    concept_id: str
    version: int
    explanation: str
    why_it_matters: str
    recognition_cue: RecognitionCue
    memorable_rule: MemorableRule
    alternative_general: str
    drill: PracticeDrill
    objective_template: PracticeObjective
    required_capabilities: tuple[str, ...] = ()
    forbidden_claims: tuple[str, ...] = ()
    max_specificity: TeachingSpecificity = TeachingSpecificity.CONCEPT_GENERAL
    alternative_certainty: AlternativeCertainty = AlternativeCertainty.GENERAL_ONLY
    review_status: str = "CURATED"
    notes: str = ""
    strength_mode: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "version": self.version,
            "explanation": self.explanation,
            "why_it_matters": self.why_it_matters,
            "recognition_cue": self.recognition_cue.to_dict(),
            "memorable_rule": self.memorable_rule.to_dict(),
            "alternative_general": self.alternative_general,
            "drill": self.drill.to_dict(),
            "objective_template": self.objective_template.to_dict(),
            "required_capabilities": list(self.required_capabilities),
            "forbidden_claims": list(self.forbidden_claims),
            "max_specificity": self.max_specificity.value,
            "alternative_certainty": self.alternative_certainty.value,
            "review_status": self.review_status,
            "notes": self.notes,
            "strength_mode": self.strength_mode,
        }


@dataclass(frozen=True)
class TeachingReadiness:
    """Whether C.5 can produce teaching for a concept."""

    concept_id: str
    playbook_exists: bool
    teaching_specificity_supported: TeachingSpecificity
    alternative_level: AlternativeCertainty
    recognition_cue_available: bool
    drill_available: bool
    objective_measurability: Measurability
    capability_limitations: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
    reason_codes: tuple[ReasonCode, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "playbook_exists": self.playbook_exists,
            "teaching_specificity_supported": self.teaching_specificity_supported.value,
            "alternative_level": self.alternative_level.value,
            "recognition_cue_available": self.recognition_cue_available,
            "drill_available": self.drill_available,
            "objective_measurability": self.objective_measurability.value,
            "capability_limitations": list(self.capability_limitations),
            "forbidden_claims": list(self.forbidden_claims),
            "reason_codes": [item.to_dict() for item in self.reason_codes],
        }


def teaching_lesson_id(prioritized_lesson_id: str, concept_id: str) -> str:
    """Stable teaching-lesson id."""
    payload = json.dumps(
        {
            "schema": TEACHING_SCHEMA_VERSION,
            "method": TEACHING_METHOD,
            "method_version": TEACHING_METHOD_VERSION,
            "prioritized_lesson_id": prioritized_lesson_id,
            "concept_id": concept_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"c5t_{digest}"


def empty_teaching_set(
    match_id: str = "",
    participant_id: int = 0,
) -> TeachingLessonSet:
    """Return empty teaching output."""
    return TeachingLessonSet(
        schema_version=TEACHING_SCHEMA_VERSION,
        match_id=match_id,
        participant_id=participant_id,
        method=TEACHING_METHOD,
        method_version=TEACHING_METHOD_VERSION,
        lessons=(),
        skipped_withheld=(),
        notes=(ReasonCode("EMPTY_INPUT", "no prioritized lessons"),),
    )
