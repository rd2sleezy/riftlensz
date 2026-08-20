"""C.2 episode interpretation schema (c2.0).

Separates observed outcome from decision quality and from execution quality.

Laws enforced by this schema and the default interpreter:
- A bad outcome does not prove a poor decision.
- A good outcome does not prove a good decision.
- Temporal precedence does not prove causality.
- Omniscient GST information does not prove player knowledge.
- Condition resolution does not prove the original decision was correct.
- UNKNOWN is a valid interpretation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from riftlens.coaching.context.models import ResolutionStatus
from riftlens.domain.enums import Source
from riftlens.domain.fact import Provenance

EPISODE_INTERPRETATION_SCHEMA_VERSION = "c2.0"
INTERPRETATION_METHOD = "c2_default_interpreter"
INTERPRETATION_METHOD_VERSION = 1
INTERPRETATION_PRODUCER = "c2_episode_interpreter"
INTERPRETATION_PRODUCER_VERSION = 1
ALTERNATIVE_ANALYSIS_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class SignalType(StrEnum):
    """What kind of signal a Finding primarily represents. Not a decision verdict."""

    OUTCOME = "OUTCOME"
    STATE = "STATE"
    ACTION = "ACTION"
    OMISSION = "OMISSION"
    PATTERN = "PATTERN"
    STRENGTH = "STRENGTH"
    UNKNOWN = "UNKNOWN"


class OutcomeKind(StrEnum):
    SUBJECT_DEATH = "SUBJECT_DEATH"
    SUBJECT_KILL = "SUBJECT_KILL"
    OBJECTIVE_EVENT = "OBJECTIVE_EVENT"
    BUILDING_EVENT = "BUILDING_EVENT"
    RESOURCE_STATE = "RESOURCE_STATE"
    FIGHT_RESULT = "FIGHT_RESULT"
    CONDITION_STATE = "CONDITION_STATE"
    STRENGTH_SIGNAL = "STRENGTH_SIGNAL"
    PATTERN_SIGNAL = "PATTERN_SIGNAL"
    UNKNOWN = "UNKNOWN"


class OutcomePolarity(StrEnum):
    """Factual polarity relative to the reviewed participant. Not decision quality."""

    FAVORABLE = "FAVORABLE"
    UNFAVORABLE = "UNFAVORABLE"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class QualityState(StrEnum):
    """Shared quality vocabulary for decision and execution assessments."""

    GOOD = "GOOD"
    POOR = "POOR"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_OBSERVABLE = "NOT_OBSERVABLE"


class DecisionOutcomeRelation(StrEnum):
    """Derived from independent decision + outcome. Never used to infer decision."""

    GOOD_DECISION_GOOD_OUTCOME = "GOOD_DECISION_GOOD_OUTCOME"
    GOOD_DECISION_BAD_OUTCOME = "GOOD_DECISION_BAD_OUTCOME"
    POOR_DECISION_GOOD_OUTCOME = "POOR_DECISION_GOOD_OUTCOME"
    POOR_DECISION_BAD_OUTCOME = "POOR_DECISION_BAD_OUTCOME"
    MIXED = "MIXED"
    UNCLASSIFIED = "UNCLASSIFIED"


class ActionabilityState(StrEnum):
    """Whether the subject could reasonably be evaluated as acting."""

    ACTIONABLE = "ACTIONABLE"
    NOT_ACTIONABLE = "NOT_ACTIONABLE"
    UNKNOWN = "UNKNOWN"


class TemporalRelation(StrEnum):
    """Ordering relative to anchors. Not causality."""

    ANTECEDENT = "ANTECEDENT"
    CONCURRENT = "CONCURRENT"
    CONSEQUENCE = "CONSEQUENCE"


class KnowledgeStatus(StrEnum):
    """Whether C.2 can establish that the reviewed player knew a fact."""

    ESTABLISHED = "ESTABLISHED"
    PLAUSIBLE = "PLAUSIBLE"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


class ClaimKind(StrEnum):
    SYSTEM_INFORMATION = "SYSTEM_INFORMATION"
    PLAYER_KNOWLEDGE = "PLAYER_KNOWLEDGE"
    INTERPRETATION = "INTERPRETATION"


@dataclass(frozen=True)
class ReasonCode:
    """Machine-readable explanation token. Not coaching prose."""

    code: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class EvidencePointer:
    """Pointer into C.1 / Finding evidence. Not a second evidence stream."""

    kind: str
    ref: str
    t_ms: int | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "ref": self.ref, "t_ms": self.t_ms, "note": self.note}


@dataclass(frozen=True)
class ObservedOutcome:
    """What happened. Independent of whether the decision was justified."""

    kind: OutcomeKind
    polarity: OutcomePolarity
    finding_id: str | None
    rule_id: str | None
    t_ms: int | None
    confidence: float
    reason_codes: tuple[ReasonCode, ...]
    support: tuple[EvidencePointer, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "polarity": self.polarity.value,
            "finding_id": self.finding_id,
            "rule_id": self.rule_id,
            "t_ms": self.t_ms,
            "confidence": self.confidence,
            "reason_codes": [item.to_dict() for item in self.reason_codes],
            "support": [item.to_dict() for item in self.support],
        }


@dataclass(frozen=True)
class DecisionAssessment:
    """Whether entering the situation was justified by available evidence.

    Finding confidence is not reused as decision confidence.
    Outcome polarity must never alone drive this state.
    """

    state: QualityState
    confidence: float
    method: str
    reason_codes: tuple[ReasonCode, ...]
    support: tuple[EvidencePointer, ...]
    conflicts: tuple[EvidencePointer, ...]
    missing_requirements: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "confidence": self.confidence,
            "method": self.method,
            "reason_codes": [item.to_dict() for item in self.reason_codes],
            "support": [item.to_dict() for item in self.support],
            "conflicts": [item.to_dict() for item in self.conflicts],
            "missing_requirements": list(self.missing_requirements),
        }


@dataclass(frozen=True)
class ExecutionAssessment:
    """Mechanical execution quality. GST-only C.2 usually cannot observe this."""

    state: QualityState
    confidence: float
    method: str
    reason_codes: tuple[ReasonCode, ...]
    support: tuple[EvidencePointer, ...] = ()
    missing_requirements: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "confidence": self.confidence,
            "method": self.method,
            "reason_codes": [item.to_dict() for item in self.reason_codes],
            "support": [item.to_dict() for item in self.support],
            "missing_requirements": list(self.missing_requirements),
        }


@dataclass(frozen=True)
class ActionabilityAssessment:
    """Conservative agency gate for evaluating a decision window."""

    state: ActionabilityState
    t_ms: int | None
    confidence: float
    reason_codes: tuple[ReasonCode, ...]
    support: tuple[EvidencePointer, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "t_ms": self.t_ms,
            "confidence": self.confidence,
            "reason_codes": [item.to_dict() for item in self.reason_codes],
            "support": [item.to_dict() for item in self.support],
        }


@dataclass(frozen=True)
class TemporalObservation:
    """Normalized before/at/after observation. Ordering != causality."""

    relation: TemporalRelation
    label: str
    t_ms: int | None
    source_kind: str
    ref: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation": self.relation.value,
            "label": self.label,
            "t_ms": self.t_ms,
            "source_kind": self.source_kind,
            "ref": self.ref,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class InformationClaim:
    """System information versus player-knowledge status."""

    claim_kind: ClaimKind
    label: str
    system_available: bool
    player_knowledge: KnowledgeStatus
    t_ms: int | None
    reason_codes: tuple[ReasonCode, ...]
    support: tuple[EvidencePointer, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_kind": self.claim_kind.value,
            "label": self.label,
            "system_available": self.system_available,
            "player_knowledge": self.player_knowledge.value,
            "t_ms": self.t_ms,
            "reason_codes": [item.to_dict() for item in self.reason_codes],
            "support": [item.to_dict() for item in self.support],
        }


@dataclass(frozen=True)
class ConditionResolutionView:
    """C.1 resolution carried into C.2 without rewriting decision quality."""

    finding_id: str
    status: ResolutionStatus
    resolver: str
    note: str

    def to_dict(self) -> dict[str, str]:
        return {
            "finding_id": self.finding_id,
            "status": self.status.value,
            "resolver": self.resolver,
            "note": self.note,
        }


@dataclass(frozen=True)
class FindingInterpretation:
    """Per-finding structured reading inside an episode."""

    finding_id: str
    rule_id: str
    concept_id: str
    signal_type: SignalType
    association: str
    suppressed: bool
    outcome: ObservedOutcome
    decision: DecisionAssessment
    execution: ExecutionAssessment
    decision_assessable: bool
    execution_observable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "rule_id": self.rule_id,
            "concept_id": self.concept_id,
            "signal_type": self.signal_type.value,
            "association": self.association,
            "suppressed": self.suppressed,
            "outcome": self.outcome.to_dict(),
            "decision": self.decision.to_dict(),
            "execution": self.execution.to_dict(),
            "decision_assessable": self.decision_assessable,
            "execution_observable": self.execution_observable,
        }


@dataclass(frozen=True)
class EpisodeInterpretation:
    """Versioned C.2 reading of one C.1 CoachingEpisode.

    Contains no coaching prose, alternatives, root causes, or prioritization.
    """

    id: str
    schema_version: str
    episode_id: str
    match_id: str
    participant_id: int
    start_ms: int
    end_ms: int
    anchor_finding_ids: tuple[str, ...]
    method: str
    method_version: int
    findings: tuple[FindingInterpretation, ...]
    outcomes: tuple[ObservedOutcome, ...]
    decision: DecisionAssessment
    execution: ExecutionAssessment
    actionability: ActionabilityAssessment
    decision_outcome_relation: DecisionOutcomeRelation
    antecedents: tuple[TemporalObservation, ...]
    concurrent: tuple[TemporalObservation, ...]
    consequences: tuple[TemporalObservation, ...]
    condition_resolutions: tuple[ConditionResolutionView, ...]
    information_claims: tuple[InformationClaim, ...]
    unknowns: tuple[str, ...]
    support: tuple[EvidencePointer, ...]
    conflicts: tuple[EvidencePointer, ...]
    provenance: Provenance
    alternative_analysis: str = ALTERNATIVE_ANALYSIS_NOT_IMPLEMENTED
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "schema_version": self.schema_version,
            "episode_id": self.episode_id,
            "match_id": self.match_id,
            "participant_id": self.participant_id,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "anchor_finding_ids": list(self.anchor_finding_ids),
            "method": self.method,
            "method_version": self.method_version,
            "findings": [item.to_dict() for item in self.findings],
            "outcomes": [item.to_dict() for item in self.outcomes],
            "decision": self.decision.to_dict(),
            "execution": self.execution.to_dict(),
            "actionability": self.actionability.to_dict(),
            "decision_outcome_relation": self.decision_outcome_relation.value,
            "antecedents": [item.to_dict() for item in self.antecedents],
            "concurrent": [item.to_dict() for item in self.concurrent],
            "consequences": [item.to_dict() for item in self.consequences],
            "condition_resolutions": [item.to_dict() for item in self.condition_resolutions],
            "information_claims": [item.to_dict() for item in self.information_claims],
            "unknowns": list(self.unknowns),
            "support": [item.to_dict() for item in self.support],
            "conflicts": [item.to_dict() for item in self.conflicts],
            "provenance": {
                "producer": self.provenance.producer,
                "producer_version": self.provenance.producer_version,
                "upstream": list(self.provenance.upstream),
            },
            "alternative_analysis": self.alternative_analysis,
            "confidence": self.confidence,
        }


def interpretation_id(episode_id: str, participant_id: int) -> str:
    """Return a stable sha256 interpretation id. Assumes episode_id is stable."""
    payload = json.dumps(
        {
            "schema_version": EPISODE_INTERPRETATION_SCHEMA_VERSION,
            "method": INTERPRETATION_METHOD,
            "method_version": INTERPRETATION_METHOD_VERSION,
            "episode_id": episode_id,
            "participant_id": participant_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"c2i_{digest}"


def derive_decision_outcome_relation(
    decision: QualityState, polarity: OutcomePolarity
) -> DecisionOutcomeRelation:
    """Derive relation only when decision quality is independently known."""
    if decision in {
        QualityState.UNKNOWN,
        QualityState.NOT_APPLICABLE,
        QualityState.NOT_OBSERVABLE,
    }:
        return DecisionOutcomeRelation.UNCLASSIFIED
    if decision is QualityState.MIXED or polarity is OutcomePolarity.UNKNOWN:
        return DecisionOutcomeRelation.MIXED
    if polarity is OutcomePolarity.NEUTRAL:
        return DecisionOutcomeRelation.MIXED
    if decision is QualityState.GOOD and polarity is OutcomePolarity.FAVORABLE:
        return DecisionOutcomeRelation.GOOD_DECISION_GOOD_OUTCOME
    if decision is QualityState.GOOD and polarity is OutcomePolarity.UNFAVORABLE:
        return DecisionOutcomeRelation.GOOD_DECISION_BAD_OUTCOME
    if decision is QualityState.POOR and polarity is OutcomePolarity.FAVORABLE:
        return DecisionOutcomeRelation.POOR_DECISION_GOOD_OUTCOME
    if decision is QualityState.POOR and polarity is OutcomePolarity.UNFAVORABLE:
        return DecisionOutcomeRelation.POOR_DECISION_BAD_OUTCOME
    return DecisionOutcomeRelation.UNCLASSIFIED


def unknown_decision(*, method: str, missing: Sequence[str]) -> DecisionAssessment:
    """Return a fail-closed UNKNOWN decision assessment."""
    return DecisionAssessment(
        state=QualityState.UNKNOWN,
        confidence=0.0,
        method=method,
        reason_codes=(
            ReasonCode(
                "DECISION_EVIDENCE_INSUFFICIENT",
                "Outcome alone cannot establish decision quality.",
            ),
        ),
        support=(),
        conflicts=(),
        missing_requirements=tuple(missing),
    )


def not_observable_execution(*, method: str) -> ExecutionAssessment:
    """Return GST-only non-observable execution assessment."""
    return ExecutionAssessment(
        state=QualityState.NOT_OBSERVABLE,
        confidence=0.0,
        method=method,
        reason_codes=(
            ReasonCode(
                "GST_ONLY_NO_MECHANICAL_EVIDENCE",
                "C.2 does not infer mechanics from kills, deaths, or fight outcomes.",
            ),
        ),
        missing_requirements=(
            "pov_visual",
            "ability_timeline",
            "precise_movement",
            "target_selection_trace",
        ),
    )


def source_token(source: Source | None) -> str | None:
    """Return Source.value or None. Assumes visual sources are never accepted."""
    return None if source is None else source.value
