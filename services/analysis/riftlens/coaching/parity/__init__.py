"""RP.0 reference-parity benchmark package. Not a production review path."""

from __future__ import annotations

from riftlens.coaching.parity.capabilities import (
    CAPABILITY_IDS,
    all_capabilities,
    capability_by_id,
)
from riftlens.coaching.parity.cases import (
    BASELINE_CHAMPION,
    BASELINE_MATCH_ID,
    BASELINE_PARTICIPANT_ID,
    BASELINE_ROLE,
    ParityCase,
    build_vladimir_baseline_cases,
    conversion_wave_blocker_case,
    fight_reason_mismatch_case,
)
from riftlens.coaching.parity.dimensions import (
    DIMENSION_DEFINITIONS,
    FIGHT_SELECTION_ANCHORS,
    all_dimensions,
    all_level_anchors,
    anchor_for,
)
from riftlens.coaching.parity.ingestion import (
    ManualCompetitorReference,
    record_manual_reference,
    reject_automated_ingest_request,
)
from riftlens.coaching.parity.models import (
    BASELINE_ADJUDICATION_LABEL,
    DEFAULT_ACCEPTANCE_POLICY,
    HUMAN_QUALITY_VALIDATION,
    PARITY_SCHEMA_VERSION,
    AdjudicationVerdict,
    MatrixCell,
    ParityDimension,
    ParityLevel,
    PriorityBand,
    ReferenceCoverage,
    ReferenceEvidenceLevel,
    RiftLensParityStatus,
    derive_matrix_cell,
)
from riftlens.coaching.parity.privacy import PrivacyError, assert_no_sensitive
from riftlens.coaching.parity.references import (
    assert_vendor_claims_not_demonstrated,
    notes_for_capability,
)
from riftlens.coaching.parity.report import (
    render_baseline,
    render_gaps,
    render_matrix,
    render_roadmap,
    render_sources,
)
from riftlens.coaching.parity.roadmap import next_track, ranked_capabilities, top_gaps

__all__ = [
    "BASELINE_ADJUDICATION_LABEL",
    "BASELINE_CHAMPION",
    "BASELINE_MATCH_ID",
    "BASELINE_PARTICIPANT_ID",
    "BASELINE_ROLE",
    "CAPABILITY_IDS",
    "DEFAULT_ACCEPTANCE_POLICY",
    "DIMENSION_DEFINITIONS",
    "FIGHT_SELECTION_ANCHORS",
    "HUMAN_QUALITY_VALIDATION",
    "PARITY_SCHEMA_VERSION",
    "AdjudicationVerdict",
    "ManualCompetitorReference",
    "MatrixCell",
    "ParityCase",
    "ParityDimension",
    "ParityLevel",
    "PriorityBand",
    "PrivacyError",
    "ReferenceCoverage",
    "ReferenceEvidenceLevel",
    "RiftLensParityStatus",
    "all_capabilities",
    "all_dimensions",
    "all_level_anchors",
    "anchor_for",
    "assert_no_sensitive",
    "assert_vendor_claims_not_demonstrated",
    "build_vladimir_baseline_cases",
    "capability_by_id",
    "conversion_wave_blocker_case",
    "derive_matrix_cell",
    "fight_reason_mismatch_case",
    "next_track",
    "notes_for_capability",
    "ranked_capabilities",
    "record_manual_reference",
    "reject_automated_ingest_request",
    "render_baseline",
    "render_gaps",
    "render_matrix",
    "render_roadmap",
    "render_sources",
    "top_gaps",
]
