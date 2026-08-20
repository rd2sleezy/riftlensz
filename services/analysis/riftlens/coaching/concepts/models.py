"""C.3 coaching concepts, causal hypotheses, and lesson candidates (c3.0).

Laws:
- A concept signal is not automatically a coaching weakness.
- Temporal proximity does not establish causality.
- Outcome does not establish decision quality.
- A broader supported concept is preferable to a specific unsupported concept.
- An external coaching system demonstrating a capability does not mean RiftLens
  has the evidence required to reproduce it.
- Capability gaps should be documented, not hidden through inference.
- UNKNOWN/BLOCKED is a successful result when evidence is insufficient.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from riftlens.domain.fact import Provenance

CONCEPTS_SCHEMA_VERSION = "c3.0"
SYNTHESIS_METHOD = "c3_default_synthesizer"
SYNTHESIS_METHOD_VERSION = 1
SYNTHESIS_PRODUCER = "c3_lesson_synthesizer"
SYNTHESIS_PRODUCER_VERSION = 1
TEACHING_OUTPUT = "NOT_IMPLEMENTED"
PRIORITIZATION = "NOT_IMPLEMENTED"


class SignalDirection(StrEnum):
    """Direction of a concept signal. Not a decision verdict."""

    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class ConceptSpecificity(StrEnum):
    """How specific a mapped concept claim is relative to available evidence."""

    SPECIFIC = "SPECIFIC"
    GENERAL = "GENERAL"
    BROAD = "BROAD"
    UNRESOLVED = "UNRESOLVED"


class CapabilityStatus(StrEnum):
    """Whether RiftLens can currently reproduce a specialized coaching capability."""

    READY = "READY"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class CausalStatus(StrEnum):
    """Uncertainty state for a causal hypothesis. SUPPORTED requires a hard contract."""

    SUPPORTED = "SUPPORTED"
    PLAUSIBLE = "PLAUSIBLE"
    CONFLICTED = "CONFLICTED"
    UNKNOWN = "UNKNOWN"


class CausalRelation(StrEnum):
    """Conservative relationship vocabulary. Prefer contributors over root causes."""

    TEMPORALLY_PRECEDES = "TEMPORALLY_PRECEDES"
    TEMPORALLY_OVERLAPS = "TEMPORALLY_OVERLAPS"
    TEMPORALLY_FOLLOWS = "TEMPORALLY_FOLLOWS"
    SHARES_CONCEPT = "SHARES_CONCEPT"
    POTENTIAL_ANTECEDENT = "POTENTIAL_ANTECEDENT"
    POTENTIAL_CONSEQUENCE = "POTENTIAL_CONSEQUENCE"
    SUPPORTED_CONTRIBUTOR = "SUPPORTED_CONTRIBUTOR"
    CONFLICTING_EXPLANATION = "CONFLICTING_EXPLANATION"
    UNRELATED = "UNRELATED"


class LessonPolarity(StrEnum):
    """Aggregate polarity of signals inside one lesson candidate."""

    CONSISTENT_NEGATIVE = "CONSISTENT_NEGATIVE"
    CONSISTENT_POSITIVE = "CONSISTENT_POSITIVE"
    MIXED = "MIXED"
    INSUFFICIENT = "INSUFFICIENT"


class SupportLevel(StrEnum):
    """Conservative lesson support — not decision confidence."""

    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    INSUFFICIENT = "INSUFFICIENT"


class LessonReadiness(StrEnum):
    """Whether a lesson candidate is ready for later C.4 prioritization inputs."""

    CANDIDATE = "CANDIDATE"
    BLOCKED = "BLOCKED"
    INSUFFICIENT = "INSUFFICIENT"


@dataclass(frozen=True)
class ReasonCode:
    code: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class EvidenceRef:
    """Lightweight pointer into Finding / C.1 / C.2 / GST evidence."""

    kind: str
    ref: str
    label: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "ref": self.ref, "label": self.label}


@dataclass(frozen=True)
class CoachingConcept:
    """Reusable League skill/decision domain above individual rule ids."""

    id: str
    name: str
    domain: str
    definition: str
    capability_status: CapabilityStatus
    supported_signal_types: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "domain": self.domain,
            "definition": self.definition,
            "capability_status": self.capability_status.value,
            "supported_signal_types": list(self.supported_signal_types),
            "evidence_requirements": list(self.evidence_requirements),
            "aliases": list(self.aliases),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ConceptMapping:
    """Conservative Finding/rule → concept mapping entry."""

    rule_id: str
    concept_id: str
    direction: SignalDirection
    specificity: ConceptSpecificity
    primary: bool
    reason_codes: tuple[ReasonCode, ...]
    forbidden_claims: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "concept_id": self.concept_id,
            "direction": self.direction.value,
            "specificity": self.specificity.value,
            "primary": self.primary,
            "reason_codes": [item.to_dict() for item in self.reason_codes],
            "forbidden_claims": list(self.forbidden_claims),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ConceptSignal:
    """Observation relevant to a concept — not automatically a weakness."""

    id: str
    concept_id: str
    finding_id: str
    rule_id: str
    interpretation_id: str
    episode_id: str
    direction: SignalDirection
    specificity: ConceptSpecificity
    confidence: float
    reason_codes: tuple[ReasonCode, ...]
    support: tuple[EvidenceRef, ...]
    conflicts: tuple[EvidenceRef, ...]
    gaps: tuple[str, ...]
    t_ms: int
    provenance: Provenance
    taxonomy_concept_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "concept_id": self.concept_id,
            "finding_id": self.finding_id,
            "rule_id": self.rule_id,
            "interpretation_id": self.interpretation_id,
            "episode_id": self.episode_id,
            "direction": self.direction.value,
            "specificity": self.specificity.value,
            "confidence": self.confidence,
            "reason_codes": [item.to_dict() for item in self.reason_codes],
            "support": [item.to_dict() for item in self.support],
            "conflicts": [item.to_dict() for item in self.conflicts],
            "gaps": list(self.gaps),
            "t_ms": self.t_ms,
            "taxonomy_concept_id": self.taxonomy_concept_id,
            "provenance": {
                "producer": self.provenance.producer,
                "producer_version": self.provenance.producer_version,
                "upstream": list(self.provenance.upstream),
            },
        }


@dataclass(frozen=True)
class CausalHypothesis:
    """Structured causal candidate with explicit uncertainty."""

    id: str
    upstream_ref: str
    downstream_ref: str
    upstream_concept_id: str
    downstream_concept_id: str
    relation: CausalRelation
    status: CausalStatus
    temporal_delta_ms: int | None
    confidence: float
    method: str
    reason_codes: tuple[ReasonCode, ...]
    support: tuple[EvidenceRef, ...]
    conflicts: tuple[EvidenceRef, ...]
    blocking_gaps: tuple[str, ...]
    h8_prior: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "upstream_ref": self.upstream_ref,
            "downstream_ref": self.downstream_ref,
            "upstream_concept_id": self.upstream_concept_id,
            "downstream_concept_id": self.downstream_concept_id,
            "relation": self.relation.value,
            "status": self.status.value,
            "temporal_delta_ms": self.temporal_delta_ms,
            "confidence": self.confidence,
            "method": self.method,
            "reason_codes": [item.to_dict() for item in self.reason_codes],
            "support": [item.to_dict() for item in self.support],
            "conflicts": [item.to_dict() for item in self.conflicts],
            "blocking_gaps": list(self.blocking_gaps),
            "h8_prior": self.h8_prior,
        }


@dataclass(frozen=True)
class LessonCandidate:
    """Potential reusable coaching lesson — not player-facing and not prioritized."""

    id: str
    schema_version: str
    concept_id: str
    match_id: str
    participant_id: int
    episode_ids: tuple[str, ...]
    finding_ids: tuple[str, ...]
    interpretation_ids: tuple[str, ...]
    positive_signal_ids: tuple[str, ...]
    negative_signal_ids: tuple[str, ...]
    neutral_signal_ids: tuple[str, ...]
    causal_hypothesis_ids: tuple[str, ...]
    polarity: LessonPolarity
    support_level: SupportLevel
    readiness: LessonReadiness
    specificity: ConceptSpecificity
    within_match_occurrences: int
    confidence: float
    context_gaps: tuple[str, ...]
    conflicting_evidence: tuple[EvidenceRef, ...]
    condition_resolution_notes: tuple[str, ...]
    reason_codes: tuple[ReasonCode, ...]
    provenance: Provenance
    teaching_output: str = TEACHING_OUTPUT
    prioritization: str = PRIORITIZATION

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "schema_version": self.schema_version,
            "concept_id": self.concept_id,
            "match_id": self.match_id,
            "participant_id": self.participant_id,
            "episode_ids": list(self.episode_ids),
            "finding_ids": list(self.finding_ids),
            "interpretation_ids": list(self.interpretation_ids),
            "positive_signal_ids": list(self.positive_signal_ids),
            "negative_signal_ids": list(self.negative_signal_ids),
            "neutral_signal_ids": list(self.neutral_signal_ids),
            "causal_hypothesis_ids": list(self.causal_hypothesis_ids),
            "polarity": self.polarity.value,
            "support_level": self.support_level.value,
            "readiness": self.readiness.value,
            "specificity": self.specificity.value,
            "within_match_occurrences": self.within_match_occurrences,
            "confidence": self.confidence,
            "context_gaps": list(self.context_gaps),
            "conflicting_evidence": [item.to_dict() for item in self.conflicting_evidence],
            "condition_resolution_notes": list(self.condition_resolution_notes),
            "reason_codes": [item.to_dict() for item in self.reason_codes],
            "provenance": {
                "producer": self.provenance.producer,
                "producer_version": self.provenance.producer_version,
                "upstream": list(self.provenance.upstream),
            },
            "teaching_output": self.teaching_output,
            "prioritization": self.prioritization,
        }


@dataclass(frozen=True)
class CoachingCapability:
    """Reference capability definition (benchmark target, not a competitor integration)."""

    id: str
    domain: str
    desired_output: str
    required_evidence: tuple[str, ...]
    available_evidence: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    unsafe_assumptions: tuple[str, ...]
    readiness: CapabilityStatus
    reason_codes: tuple[ReasonCode, ...]
    can_safely_mimic: bool
    future_upstream: str
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "domain": self.domain,
            "desired_output": self.desired_output,
            "required_evidence": list(self.required_evidence),
            "available_evidence": list(self.available_evidence),
            "missing_evidence": list(self.missing_evidence),
            "unsafe_assumptions": list(self.unsafe_assumptions),
            "readiness": self.readiness.value,
            "reason_codes": [item.to_dict() for item in self.reason_codes],
            "can_safely_mimic": self.can_safely_mimic,
            "future_upstream": self.future_upstream,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class SynthesisResult:
    """Deterministic C.3 synthesis bundle for one match/participant view."""

    schema_version: str
    match_id: str
    participant_id: int
    signals: tuple[ConceptSignal, ...]
    hypotheses: tuple[CausalHypothesis, ...]
    lessons: tuple[LessonCandidate, ...]
    capabilities: tuple[CoachingCapability, ...]
    method: str = SYNTHESIS_METHOD
    method_version: int = SYNTHESIS_METHOD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "match_id": self.match_id,
            "participant_id": self.participant_id,
            "method": self.method,
            "method_version": self.method_version,
            "signals": [item.to_dict() for item in self.signals],
            "hypotheses": [item.to_dict() for item in self.hypotheses],
            "lessons": [item.to_dict() for item in self.lessons],
            "capabilities": [item.to_dict() for item in self.capabilities],
        }


def signal_id(
    concept_id: str,
    finding_id: str,
    interpretation_id: str,
) -> str:
    """Stable concept-signal id."""
    payload = json.dumps(
        {
            "schema": CONCEPTS_SCHEMA_VERSION,
            "concept_id": concept_id,
            "finding_id": finding_id,
            "interpretation_id": interpretation_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"c3s_{digest}"


def hypothesis_id(upstream_ref: str, downstream_ref: str, relation: str) -> str:
    """Stable causal-hypothesis id."""
    payload = json.dumps(
        {
            "schema": CONCEPTS_SCHEMA_VERSION,
            "upstream_ref": upstream_ref,
            "downstream_ref": downstream_ref,
            "relation": relation,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"c3h_{digest}"


def lesson_id(concept_id: str, match_id: str, participant_id: int) -> str:
    """Stable lesson-candidate id (one per concept per match/participant)."""
    payload = json.dumps(
        {
            "schema": CONCEPTS_SCHEMA_VERSION,
            "concept_id": concept_id,
            "match_id": match_id,
            "participant_id": participant_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"c3l_{digest}"


def empty_synthesis(match_id: str = "", participant_id: int = 0) -> SynthesisResult:
    """Return an empty serializable synthesis result."""
    return SynthesisResult(
        schema_version=CONCEPTS_SCHEMA_VERSION,
        match_id=match_id,
        participant_id=participant_id,
        signals=(),
        hypotheses=(),
        lessons=(),
        capabilities=(),
    )
