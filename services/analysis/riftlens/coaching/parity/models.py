"""RP.0 reference-parity benchmark schema.

Complements C.7 (coaching quality/safety). Does not replace C.7.
Does not wire into production review, H.8, H.11, API, or UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Any

PARITY_SCHEMA_VERSION = "rp.0"
PARITY_METHOD = "rp0_reference_parity"
PARITY_METHOD_VERSION = 1
PARITY_PRODUCER = "rp0_parity_registry"
PARITY_PRODUCER_VERSION = 1

HUMAN_QUALITY_VALIDATION = "NOT_YET_PERFORMED"
BASELINE_ADJUDICATION_LABEL = "PILOT_SELF_REVIEW"


class ReferenceEvidenceLevel(StrEnum):
    """How strongly we know a reference system actually has a capability."""

    DEMONSTRATED = "DEMONSTRATED"
    VENDOR_CLAIM = "VENDOR_CLAIM"
    HUMAN_REFERENCE = "HUMAN_REFERENCE"
    UNKNOWN = "UNKNOWN"


class ReferenceCoverage(StrEnum):
    """Claimed or observed breadth — independent of evidence class."""

    FULL = "FULL"
    PARTIAL = "PARTIAL"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"
    NA = "N/A"


class MatrixCell(StrEnum):
    """Public matrix vocabulary. Derived; never stored as a raw vendor claim."""

    DEMONSTRATED = "DEMONSTRATED"
    CLAIMED = "CLAIMED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    NA = "N/A"


class RiftLensParityStatus(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    UNTESTED = "UNTESTED"
    REFERENCE_ONLY = "REFERENCE_ONLY"


class ParityCaseSource(StrEnum):
    REAL_MATCH_LOCAL = "REAL_MATCH_LOCAL"
    SYNTHETIC = "SYNTHETIC"
    MANUAL_REFERENCE = "MANUAL_REFERENCE"
    COMPETITOR_REFERENCE = "COMPETITOR_REFERENCE"
    HUMAN_COACH = "HUMAN_COACH"
    PUBLIC_DEMO = "PUBLIC_DEMO"


class AdjudicationVerdict(StrEnum):
    AGREE = "AGREE"
    PARTLY = "PARTLY"
    DISAGREE = "DISAGREE"


class ParityDimension(StrEnum):
    DETECTION = "DETECTION"
    STATE_RECONSTRUCTION = "STATE_RECONSTRUCTION"
    DECISION_CLASSIFICATION = "DECISION_CLASSIFICATION"
    CAUSAL_EXPLANATION = "CAUSAL_EXPLANATION"
    ALTERNATIVE = "ALTERNATIVE"
    SPECIFICITY = "SPECIFICITY"
    EPISTEMIC_CALIBRATION = "EPISTEMIC_CALIBRATION"
    PRIORITIZATION = "PRIORITIZATION"
    TEACHING_VALUE = "TEACHING_VALUE"
    REPLAY_TRACEABILITY = "REPLAY_TRACEABILITY"
    LONGITUDINAL_VALUE = "LONGITUDINAL_VALUE"
    HUMAN_PREFERENCE = "HUMAN_PREFERENCE"


class ParityLevel(IntEnum):
    ABSENT = 0
    DETECTS_EVENT_ONLY = 1
    RECONSTRUCTS_PARTIAL_CONTEXT = 2
    GENERALLY_CORRECT_COACHING = 3
    REFERENCE_COMPARABLE = 4
    REFERENCE_EXCEEDING = 5


class PriorityBand(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class SourceAvailability(StrEnum):
    NO = "NO"
    POSSIBLE = "POSSIBLE"
    LIKELY = "LIKELY"
    PROVEN = "PROVEN"
    UNKNOWN = "UNKNOWN"


class StatementKind(StrEnum):
    OBSERVED = "OBSERVED"
    VENDOR_CLAIM = "VENDOR_CLAIM"
    HUMAN_JUDGMENT = "HUMAN_JUDGMENT"
    INFERENCE = "INFERENCE"


ALL_PARITY_DIMENSIONS: tuple[ParityDimension, ...] = tuple(ParityDimension)


def derive_matrix_cell(
    evidence_level: ReferenceEvidenceLevel,
    coverage: ReferenceCoverage,
) -> MatrixCell:
    """Map evidence class + coverage to a matrix cell.

    Vendor claims cannot become DEMONSTRATED.
    """
    if coverage is ReferenceCoverage.NA:
        return MatrixCell.NA
    if evidence_level is ReferenceEvidenceLevel.UNKNOWN:
        return MatrixCell.UNKNOWN
    if coverage is ReferenceCoverage.NONE:
        return MatrixCell.NA
    if coverage is ReferenceCoverage.UNKNOWN:
        return MatrixCell.UNKNOWN
    if evidence_level is ReferenceEvidenceLevel.VENDOR_CLAIM:
        if coverage is ReferenceCoverage.PARTIAL:
            return MatrixCell.PARTIAL
        return MatrixCell.CLAIMED
    if evidence_level is ReferenceEvidenceLevel.HUMAN_REFERENCE:
        if coverage is ReferenceCoverage.PARTIAL:
            return MatrixCell.PARTIAL
        return MatrixCell.DEMONSTRATED
    # DEMONSTRATED evidence
    if coverage is ReferenceCoverage.PARTIAL:
        return MatrixCell.PARTIAL
    if coverage is ReferenceCoverage.FULL:
        return MatrixCell.DEMONSTRATED
    return MatrixCell.UNKNOWN


def priority_band_for_score(score: int) -> PriorityBand:
    """Map the 0–5 aggressive-priority score to a band."""
    if score >= 5:
        return PriorityBand.CRITICAL
    if score >= 4:
        return PriorityBand.HIGH
    if score >= 3:
        return PriorityBand.MEDIUM
    return PriorityBand.LOW


@dataclass(frozen=True)
class ReferenceSystem:
    """One external coaching product or human-reference class."""

    system_id: str
    display_name: str
    kind: str
    notes: str
    uncertainty: str

    def to_dict(self) -> dict[str, str]:
        return {
            "system_id": self.system_id,
            "display_name": self.display_name,
            "kind": self.kind,
            "notes": self.notes,
            "uncertainty": self.uncertainty,
        }


@dataclass(frozen=True)
class ReferenceCapabilityNote:
    """One system's relationship to one RP capability."""

    system_id: str
    capability_id: str
    coverage: ReferenceCoverage
    evidence_level: ReferenceEvidenceLevel
    notes: str = ""

    def matrix_cell(self) -> MatrixCell:
        return derive_matrix_cell(self.evidence_level, self.coverage)

    def to_dict(self) -> dict[str, str]:
        cell = self.matrix_cell()
        if (
            self.evidence_level is ReferenceEvidenceLevel.VENDOR_CLAIM
            and cell is MatrixCell.DEMONSTRATED
        ):
            raise ValueError("vendor claim cannot serialize as DEMONSTRATED")
        return {
            "system_id": self.system_id,
            "capability_id": self.capability_id,
            "coverage": self.coverage.value,
            "evidence_level": self.evidence_level.value,
            "matrix_cell": cell.value,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ParityCapability:
    """First-class RiftLens parity capability record."""

    capability_id: str
    name: str
    description: str
    reference_systems: tuple[str, ...]
    reference_evidence_level: ReferenceEvidenceLevel
    riftlens_status: RiftLensParityStatus
    required_inputs: tuple[str, ...]
    currently_available_inputs: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    current_riftlens_sources: tuple[str, ...]
    candidate_upstream_sources: tuple[str, ...]
    evaluation_method: str
    parity_dimensions: tuple[ParityDimension, ...]
    notes: str
    proposed_rp_track: str
    primary_blocker: str
    unlocks: tuple[str, ...] = ()
    exposed_by_baseline: bool = False
    materially_improves_coaching: bool = True
    related_c3_ids: tuple[str, ...] = ()

    def priority_score(self) -> int:
        """Aggressive priority: references + gap + value + baseline + unlocks."""
        score = 0
        if self.reference_systems:
            score += 1
        if self.riftlens_status in (
            RiftLensParityStatus.BLOCKED,
            RiftLensParityStatus.PARTIAL,
        ):
            score += 1
        if self.materially_improves_coaching:
            score += 1
        if self.exposed_by_baseline:
            score += 1
        if len(self.unlocks) >= 2:
            score += 1
        return score

    def priority(self) -> PriorityBand:
        return priority_band_for_score(self.priority_score())

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "reference_systems": list(self.reference_systems),
            "reference_evidence_level": self.reference_evidence_level.value,
            "riftlens_status": self.riftlens_status.value,
            "required_inputs": list(self.required_inputs),
            "currently_available_inputs": list(self.currently_available_inputs),
            "missing_inputs": list(self.missing_inputs),
            "current_riftlens_sources": list(self.current_riftlens_sources),
            "candidate_upstream_sources": list(self.candidate_upstream_sources),
            "evaluation_method": self.evaluation_method,
            "parity_dimensions": [item.value for item in self.parity_dimensions],
            "priority": self.priority().value,
            "priority_score": self.priority_score(),
            "notes": self.notes,
            "proposed_rp_track": self.proposed_rp_track,
            "primary_blocker": self.primary_blocker,
            "unlocks": list(self.unlocks),
            "exposed_by_baseline": self.exposed_by_baseline,
            "materially_improves_coaching": self.materially_improves_coaching,
            "related_c3_ids": list(self.related_c3_ids),
        }


