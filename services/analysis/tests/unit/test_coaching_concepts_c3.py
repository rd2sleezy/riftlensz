"""C.3 concept mapping, causal synthesis, and capability readiness tests."""

from __future__ import annotations

from pathlib import Path

from riftlens.coaching.concepts import (
    CONCEPTS_SCHEMA_VERSION,
    TEACHING_OUTPUT,
    CapabilityStatus,
    CausalRelation,
    CausalStatus,
    ConceptSpecificity,
    LessonPolarity,
    SignalDirection,
    SupportLevel,
    evaluate_capability_readiness,
    map_concept_signals,
    mappings_for,
    production_mapped_rule_ids,
    supported_causal_contracts,
    synthesize_lesson_candidates,
    wave_action_readiness,
)
from riftlens.coaching.context import (
    EpisodeBuilderConfig,
    build_coaching_episodes,
)
from riftlens.coaching.interpretation import (
    QualityState,
    interpret_coaching_episodes,
)
from riftlens.domain.enums import EvidenceKind, FactKind, Severity, Source
from riftlens.domain.evidence import Evidence
from riftlens.domain.fact import Fact
from riftlens.domain.finding import Finding
from tests.helpers.gst import bundled_patch, fact, make_gst, make_participant

_CONCEPTS_ROOT = Path(__file__).resolve().parents[2] / "riftlens" / "coaching" / "concepts"


def _evidence(label: str, value: object, t_ms: int) -> Evidence:
    return Evidence(
        kind=EvidenceKind.FACT,
        label=label,
        value=value,
        source=Source.RIOT_TIMELINE,
        t_ms=t_ms,
        confidence=1.0,
    )


def _finding(
    *,
    finding_id: str,
    rule_id: str,
    t_ms: int,
    concept_id: str = "TEST.CONCEPT",
    suppressed: bool = False,
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
        evidence=(_evidence("event", {"t_ms": t_ms, "rule_id": rule_id}, t_ms),),
        suppressed=suppressed,
        suppressed_by="R-001" if suppressed else None,
    )


def _simple_gst(*, duration_ms: int = 400_000, extra: list[Fact] | None = None):
    people = {1: make_participant(1), 6: make_participant(6)}
    facts = [
        fact(0, FactKind.POSITION, 1, {"x": 6000, "y": 6200}),
        fact(60_000, FactKind.POSITION, 1, {"x": 6100, "y": 6300}),
        fact(120_000, FactKind.POSITION, 1, {"x": 6200, "y": 6400}),
        fact(0, FactKind.GOLD, 1, {"currentGold": 1800, "totalGold": 2000}),
        fact(60_000, FactKind.GOLD, 1, {"currentGold": 1800, "totalGold": 2600}),
        fact(120_000, FactKind.GOLD, 1, {"currentGold": 400, "totalGold": 3200}),
        fact(0, FactKind.HEALTH, 1, {"health": 300, "healthMax": 1000}),
        fact(60_000, FactKind.HEALTH, 1, {"health": 300, "healthMax": 1000}),
        fact(120_000, FactKind.HEALTH, 1, {"health": 900, "healthMax": 1000}),
        fact(90_000, FactKind.ITEM_PURCHASED, 1, {"itemId": 1001}),
        fact(duration_ms, FactKind.GAME_END, None, {"gameId": 1}),
        *(extra or []),
    ]
    return make_gst(facts, people, match_id="C3_SIMPLE", duration_ms=duration_ms)


def _pipeline(gst, findings, pid: int = 1, *, patch=None, config=None):
    episodes = build_coaching_episodes(gst, findings, pid, config, patch=patch)
    interps = interpret_coaching_episodes(gst, episodes, pid, patch=patch)
    result = synthesize_lesson_candidates(episodes, interps, findings)
    return result, episodes, interps


def test_zero_inputs_yield_zero_lessons() -> None:
    result = synthesize_lesson_candidates([], [], [])
    assert result.lessons == ()
    assert result.signals == ()
    assert result.schema_version == CONCEPTS_SCHEMA_VERSION


def test_ct01_r002_maps_economy_not_reset_caused_death() -> None:
    gst = _simple_gst()
    item = _finding(
        finding_id="e1",
        rule_id="R-002",
        t_ms=90_000,
        concept_id="ECONOMY.SPENDING.UNSPENT_AT_DEATH",
    )
    result, _, _ = _pipeline(gst, [item])
    concepts = {signal.concept_id for signal in result.signals}
    assert "economy.resource_spending" in concepts
    for signal in result.signals:
        assert "RESET_CAUSED_DEATH" in signal.gaps or "RESET_CAUSED_DEATH" not in "".join(
            signal.gaps
        )
        assert all(code.code != "RESET_CAUSED_DEATH" for code in signal.reason_codes)
        assert "RESET_CAUSED_DEATH" in mappings_for("R-002")[0].forbidden_claims


