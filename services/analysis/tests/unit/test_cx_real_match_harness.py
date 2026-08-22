"""Developer harness plumbing tests — no Riot network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from riftlens.analysis.rules.engine import RuleEngine
from riftlens.analysis.rules.lab import production_rules
from riftlens.analysis.rules.loader import load_rule_pack
from riftlens.coaching.concepts.models import CapabilityStatus
from riftlens.coaching.longitudinal import PatternStatus
from riftlens.coaching.prioritization.models import LessonTier
from riftlens.coaching.validation import (
    assert_safe_output_path,
    format_human_report,
    run_cx_pipeline,
    validate_participant_id,
)
from riftlens.domain.enums import EvidenceKind, FactKind, Severity, Source
from riftlens.domain.evidence import Evidence
from riftlens.domain.finding import Finding
from tests.helpers.gst import bundled_patch, load_gst, make_gst, make_participant
from tests.helpers.gst import fact as make_fact

_REPO = Path(__file__).resolve().parents[3]


def _finding(
    *,
    finding_id: str,
    rule_id: str,
    t_ms: int,
    concept_id: str = "economy.resource_spending",
) -> Finding:
    return Finding(
        id=finding_id,
        rule_id=rule_id,
        rule_version=1,
        concept_id=concept_id,
        t_ms=t_ms,
        severity=Severity.MEDIUM,
        confidence=0.9,
        title=rule_id,
        evidence=(
            Evidence(
                kind=EvidenceKind.FACT,
                label="event",
                value={"t_ms": t_ms, "rule_id": rule_id},
                source=Source.RIOT_TIMELINE,
                t_ms=t_ms,
                confidence=1.0,
            ),
        ),
    )


def test_harness01_fixture_runs_c1_to_c5() -> None:
    gst = load_gst("NA1_fixture_a")
    pid = next(iter(gst.participants))
    pack = load_rule_pack()
    rules = production_rules(pack)
    from riftlens.analysis.rules.models import RulePack

    patch = bundled_patch(gst.patch)
    findings = RuleEngine(RulePack(rules, tuple(pack.concept_ids)), patch=patch).run(
        gst, pid
    )
    result = run_cx_pipeline(gst, findings, pid, patch=patch)
    assert result.match_id
    assert result.participant_id == pid
    # Pipeline completes even if this unpaired fixture yields few/no lessons
    blob = result.to_dict()
    assert "c1_episodes" in blob
    assert "c5_teaching" in blob
    report = format_human_report(result)
    assert "RIFTLENS C.x REAL MATCH VALIDATION" in report
    assert "HUMAN QUALITY VALIDATION" in report


def test_harness02_zero_findings_clean() -> None:
    gst = make_gst(
        [make_fact(0, FactKind.POSITION, 1, {"x": 1, "y": 1})],
        {1: make_participant(1)},
        match_id="ZERO",
    )
    result = run_cx_pipeline(gst, [], 1)
    assert result.finding_count == 0
    assert result.episodes == ()
    assert result.synthesis.lessons == ()
    assert result.prioritized.major == ()
    assert "Primary C.5 teaching lesson: NONE" in format_human_report(result)


def test_harness03_participant_validation() -> None:
    with pytest.raises(ValueError):
        validate_participant_id(0)
    with pytest.raises(ValueError):
        validate_participant_id(11)
    validate_participant_id(1)


def test_harness04_json_deterministic() -> None:
    gst = make_gst(
        [make_fact(60_000, FactKind.GOLD, 1, {"currentGold": 2000, "totalGold": 2000})],
        {1: make_participant(1)},
        match_id="DET",
    )
    findings = [_finding(finding_id="f1", rule_id="R-006", t_ms=60_000)]
    a = run_cx_pipeline(gst, findings, 1).to_dict()
    b = run_cx_pipeline(gst, findings, 1).to_dict()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_harness05_no_puuid_in_report() -> None:
    gst = make_gst(
        [make_fact(60_000, FactKind.GOLD, 1, {"currentGold": 2500, "totalGold": 2500})],
        {1: make_participant(1)},
        match_id="PRIV",
    )
    assert gst.participants[1].puuid.startswith("puuid-")
    findings = [_finding(finding_id="f1", rule_id="R-006", t_ms=60_000)]
    report = format_human_report(run_cx_pipeline(gst, findings, 1))
    assert "puuid-" not in report.lower()
    assert "summoner_name" not in report.lower()
    assert "riot_id" not in report.lower()
    assert "api_key" not in report.lower()


def test_harness06_c4_tiers_preserved() -> None:
    gst = make_gst(
        [make_fact(90_000, FactKind.GOLD, 1, {"currentGold": 3000, "totalGold": 3000})],
        {1: make_participant(1)},
        match_id="TIER",
    )
    findings = [_finding(finding_id="f1", rule_id="R-006", t_ms=90_000)]
    result = run_cx_pipeline(gst, findings, 1)
    for row in result.prioritized.major:
        assert row.tier is LessonTier.MAJOR
    for row in result.prioritized.secondary:
        assert row.tier is LessonTier.SECONDARY
    for row in result.prioritized.strengths:
        assert row.tier is LessonTier.STRENGTH
    for row in result.prioritized.withheld:
        assert row.tier is LessonTier.WITHHELD


def test_harness07_c5_teaching_fields_when_major() -> None:
    gst = make_gst(
        [make_fact(90_000, FactKind.GOLD, 1, {"currentGold": 3000, "totalGold": 3000})],
        {1: make_participant(1)},
        match_id="TEACH",
    )
    findings = [_finding(finding_id="f1", rule_id="R-006", t_ms=90_000)]
    result = run_cx_pipeline(gst, findings, 1)
    if not result.teaching.lessons:
        pytest.skip("no teaching lessons produced for synthetic finding")
    major = [item for item in result.teaching.lessons if item.tier == LessonTier.MAJOR.value]
    if not major:
        pytest.skip("no MAJOR teaching lesson")
    lesson = major[0]
    # Preserve whatever C.5 emitted — do not invent
    rendered = result.teaching_render
    assert lesson.concept_id in rendered
    if lesson.recognition_cue is not None:
        assert "CUE:" in rendered
    if lesson.memorable_rule is not None:
        assert "RULE:" in rendered
    if lesson.drill is not None:
        assert "DRILL" in rendered
    if lesson.objective is not None:
        assert "OBJECTIVE" in rendered


def test_harness08_blocked_capability_visible() -> None:
    gst = make_gst(
        [make_fact(0, FactKind.POSITION, 1, {"x": 1, "y": 1})],
        {1: make_participant(1)},
        match_id="BLOCK",
    )
    result = run_cx_pipeline(gst, [], 1)
    blocked = [
        item
        for item in result.synthesis.capabilities
        if item.readiness is CapabilityStatus.BLOCKED
    ]
    assert blocked
    report = format_human_report(result)
    assert "BLOCKED" in report


def test_harness09_c6_single_game_not_recurring() -> None:
    gst = make_gst(
        [make_fact(90_000, FactKind.GOLD, 1, {"currentGold": 3000, "totalGold": 3000})],
        {1: make_participant(1)},
        match_id="C6ONE",
    )
    findings = [_finding(finding_id="f1", rule_id="R-006", t_ms=90_000)]
    result = run_cx_pipeline(gst, findings, 1, include_c6=True)
    assert result.c6_state is not None
    assert any("C6_SINGLE_GAME_ADAPTER_PARTIAL" in note for note in result.c6_notes)
    for hist in result.c6_state.concept_histories:
        assert hist.status is not PatternStatus.RECURRING


def test_harness10_c7_hard_fail_surface() -> None:
    gst = make_gst(
        [make_fact(0, FactKind.POSITION, 1, {"x": 1, "y": 1})],
        {1: make_participant(1)},
        match_id="C7",
    )
    result = run_cx_pipeline(gst, [], 1, include_c7=True)
    assert result.c7_passed is True
    assert result.c7_hard_fails == ()
    report = format_human_report(result)
    assert "HUMAN QUALITY VALIDATION = NOT PERFORMED" in report
    assert "Automated PASS does NOT mean" in report


def test_out_path_refuses_repo() -> None:
    with pytest.raises(ValueError, match="Refusing"):
        assert_safe_output_path(_REPO / "docs" / "tmp_cx.json", repo_root=_REPO)
    safe = assert_safe_output_path(Path("/tmp/cx_validation_out.json"), repo_root=_REPO)
    assert safe.name == "cx_validation_out.json"