@dataclass(frozen=True)
class LevelAnchor:
    capability_id: str
    level: ParityLevel
    behavior: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "level": int(self.level),
            "level_name": self.level.name,
            "behavior": self.behavior,
        }


@dataclass(frozen=True)
class InputSourceRow:
    """Where a missing coaching input could plausibly come from."""

    input_id: str
    riot_match: SourceAvailability
    riot_timeline: SourceAvailability
    rofl_metadata: SourceAvailability
    video_frames: SourceAvailability
    hud_cv: SourceAvailability
    ocr: SourceAvailability
    object_detection: SourceAvailability
    tracking: SourceAvailability
    minimap: SourceAvailability
    vlm: SourceAvailability
    derived_temporal: SourceAvailability
    live_client: SourceAvailability
    manual_annotation: SourceAvailability
    notes: str

    def to_dict(self) -> dict[str, str]:
        return {
            "input_id": self.input_id,
            "RIOT_MATCH": self.riot_match.value,
            "RIOT_TIMELINE": self.riot_timeline.value,
            "ROFL_METADATA": self.rofl_metadata.value,
            "video_frames": self.video_frames.value,
            "HUD_CV": self.hud_cv.value,
            "OCR": self.ocr.value,
            "object_detection": self.object_detection.value,
            "tracking": self.tracking.value,
            "minimap": self.minimap.value,
            "VLM": self.vlm.value,
            "derived_temporal": self.derived_temporal.value,
            "live_client": self.live_client.value,
            "manual_annotation": self.manual_annotation.value,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class RoadmapTrack:
    track_id: str
    name: str
    depends_on: tuple[str, ...]
    unlocks_capabilities: tuple[str, ...]
    rationale: str
    next: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "name": self.name,
            "depends_on": list(self.depends_on),
            "unlocks_capabilities": list(self.unlocks_capabilities),
            "rationale": self.rationale,
            "next": self.next,
        }


@dataclass(frozen=True)
class AcceptancePolicy:
    """How a capability becomes READY / REFERENCE-COMPARABLE."""

    ready_requires: tuple[str, ...]
    ready_forbids: tuple[str, ...]
    reference_comparable_requires: tuple[str, ...]
    provisional_note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready_requires": list(self.ready_requires),
            "ready_forbids": list(self.ready_forbids),
            "reference_comparable_requires": list(self.reference_comparable_requires),
            "provisional_note": self.provisional_note,
        }


DEFAULT_ACCEPTANCE_POLICY = AcceptancePolicy(
    ready_requires=(
        "deterministic_unit_tests",
        "curated_edge_cases",
        "real_replay_cases",
        "no_epistemic_regressions",
        "human_adjudication_when_strategic",
    ),
    ready_forbids=(
        "one_demo_success",
        "one_real_match_looks_correct",
        "vendor_claim_similarity",
        "synthetic_tests_alone",
    ),
    reference_comparable_requires=(
        "same_case_comparisons",
        "competitor_or_human_reference",
        "acceptable_agreement",
        "no_severe_false_confidence",
    ),
    provisional_note=(
        "Sample-size targets are provisional. RP.0 does not invent a required N."
    ),
)
