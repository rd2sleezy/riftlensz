"""C.2 decision/event interpretation tests and reference-behavior suite."""

from __future__ import annotations

from pathlib import Path

from riftlens.coaching.context import (
    EpisodeBuilderConfig,
    build_coaching_episodes,
)
from riftlens.coaching.interpretation import (
    ALTERNATIVE_ANALYSIS_NOT_IMPLEMENTED,
    EPISODE_INTERPRETATION_SCHEMA_VERSION,
    ActionabilityState,
    DecisionOutcomeRelation,
    KnowledgeStatus,
    OutcomePolarity,
    QualityState,
    derive_decision_outcome_relation,
    evidence_contracts,
    interpret_coaching_episodes,
    production_rule_ids,
    profile_for,
)
from riftlens.coaching.interpretation.models import ObservedOutcome, OutcomeKind, ReasonCode
from riftlens.domain.enums import EvidenceKind, FactKind, Severity, Source
from riftlens.domain.evidence import Evidence
from riftlens.domain.fact import Fact
from riftlens.domain.finding import Finding
from tests.helpers.gst import bundled_patch, fact, load_gst, make_gst, make_participant
from tests.helpers.synthetic import RIVER_ENEMY_FOR_BLUE, buy, kill, quiet_frames, roster

_INTERP_ROOT = Path(__file__).resolve().parents[2] / "riftlens" / "coaching" / "interpretation"


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
    extra: tuple[Evidence, ...] = (),
) -> Finding:
    items = (_evidence("event", {"t_ms": t_ms, "rule_id": rule_id}, t_ms), *extra)
    return Finding(
        id=finding_id,
        rule_id=rule_id,
        rule_version=1,
        concept_id=concept_id,
        t_ms=t_ms,
        severity=Severity.MEDIUM,
        confidence=0.9,
        title=rule_id,
        evidence=items,
        suppressed=suppressed,
        suppressed_by="R-001" if suppressed else None,
    )


def _simple_gst(*, duration_ms: int = 300_000, extra: list[Fact] | None = None):
    people = {1: make_participant(1), 6: make_participant(6)}
    facts = [
        fact(0, FactKind.POSITION, 1, {"x": 6000, "y": 6200}),
        fact(60_000, FactKind.POSITION, 1, {"x": 6100, "y": 6300}),
        fact(120_000, FactKind.POSITION, 1, {"x": 6200, "y": 6400}),
        fact(0, FactKind.POSITION, 6, {"x": 9000, "y": 9000}),
        fact(60_000, FactKind.POSITION, 6, {"x": 9100, "y": 9100}),
        fact(0, FactKind.GOLD, 1, {"currentGold": 1800, "totalGold": 2000}),
        fact(60_000, FactKind.GOLD, 1, {"currentGold": 1800, "totalGold": 2600}),
        fact(120_000, FactKind.GOLD, 1, {"currentGold": 400, "totalGold": 3200}),
        fact(0, FactKind.HEALTH, 1, {"health": 300, "healthMax": 1000}),
        fact(60_000, FactKind.HEALTH, 1, {"health": 300, "healthMax": 1000}),
        fact(120_000, FactKind.HEALTH, 1, {"health": 900, "healthMax": 1000}),
        fact(0, FactKind.LEVEL, 1, {"level": 6}),
        fact(60_000, FactKind.LEVEL, 1, {"level": 6}),
        fact(duration_ms, FactKind.GAME_END, None, {"gameId": 1}),
        *(extra or []),
    ]
    return make_gst(facts, people, match_id="C2_SIMPLE", duration_ms=duration_ms)


def _interpret(gst, findings, pid: int = 1, *, patch=None, config=None):
    episodes = build_coaching_episodes(gst, findings, pid, config, patch=patch)
    return interpret_coaching_episodes(gst, episodes, pid, patch=patch), episodes


def test_zero_episodes_yield_zero_interpretations() -> None:
    assert interpret_coaching_episodes(_simple_gst(), [], 1) == []


def test_rb01_death_does_not_force_poor_decision() -> None:
    gst = _simple_gst()
    item = _finding(finding_id="d1", rule_id="R-001", t_ms=90_000)
    rows, _ = _interpret(gst, [item], patch=bundled_patch())
    assert len(rows) == 1
    interp = rows[0]
    assert interp.schema_version == EPISODE_INTERPRETATION_SCHEMA_VERSION
    assert interp.outcomes[0].kind is OutcomeKind.SUBJECT_DEATH
    assert interp.outcomes[0].polarity is OutcomePolarity.UNFAVORABLE
    assert interp.decision.state is QualityState.UNKNOWN
    assert interp.decision_outcome_relation is DecisionOutcomeRelation.UNCLASSIFIED