def test_ct02_r001_maps_risk_not_player_blindness() -> None:
    gst = _simple_gst()
    item = _finding(
        finding_id="d1",
        rule_id="R-001",
        t_ms=90_000,
        concept_id="RISK.DEATH_CAUSE.UNSEEN_JUNGLER",
    )
    result, _, interps = _pipeline(gst, [item])
    assert any(s.concept_id == "risk.threat_awareness" for s in result.signals)
    mapping = mappings_for("R-001")[0]
    assert "PLAYER_COULD_NOT_SEE_JUNGLER" in mapping.forbidden_claims
    assert "FAILED_JUNGLE_TRACKING" in mapping.forbidden_claims
    assert interps[0].decision.state is QualityState.UNKNOWN
    assert all(
        "POOR" not in code.code for signal in result.signals for code in signal.reason_codes
    )


def test_ct03_r005_cs_loss_not_wave_management_error() -> None:
    gst = _simple_gst()
    item = _finding(
        finding_id="cs1",
        rule_id="R-005",
        t_ms=100_000,
        concept_id="LANING.FARM.CS_COLLAPSE_AFTER_DEATH",
    )
    result, _, _ = _pipeline(gst, [item])
    assert any(s.concept_id == "laning.cs_maintenance" for s in result.signals)
    assert not any(s.concept_id == "wave.management" for s in result.signals)
    assert "WAVE_MANAGEMENT_ERROR" in mappings_for("R-005")[0].forbidden_claims


def test_ct04_r008_objective_absence_not_bad_macro_decision() -> None:
    gst = _simple_gst()
    item = _finding(
        finding_id="o1",
        rule_id="R-008",
        t_ms=120_000,
        concept_id="MACRO.OBJECTIVES.NO_SHOW",
    )
    result, _, _ = _pipeline(gst, [item])
    assert any(s.concept_id == "objective.presence" for s in result.signals)
    assert "BAD_MACRO_DECISION" in mappings_for("R-008")[0].forbidden_claims


def test_ct05_strength_produces_positive_signals() -> None:
    gst = _simple_gst()
    item = _finding(
        finding_id="p1",
        rule_id="P-001",
        t_ms=90_000,
        concept_id="STRENGTH.CLEAN_LANE_PHASE",
    )
    result, _, _ = _pipeline(gst, [item])
    positives = [s for s in result.signals if s.direction is SignalDirection.POSITIVE]
    assert positives
    assert any(s.concept_id == "strength.clean_lane" for s in positives)
    lesson = next(item for item in result.lessons if item.concept_id == "strength.clean_lane")
    assert lesson.polarity is LessonPolarity.CONSISTENT_POSITIVE


def test_ct06_unknown_rule_fails_broad() -> None:
    rows = mappings_for("R-999")
    assert rows[0].specificity is ConceptSpecificity.UNRESOLVED
    assert rows[0].concept_id == "context.risk_broad"


def test_ca01_temporally_adjacent_unrelated_no_supported_causality() -> None:
    gst = _simple_gst()
    findings = [
        _finding(
            finding_id="a",
            rule_id="R-010",
            t_ms=90_000,
            concept_id="VISION.DENIAL.NO_CONTROL_WARDS",
        ),
        _finding(
            finding_id="b",
            rule_id="R-016",
            t_ms=95_000,
            concept_id="LANING.LEVEL_SPIKES.DEFICIT_AT_SPIKE",
        ),
    ]
    result, _, _ = _pipeline(gst, findings)
    assert result.hypotheses
    assert all(h.status is not CausalStatus.SUPPORTED for h in result.hypotheses)
    assert all(
        "TEMPORAL_ORDER_ONLY" in {c.code for c in h.reason_codes} or h.h8_prior
        for h in result.hypotheses
    )


def test_ca02_h8_prior_may_plausible_never_supported_by_default() -> None:
    gst = _simple_gst()
    findings = [
        _finding(
            finding_id="u",
            rule_id="R-001",
            t_ms=80_000,
            concept_id="RISK.DEATH_CAUSE.UNSEEN_JUNGLER",
        ),
        _finding(
            finding_id="c",
            rule_id="R-005",
            t_ms=100_000,
            concept_id="LANING.FARM.CS_COLLAPSE_AFTER_DEATH",
        ),
    ]
    result, _, _ = _pipeline(gst, findings)
    h8_rows = [h for h in result.hypotheses if h.h8_prior]
    assert h8_rows
    assert all(h.status is CausalStatus.PLAUSIBLE for h in h8_rows)
    assert all(h.status is not CausalStatus.SUPPORTED for h in h8_rows)
    assert supported_causal_contracts() == {}


