"""RP.0 reference-parity tests. No Riot network. No production wiring."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from riftlens.coaching.evaluation import EVALUATION_SCHEMA_VERSION, HUMAN_VALIDATION_STATUS
from riftlens.coaching.parity import (
    BASELINE_ADJUDICATION_LABEL,
    BASELINE_CHAMPION,
    BASELINE_MATCH_ID,
    BASELINE_PARTICIPANT_ID,
    BASELINE_ROLE,
    CAPABILITY_IDS,
    DEFAULT_ACCEPTANCE_POLICY,
    HUMAN_QUALITY_VALIDATION,
    PARITY_SCHEMA_VERSION,
    AdjudicationVerdict,
    MatrixCell,
    ParityDimension,
    ParityLevel,
    PrivacyError,
    ReferenceCoverage,
    ReferenceEvidenceLevel,
    RiftLensParityStatus,
    all_capabilities,
    all_dimensions,
    all_level_anchors,
    anchor_for,
    assert_vendor_claims_not_demonstrated,
    build_vladimir_baseline_cases,
    conversion_wave_blocker_case,
    derive_matrix_cell,
    fight_reason_mismatch_case,
    next_track,
    notes_for_capability,
    ranked_capabilities,
    record_manual_reference,
    reject_automated_ingest_request,
    render_baseline,
    render_gaps,
    render_matrix,
    render_roadmap,
    top_gaps,
)
from riftlens.coaching.parity.privacy import assert_no_sensitive
from riftlens.coaching.parity.references import REFERENCE_MATRIX, all_reference_systems

_ANALYSIS_ROOT = Path(__file__).resolve().parents[2]
_RIFTLENS = _ANALYSIS_ROOT / "riftlens"
_PRODUCTION_ROOTS = (
    _RIFTLENS / "api",
    _RIFTLENS / "pipeline",
    _RIFTLENS / "analysis",
    _RIFTLENS / "orchestration",
    _RIFTLENS / "visual",
    _RIFTLENS / "replay_host",
    _RIFTLENS / "coaching" / "context",
    _RIFTLENS / "coaching" / "interpretation",
    _RIFTLENS / "coaching" / "concepts",
    _RIFTLENS / "coaching" / "prioritization",
    _RIFTLENS / "coaching" / "teaching",
    _RIFTLENS / "coaching" / "longitudinal",
    _RIFTLENS / "coaching" / "evaluation",
    _RIFTLENS / "coaching" / "items.py",
    _RIFTLENS / "coaching" / "prioritizer.py",
    _RIFTLENS / "coaching" / "bundler.py",
    _RIFTLENS / "coaching" / "composer.py",
    _RIFTLENS / "coaching" / "__init__.py",
)


def test_rp0_01_capability_registry_deterministic() -> None:
    first = [(cap.capability_id, cap.riftlens_status.value) for cap in all_capabilities()]
    second = [(cap.capability_id, cap.riftlens_status.value) for cap in all_capabilities()]
    assert first == second
    assert first == sorted(first, key=lambda row: row[0])
    assert len(first) == len(CAPABILITY_IDS)
    assert "RP-CAP-WAVE-STATE" in CAPABILITY_IDS
    assert "RP-CAP-FIGHT-SELECTION" in CAPABILITY_IDS
    assert PARITY_SCHEMA_VERSION == "rp.0"


def test_rp0_02_valid_status_and_evidence_enums() -> None:
    statuses = {cap.riftlens_status for cap in all_capabilities()}
    allowed = set(RiftLensParityStatus)
    assert statuses <= allowed
    for cap in all_capabilities():
        assert cap.reference_evidence_level in set(ReferenceEvidenceLevel)
        assert cap.missing_inputs or cap.riftlens_status in {
            RiftLensParityStatus.READY,
            RiftLensParityStatus.REFERENCE_ONLY,
            RiftLensParityStatus.PARTIAL,
        }


def test_rp0_03_vendor_claim_not_demonstrated() -> None:
    assert_vendor_claims_not_demonstrated()
    cell = derive_matrix_cell(
        ReferenceEvidenceLevel.VENDOR_CLAIM,
        ReferenceCoverage.FULL,
    )
    assert cell is MatrixCell.CLAIMED
    assert cell is not MatrixCell.DEMONSTRATED
    wave_notes = notes_for_capability("RP-CAP-WAVE-STATE")
    middiff = next(note for note in wave_notes if note.system_id == "middiff")
    assert middiff.evidence_level is ReferenceEvidenceLevel.VENDOR_CLAIM
    assert middiff.matrix_cell() is MatrixCell.CLAIMED
    dumped = middiff.to_dict()
    assert dumped["matrix_cell"] != MatrixCell.DEMONSTRATED.value
    assert dumped["evidence_level"] == ReferenceEvidenceLevel.VENDOR_CLAIM.value


def test_rp0_04_baseline_vladimir_accurate() -> None:
    cases = build_vladimir_baseline_cases()
    assert cases
    for case in cases:
        ctx = case.game_context
        assert ctx.match_id == BASELINE_MATCH_ID
        assert ctx.participant_id == BASELINE_PARTICIPANT_ID
        assert ctx.champion == BASELINE_CHAMPION
        assert ctx.role == BASELINE_ROLE
        assert case.human_adjudication.label == BASELINE_ADJUDICATION_LABEL
        payload = case.to_dict()
        blob = str(payload).lower()
        assert "puuid" not in blob
        assert "summoner_name" not in blob
    ids = {case.case_id for case in cases}
    assert "RP0-VLAD-0707-OBJECTIVE" in ids
    assert "RP0-VLAD-3124-FIGHT-REASON" in ids
    assert "RP0-VLAD-CONVERSION-OVERALL" in ids
    obj = next(case for case in cases if case.case_id == "RP0-VLAD-0707-OBJECTIVE")
    assert obj.human_adjudication.verdict is AdjudicationVerdict.PARTLY
    assert obj.t_ms == 427_000
    roam = next(case for case in cases if case.case_id == "RP0-VLAD-2400-ROAM")
    assert roam.human_adjudication.verdict is AdjudicationVerdict.DISAGREE
    lane = next(case for case in cases if case.case_id == "RP0-VLAD-1400-LANE")
    assert lane.human_adjudication.verdict is AdjudicationVerdict.AGREE


def test_rp0_05_fight_reason_mismatch_preserved() -> None:
    case = fight_reason_mismatch_case()
    assert case.clock_label == "31:24"
    assert case.t_ms == 1_884_000
    assert case.riftlens_output is not None
    rl = case.riftlens_output.reason_code
    human = case.human_adjudication.reason_code
    assert rl == "unaccounted_enemies"
    assert human == "knowingly_entered_1v3"
    assert rl != human
    assert case.human_adjudication.verdict is AdjudicationVerdict.PARTLY
    assert "wrong reason" in case.notes.lower() or "wrong reason" in case.notes


def test_rp0_06_post_fight_wave_state_blocker() -> None:
    case = conversion_wave_blocker_case()
    assert "RP-CAP-WAVE-STATE" in case.required_capabilities
    assert "wave_state" in case.missing_inputs
    assert case.human_adjudication.verdict is AdjudicationVerdict.PARTLY
    wave = next(cap for cap in all_capabilities() if cap.capability_id == "RP-CAP-WAVE-STATE")
    assert wave.riftlens_status is RiftLensParityStatus.BLOCKED
    assert wave.exposed_by_baseline is True
    text = render_baseline()
    assert "cannot judge conversion correctly without wave state" in text.lower() or (
        "without wave state" in text.lower()
    )


def test_rp0_07_manual_competitor_reference() -> None:
    record = record_manual_reference(
        reference_id="ref-questie-1",
        system_id="questie",
        paraphrase="Questie recommended freezing the wave before recalling.",
        observed_on="2026-08-21",
        evidence_level=ReferenceEvidenceLevel.VENDOR_CLAIM,
        t_ms=427_000,
        case_id="RP0-VLAD-0707-OBJECTIVE",
        confidence=0.4,
    )
    dumped = record.to_dict()
    assert dumped["paraphrase"].startswith("Questie recommended")
    assert dumped["evidence_level"] == "VENDOR_CLAIM"
    with pytest.raises(PrivacyError):
        reject_automated_ingest_request("scrape")


def test_rp0_08_privacy_fields_rejected() -> None:
    with pytest.raises(PrivacyError):
        assert_no_sensitive({"puuid": "abc"}, context="test")
    with pytest.raises(PrivacyError):
        record_manual_reference(
            reference_id="bad",
            system_id="questie",
            paraphrase="player puuid-12345 should freeze",
            observed_on="2026-08-21",
        )
    baseline = render_baseline().lower()
    assert "puuid" not in baseline
    assert "api_key" not in baseline
    assert "summoner_name" not in baseline


def test_rp0_09_parity_levels_rubric_deterministic() -> None:
    anchors = all_level_anchors()
    assert anchors == all_level_anchors()
    assert len(all_dimensions()) == 12
    assert ParityDimension.DETECTION in all_dimensions()
    text = anchor_for("RP-CAP-FIGHT-SELECTION", ParityLevel.REFERENCE_COMPARABLE)
    assert "unaccounted" in text
    assert "knowingly outnumbered" in text
    generic = anchor_for("RP-CAP-ROAM", ParityLevel.ABSENT)
    assert "Cannot identify" in generic or "cannot identify" in generic.lower()


def test_rp0_10_roadmap_priority_deterministic() -> None:
    first = [(cap.capability_id, cap.priority_score()) for cap in ranked_capabilities()]
    second = [(cap.capability_id, cap.priority_score()) for cap in ranked_capabilities()]
    assert first == second
    gaps_a = [cap.capability_id for cap in top_gaps()]
    gaps_b = [cap.capability_id for cap in top_gaps()]
    assert gaps_a == gaps_b
    ranked_ids = [cap.capability_id for cap in ranked_capabilities()]
    assert gaps_a[0] in ranked_ids
    assert next_track().track_id == "RP.1"
    assert "RP.1" in render_roadmap()
    gap_text = render_gaps()
    assert gap_text == render_gaps()
    assert "TOP PARITY GAPS" in gap_text
    assert "RP-CAP-WAVE-STATE" in gap_text
    assert "RP-CAP-FIGHT-SELECTION" in gap_text
    ready_forbids = DEFAULT_ACCEPTANCE_POLICY.ready_forbids
    assert "one_demo_success" in ready_forbids


def test_rp0_11_no_production_dependency() -> None:
    hits: list[str] = []
    for root in _PRODUCTION_ROOTS:
        paths = [root] if root.is_file() else list(root.rglob("*.py"))
        for path in paths:
            source = path.read_text(encoding="utf-8")
            if "coaching.parity" in source or "coaching/parity" in source:
                hits.append(str(path.relative_to(_ANALYSIS_ROOT)))
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if "coaching.parity" in node.module:
                        hits.append(str(path.relative_to(_ANALYSIS_ROOT)))
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "coaching.parity" in alias.name:
                            hits.append(str(path.relative_to(_ANALYSIS_ROOT)))
    assert hits == []
    matrix = render_matrix()
    assert "CLAIMED" in matrix
    assert "VENDOR_CLAIM never serializes as DEMONSTRATED" in matrix


def test_rp0_12_c7_surface_unchanged() -> None:
    assert EVALUATION_SCHEMA_VERSION == "c7.0"
    assert HUMAN_VALIDATION_STATUS == "NOT_YET_PERFORMED"
    assert HUMAN_QUALITY_VALIDATION == "NOT_YET_PERFORMED"
    coaching_init = (_RIFTLENS / "coaching" / "__init__.py").read_text(encoding="utf-8")
    assert "coaching.parity" not in coaching_init


def test_reference_systems_cover_required_names() -> None:
    ids = {item.system_id for item in all_reference_systems()}
    for required in (
        "middiff",
        "questie",
        "hakko",
        "replays_lol",
        "trenix",
        "mobalytics",
        "itero",
        "skill_capped",
        "human_coach",
    ):
        assert required in ids
    assert set(REFERENCE_MATRIX) == set(CAPABILITY_IDS)


def test_human_coach_can_be_demonstrated() -> None:
    notes = notes_for_capability("RP-CAP-HUMAN-DECISION-REASONING")
    human = next(note for note in notes if note.system_id == "human_coach")
    assert human.evidence_level is ReferenceEvidenceLevel.HUMAN_REFERENCE
    assert human.matrix_cell() is MatrixCell.DEMONSTRATED