def test_rb02_favorable_strength_does_not_force_good_decision() -> None:
    gst = _simple_gst()
    item = _finding(
        finding_id="p1",
        rule_id="P-001",
        t_ms=90_000,
        concept_id="STRENGTH.CLEAN_LANE_PHASE",
    )
    rows, _ = _interpret(gst, [item])
    interp = rows[0]
    assert interp.outcomes[0].polarity is OutcomePolarity.FAVORABLE
    assert interp.decision.state is QualityState.UNKNOWN
    assert interp.decision_outcome_relation is DecisionOutcomeRelation.UNCLASSIFIED


def test_rb03_execution_not_observable_without_mechanics() -> None:
    gst = _simple_gst()
    item = _finding(finding_id="c1", rule_id="R-012", t_ms=90_000)
    interp = _interpret(gst, [item])[0][0]
    assert interp.execution.state is QualityState.NOT_OBSERVABLE
    codes = interp.execution.reason_codes
    assert any(code.code == "GST_ONLY_NO_MECHANICAL_EVIDENCE" for code in codes)


def test_rb04_omniscient_enemy_position_is_not_player_known() -> None:
    gst = _simple_gst()
    item = _finding(finding_id="d1", rule_id="R-001", t_ms=90_000)
    interp = _interpret(gst, [item])[0][0]
    pos_claims = [c for c in interp.information_claims if c.label == "enemy_or_ally_position_frame"]
    assert pos_claims
    assert all(c.system_available for c in pos_claims)
    assert all(c.player_knowledge is KnowledgeStatus.UNAVAILABLE for c in pos_claims)


def test_rb05_info_age_does_not_become_player_blindness() -> None:
    gst = _simple_gst()
    item = _finding(
        finding_id="d1",
        rule_id="R-001",
        t_ms=90_000,
        extra=(
            _evidence(
                "jungler info age",
                {"age_ms": 90_000, "interpretation": "inferred"},
                90_000,
            ),
        ),
    )
    interp = _interpret(gst, [item])[0][0]
    assert "info_age_is_not_player_blindness" in interp.unknowns
    fog = next(c for c in interp.information_claims if c.label == "true_fog")
    assert fog.player_knowledge is KnowledgeStatus.UNAVAILABLE
    details = [
        code.detail.lower()
        for claim in interp.information_claims
        for code in claim.reason_codes
    ]
    assert not any("could not see" in detail for detail in details)


def test_rb06_temporal_precedence_is_not_causal() -> None:
    gst = _simple_gst(duration_ms=400_000)
    early = _finding(finding_id="a", rule_id="R-006", t_ms=90_000)
    later = _finding(finding_id="b", rule_id="R-008", t_ms=100_000)
    interp = _interpret(gst, [early, later])[0][0]
    assert all(
        "CAUS" not in obs.payload.get("temporal_note", "").upper()
        and "ROOT" not in obs.label.upper()
        for obs in (*interp.antecedents, *interp.concurrent, *interp.consequences)
    )
    assert any(
        obs.payload.get("temporal_note") == "TEMPORALLY_PRECEDING_OR_FOLLOWING_ONLY"
        for obs in interp.concurrent
    )


def test_rb07_condition_resolution_does_not_rewrite_decision() -> None:
    gst = _simple_gst(extra=[buy(100_000, 1, 1038)])
    item = _finding(
        finding_id="r7",
        rule_id="R-007",
        t_ms=90_000,
        extra=(_evidence("unspent gold", {"value": 1500, "threshold": 1150}, 90_000),),
    )
    patch = bundled_patch()
    rows, episodes = _interpret(gst, [item], patch=patch)
    assert episodes[0].resolutions[0].status.value in {"RESOLVED", "UNKNOWN", "PERSISTED"}
    resolution = rows[0].condition_resolutions[0]
    if resolution.status.value == "RESOLVED":
        assert "resolved_condition_does_not_prove_decision_correct" in rows[0].unknowns
    assert rows[0].decision.state is QualityState.UNKNOWN


def test_rb08_dead_after_sample_is_not_actionable() -> None:
    duration = 180_000
    death_ms = 100_000
    people = roster()
    facts = [
        *quiet_frames(duration),
        *kill(death_ms, 1, 8, position=RIVER_ENEMY_FOR_BLUE),
    ]
    gst = make_gst(facts, match_id="C2_DEAD", duration_ms=duration, participants=people)
    item = _finding(finding_id="d1", rule_id="R-001", t_ms=death_ms)
    config = EpisodeBuilderConfig(pre_context_ms=30_000, post_context_ms=5_000)
    rows, _ = _interpret(gst, [item], patch=bundled_patch(), config=config)
    assert rows[0].actionability.state is ActionabilityState.NOT_ACTIONABLE
    assert any(
        code.code == "SUBJECT_DEAD_IN_WINDOW" for code in rows[0].actionability.reason_codes
    )