def test_ca03_temporal_precedence_alone_not_supported() -> None:
    gst = _simple_gst()
    findings = [
        _finding(
            finding_id="a",
            rule_id="R-006",
            t_ms=70_000,
            concept_id="ECONOMY.SPENDING.DEAD_GOLD",
        ),
        _finding(
            finding_id="b",
            rule_id="R-019",
            t_ms=200_000,
            concept_id="ECONOMY.INCOME.LOW_CONVERSION",
        ),
    ]
    result, _, _ = _pipeline(gst, findings)
    temporal = [
        h
        for h in result.hypotheses
        if h.relation
        in {
            CausalRelation.TEMPORALLY_PRECEDES,
            CausalRelation.TEMPORALLY_FOLLOWS,
            CausalRelation.TEMPORALLY_OVERLAPS,
            CausalRelation.SHARES_CONCEPT,
            CausalRelation.UNRELATED,
            CausalRelation.POTENTIAL_ANTECEDENT,
        }
    ]
    assert temporal
    assert all(h.status is not CausalStatus.SUPPORTED for h in temporal)


def test_ca04_resolution_affects_persistence_not_decision() -> None:
    gst = _simple_gst()
    item = _finding(
        finding_id="r7",
        rule_id="R-007",
        t_ms=60_000,
        concept_id="LANING.RECALL_TIMING.RECALL_WITH_EXCESS_GOLD",
    )
    result, episodes, interps = _pipeline(
        gst,
        [item],
        patch=bundled_patch(),
        config=EpisodeBuilderConfig(post_context_ms=90_000),
    )
    assert episodes
    assert interps[0].decision.state is QualityState.UNKNOWN
    # Purchase at 90s may resolve R-007 after 60s anchor depending on resolver.
    for lesson in result.lessons:
        if lesson.concept_id == "economy.reset_timing":
            assert lesson.support_level in {
                SupportLevel.WEAK,
                SupportLevel.INSUFFICIENT,
                SupportLevel.MODERATE,
            }
            if lesson.condition_resolution_notes:
                assert any(
                    "CONDITION_RESOLUTION_REDUCES_PERSISTENCE" in code.code
                    for code in lesson.reason_codes
                )


def test_ca05_c2_unknown_not_transformed_to_poor() -> None:
    gst = _simple_gst()
    item = _finding(
        finding_id="d1",
        rule_id="R-001",
        t_ms=90_000,
        concept_id="RISK.DEATH_CAUSE.UNSEEN_JUNGLER",
    )
    result, _, interps = _pipeline(gst, [item])
    assert interps[0].decision.state is QualityState.UNKNOWN
    # Forbidden claim names may appear as gaps; they must not become reason verdicts.
    assert all(
        code.code
        not in {
            "POOR_DECISION",
            "BAD_DECISION",
            "FAILED_JUNGLE_TRACKING",
            "PLAYER_COULD_NOT_SEE_JUNGLER",
        }
        for signal in result.signals
        for code in signal.reason_codes
    )
    assert any(
        code.code == "C2_DECISION_REMAINS_UNKNOWN"
        for signal in result.signals
        for code in signal.reason_codes
    )


def test_ca06_conflicting_positive_negative_preserved() -> None:
    gst = _simple_gst()
    findings = [
        _finding(
            finding_id="n1",
            rule_id="R-007",
            t_ms=60_000,
            concept_id="LANING.RECALL_TIMING.RECALL_WITH_EXCESS_GOLD",
        ),
        _finding(
            finding_id="p2",
            rule_id="P-002",
            t_ms=180_000,
            concept_id="STRENGTH.EFFICIENT_RESETS",
        ),
    ]
    result, _, _ = _pipeline(gst, findings)
    # P-002 also maps broadly to economy.reset_timing
    reset_lessons = [item for item in result.lessons if item.concept_id == "economy.reset_timing"]
    assert reset_lessons
    lesson = reset_lessons[0]
    assert lesson.polarity is LessonPolarity.MIXED
    assert lesson.positive_signal_ids
    assert lesson.negative_signal_ids
    assert lesson.conflicting_evidence


def test_cr01_wave_recommendation_blocked() -> None:
    caps = {item.id: item for item in evaluate_capability_readiness()}
    assert caps["CAP-WAVE-STATE"].readiness is CapabilityStatus.BLOCKED
    assert caps["CAP-WAVE-ACTION"].readiness is CapabilityStatus.BLOCKED
    assert caps["CAP-WAVE-ACTION"].can_safely_mimic is False
    actions = wave_action_readiness()
    assert actions["freeze"] is CapabilityStatus.BLOCKED
    assert actions["slow_push"] is CapabilityStatus.BLOCKED
    assert actions["hard_push"] is CapabilityStatus.BLOCKED
    assert actions["crash"] is CapabilityStatus.BLOCKED
    assert actions["bounce"] is CapabilityStatus.BLOCKED
    assert actions["hold"] is CapabilityStatus.BLOCKED


def test_cr02_mechanical_execution_blocked() -> None:
    cap = next(item for item in evaluate_capability_readiness(("CAP-MECHANICAL-EXECUTION",)))
    assert cap.readiness is CapabilityStatus.BLOCKED


def test_cr03_vision_quality_blocked() -> None:
    cap = next(item for item in evaluate_capability_readiness(("CAP-VISION-QUALITY",)))
    assert cap.readiness is CapabilityStatus.BLOCKED
    assert "ward_positions" in cap.missing_evidence


def test_cr04_resource_spending_partial() -> None:
    cap = next(item for item in evaluate_capability_readiness(("CAP-RESOURCE-SPENDING",)))
    assert cap.readiness is CapabilityStatus.PARTIAL
    assert cap.can_safely_mimic is True


def test_cr05_missing_evidence_deterministic() -> None:
    a = evaluate_capability_readiness()
    b = evaluate_capability_readiness()
    assert [item.to_dict() for item in a] == [item.to_dict() for item in b]


def test_cr06_related_rule_does_not_make_wave_ready() -> None:
    gst = _simple_gst()
    item = _finding(
        finding_id="cs1",
        rule_id="R-005",
        t_ms=100_000,
        concept_id="LANING.FARM.CS_COLLAPSE_AFTER_DEATH",
    )
    result, _, _ = _pipeline(gst, [item])
    wave = next(item for item in result.capabilities if item.id == "CAP-WAVE-ACTION")
    assert wave.readiness is CapabilityStatus.BLOCKED
    assert not any(s.concept_id == "wave.management" for s in result.signals)


def test_reference_freeze_not_emitted_when_wave_blocked() -> None:
    result = synthesize_lesson_candidates([], [])
    blob = str(result.to_dict()) + str([c.to_dict() for c in evaluate_capability_readiness()])
    assert "FREEZE_RECOMMENDATION" not in blob
    assert "freeze" in wave_action_readiness()


def test_all_production_rules_mapped() -> None:
    expected = tuple(
        sorted(
            tuple(f"R-{i:03d}" for i in range(1, 21))
            + tuple(f"P-{i:03d}" for i in range(1, 6))
        )
    )
    assert production_mapped_rule_ids() == expected


def test_within_match_recurrence_not_cross_game_habit() -> None:
    gst = _simple_gst()
    findings = [
        _finding(
            finding_id=f"d{i}",
            rule_id="R-001",
            t_ms=60_000 + i * 40_000,
            concept_id="RISK.DEATH_CAUSE.UNSEEN_JUNGLER",
        )
        for i in range(3)
    ]
    result, _, _ = _pipeline(gst, findings)
    threat = next(item for item in result.lessons if item.concept_id == "risk.threat_awareness")
    assert threat.within_match_occurrences == 3
    assert any(code.code == "WITHIN_MATCH_ONLY" for code in threat.reason_codes)
    assert "habit" not in threat.to_dict().get("prioritization", "").lower()


def test_no_teaching_output() -> None:
    gst = _simple_gst()
    item = _finding(finding_id="d1", rule_id="R-001", t_ms=90_000)
    result, _, _ = _pipeline(gst, [item])
    assert all(lesson.teaching_output == TEACHING_OUTPUT for lesson in result.lessons)
    blob = str(result.to_dict()).lower()
    assert "you should" not in blob
    assert "drill" not in blob


def test_determinism() -> None:
    gst = _simple_gst()
    findings = [
        _finding(finding_id="d1", rule_id="R-001", t_ms=90_000),
        _finding(finding_id="e1", rule_id="R-002", t_ms=90_000),
    ]
    a, _, _ = _pipeline(gst, findings)
    b, _, _ = _pipeline(gst, findings)
    assert a.to_dict() == b.to_dict()


def test_map_concept_signals_empty_safe() -> None:
    assert map_concept_signals([], []) == []


def test_import_isolation_scan() -> None:
    banned = (
        "riftlens.visual",
        "riftlens.replay_host",
        "riftlens.coaching.providers",
        "riftlens.coaching.composer",
        "openai",
        "anthropic",
    )
    for path in _CONCEPTS_ROOT.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{path.name} imports {token}"