def test_rb09_decision_outcome_matrix_is_independently_representable() -> None:
    assert (
        derive_decision_outcome_relation(QualityState.GOOD, OutcomePolarity.FAVORABLE)
        is DecisionOutcomeRelation.GOOD_DECISION_GOOD_OUTCOME
    )
    assert (
        derive_decision_outcome_relation(QualityState.GOOD, OutcomePolarity.UNFAVORABLE)
        is DecisionOutcomeRelation.GOOD_DECISION_BAD_OUTCOME
    )
    assert (
        derive_decision_outcome_relation(QualityState.POOR, OutcomePolarity.FAVORABLE)
        is DecisionOutcomeRelation.POOR_DECISION_GOOD_OUTCOME
    )
    assert (
        derive_decision_outcome_relation(QualityState.POOR, OutcomePolarity.UNFAVORABLE)
        is DecisionOutcomeRelation.POOR_DECISION_BAD_OUTCOME
    )
    assert (
        derive_decision_outcome_relation(QualityState.UNKNOWN, OutcomePolarity.UNFAVORABLE)
        is DecisionOutcomeRelation.UNCLASSIFIED
    )
    assert (
        derive_decision_outcome_relation(QualityState.UNKNOWN, OutcomePolarity.FAVORABLE)
        is DecisionOutcomeRelation.UNCLASSIFIED
    )


def test_rb10_no_coaching_recommendation_or_counterfactual() -> None:
    gst = _simple_gst()
    item = _finding(finding_id="d1", rule_id="R-001", t_ms=90_000)
    payload = _interpret(gst, [item])[0][0].to_dict()
    assert payload["alternative_analysis"] == ALTERNATIVE_ANALYSIS_NOT_IMPLEMENTED
    blob = " ".join(
        [
            str(payload.get("decision")),
            str(payload.get("execution")),
            str(payload.get("outcomes")),
            str(payload.get("findings")),
        ]
    ).lower()
    banned = ("you should", "should have", "root cause:", "practice drill")
    assert not any(token in blob for token in banned)


def test_all_production_rules_have_safe_catalog_profiles() -> None:
    ids = set(production_rule_ids())
    expected = {f"R-{i:03d}" for i in range(1, 21)} | {f"P-00{i}" for i in range(1, 6)}
    assert ids == expected
    assert evidence_contracts() == {}
    for rule_id in sorted(ids):
        profile = profile_for(rule_id)
        assert profile.decision_assessable is False
        assert profile.execution_observable is False


def test_suppressed_findings_remain_non_anchor_in_interpretation() -> None:
    gst = _simple_gst()
    seed = _finding(finding_id="seed", rule_id="R-001", t_ms=90_000)
    quiet = _finding(finding_id="quiet", rule_id="R-003", t_ms=95_000, suppressed=True)
    interp = _interpret(gst, [quiet, seed])[0][0]
    by_id = {item.finding_id: item for item in interp.findings}
    assert by_id["seed"].association == "ANCHOR"
    assert by_id["quiet"].association == "TEMPORALLY_ASSOCIATED"
    assert by_id["quiet"].suppressed is True
    assert "quiet" not in interp.anchor_finding_ids


def test_fixture_gst_interpretation_is_deterministic() -> None:
    gst = load_gst("NA1_fixture_a")
    t_ms = min(300_000, gst.duration_ms // 2)
    item = _finding(finding_id="fx", rule_id="R-001", t_ms=t_ms)
    patch = bundled_patch(gst.patch)
    first = _interpret(gst, [item], patch=patch)[0][0]
    second = _interpret(gst, [item], patch=patch)[0][0]
    assert first.to_dict() == second.to_dict()
    assert first.decision.state is QualityState.UNKNOWN


def test_outcome_object_never_sets_decision_state() -> None:
    outcome = ObservedOutcome(
        kind=OutcomeKind.SUBJECT_DEATH,
        polarity=OutcomePolarity.UNFAVORABLE,
        finding_id="x",
        rule_id="R-001",
        t_ms=1,
        confidence=1.0,
        reason_codes=(ReasonCode("TEST", ""),),
    )
    assert derive_decision_outcome_relation(QualityState.UNKNOWN, outcome.polarity) is (
        DecisionOutcomeRelation.UNCLASSIFIED
    )


def test_c2_sources_forbid_visual_llm_replay_imports() -> None:
    forbidden = (
        "riftlens.visual",
        "riftlens.replay_host",
        "riftlens.coaching.providers",
        "riftlens.coaching.composer",
        "openai",
        "anthropic",
    )
    for path in _INTERP_ROOT.rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if stripped.startswith("from ") or stripped.startswith("import "):
                for token in forbidden:
                    assert token not in stripped, f"{path} imports {token}"
