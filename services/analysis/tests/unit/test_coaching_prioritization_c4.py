"""C.4 learning-value prioritization tests."""

from __future__ import annotations

from pathlib import Path

from riftlens.coaching.concepts.models import (
    CONCEPTS_SCHEMA_VERSION,
    ConceptSpecificity,
    EvidenceRef,
    LessonCandidate,
    LessonPolarity,
    LessonReadiness,
    SupportLevel,
)
from riftlens.coaching.concepts.models import (
    ReasonCode as C3Reason,
)
from riftlens.coaching.prioritization import (
    DEFAULT_LEARNING_VALUE_CONFIG,
    PRIORITIZATION_SCHEMA_VERSION,
    ActionabilityHint,
    LessonTier,
    OverlapRelation,
    ScoringContext,
    explain_lesson_priority,
    overlap_relation,
    prioritize_lesson_candidates,
    score_lesson_candidates,
    with_config_overrides,
)
from riftlens.domain.fact import Provenance

_ROOT = Path(__file__).resolve().parents[2] / "riftlens" / "coaching" / "prioritization"


def _lesson(
    *,
    lesson_id: str,
    concept_id: str,
    polarity: LessonPolarity = LessonPolarity.CONSISTENT_NEGATIVE,
    support: SupportLevel = SupportLevel.STRONG,
    readiness: LessonReadiness = LessonReadiness.CANDIDATE,
    specificity: ConceptSpecificity = ConceptSpecificity.GENERAL,
    occurrences: int = 1,
    episode_ids: tuple[str, ...] | None = None,
    finding_ids: tuple[str, ...] | None = None,
    gaps: tuple[str, ...] = (),
    conflicts: tuple[EvidenceRef, ...] = (),
    resolution_notes: tuple[str, ...] = (),
    confidence: float = 0.8,
) -> LessonCandidate:
    eps = episode_ids if episode_ids is not None else (f"ep-{lesson_id}",)
    finds = finding_ids if finding_ids is not None else (f"f-{lesson_id}",)
    return LessonCandidate(
        id=lesson_id,
        schema_version=CONCEPTS_SCHEMA_VERSION,
        concept_id=concept_id,
        match_id="C4_MATCH",
        participant_id=1,
        episode_ids=eps,
        finding_ids=finds,
        interpretation_ids=(f"i-{lesson_id}",),
        positive_signal_ids=("p1",) if polarity is LessonPolarity.CONSISTENT_POSITIVE else (),
        negative_signal_ids=("n1",)
        if polarity is LessonPolarity.CONSISTENT_NEGATIVE
        else (("n1",) if polarity is LessonPolarity.MIXED else ()),
        neutral_signal_ids=(),
        causal_hypothesis_ids=(),
        polarity=polarity,
        support_level=support,
        readiness=readiness,
        specificity=specificity,
        within_match_occurrences=occurrences,
        confidence=confidence,
        context_gaps=gaps,
        conflicting_evidence=conflicts,
        condition_resolution_notes=resolution_notes,
        reason_codes=(C3Reason("TEST"),),
        provenance=Provenance(producer="test", producer_version=1, upstream=()),
    )


def test_zero_input_empty() -> None:
    result = prioritize_lesson_candidates([])
    assert result.schema_version == PRIORITIZATION_SCHEMA_VERSION
    assert result.major == ()
    assert result.strengths == ()
    assert result.ranked == ()


def test_pr01_one_strong_one_major() -> None:
    strong = _lesson(
        lesson_id="s1",
        concept_id="economy.resource_spending",
        support=SupportLevel.STRONG,
        occurrences=3,
        episode_ids=("e1", "e2", "e3"),
        finding_ids=("f1", "f2", "f3"),
    )
    weak = _lesson(
        lesson_id="w1",
        concept_id="risk.isolation",
        support=SupportLevel.INSUFFICIENT,
        occurrences=1,
    )
    result = prioritize_lesson_candidates([strong, weak])
    assert len(result.major) == 1
    assert result.major[0].lesson_candidate_id == "s1"


def test_pr02_two_strong_distinct_two_major() -> None:
    a = _lesson(
        lesson_id="a",
        concept_id="economy.resource_spending",
        support=SupportLevel.STRONG,
        occurrences=2,
        episode_ids=("e1", "e2"),
        finding_ids=("f1", "f2"),
    )
    b = _lesson(
        lesson_id="b",
        concept_id="tempo.post_fight_conversion",
        support=SupportLevel.STRONG,
        occurrences=2,
        episode_ids=("e3", "e4"),
        finding_ids=("f3", "f4"),
    )
    result = prioritize_lesson_candidates([a, b])
    assert len(result.major) == 2


def test_pr03_zero_major_when_none_clear() -> None:
    rows = [
        _lesson(
            lesson_id=f"w{i}",
            concept_id="risk.isolation",
            support=SupportLevel.INSUFFICIENT,
        )
        for i in range(3)
    ]
    result = prioritize_lesson_candidates(rows)
    assert len(result.major) == 0
    assert any(n.code == "ZERO_MAJOR_VALID" for n in result.selection_notes)


def test_pr04_four_major_possible() -> None:
    concepts = [
        "economy.resource_spending",
        "tempo.post_fight_conversion",
        "laning.cs_maintenance",
        "objective.presence",
    ]
    rows = [
        _lesson(
            lesson_id=f"m{i}",
            concept_id=concept,
            support=SupportLevel.STRONG,
            occurrences=2,
            episode_ids=(f"e{i}a", f"e{i}b"),
            finding_ids=(f"f{i}a", f"f{i}b"),
        )
        for i, concept in enumerate(concepts)
    ]
    result = prioritize_lesson_candidates(rows)
    assert len(result.major) == 4
    assert DEFAULT_LEARNING_VALUE_CONFIG.max_major_safety_cap != 3


def test_lv01_support_recurrence_can_outrank_raw_impact() -> None:
    repeated = _lesson(
        lesson_id="rep",
        concept_id="economy.reset_timing",
        support=SupportLevel.STRONG,
        occurrences=3,
        episode_ids=("e1", "e2", "e3"),
        finding_ids=("f1", "f2", "f3"),
    )
    splashy = _lesson(
        lesson_id="splash",
        concept_id="risk.threat_awareness",
        support=SupportLevel.WEAK,
        occurrences=1,
        gaps=("true_player_fog_or_vision", "PLAYER_COULD_NOT_SEE_JUNGLER"),
    )
    ctx = ScoringContext(
        impact_by_lesson_id={"rep": 120.0, "splash": 900.0},
        teachability_by_concept={
            "economy.reset_timing": 0.9,
            "risk.threat_awareness": 0.5,
        },
    )
    result = prioritize_lesson_candidates([repeated, splashy], context=ctx)
    explained = {
        item.lesson_candidate_id: item.learning_value for item in result.ranked
    }
    assert explained["rep"] > explained["splash"]


def test_lv02_resolved_vs_persistent() -> None:
    resolved = _lesson(
        lesson_id="res",
        concept_id="economy.reset_timing",
        support=SupportLevel.MODERATE,
        resolution_notes=("r7:RESOLVED:purchase",),
        episode_ids=("e1",),
        finding_ids=("f1",),
    )
    persistent = _lesson(
        lesson_id="per",
        concept_id="economy.resource_spending",
        support=SupportLevel.MODERATE,
        episode_ids=("e2",),
        finding_ids=("f2",),
    )
    result = prioritize_lesson_candidates([resolved, persistent])
    values = {
        item.lesson_candidate_id: item.learning_value for item in result.ranked
    }
    assert values["per"] > values["res"]


def test_lv03_mixed_signals_lower_priority() -> None:
    mixed = _lesson(
        lesson_id="mix",
        concept_id="economy.reset_timing",
        polarity=LessonPolarity.MIXED,
        support=SupportLevel.MODERATE,
        conflicts=(EvidenceRef("signal", "p1"), EvidenceRef("signal", "n1")),
        episode_ids=("e1",),
        finding_ids=("f1",),
    )
    clean = _lesson(
        lesson_id="clean",
        concept_id="economy.resource_spending",
        support=SupportLevel.MODERATE,
        episode_ids=("e2",),
        finding_ids=("f2",),
    )
    result = prioritize_lesson_candidates([mixed, clean])
    values = {
        item.lesson_candidate_id: item.learning_value for item in result.ranked
    }
    assert values["clean"] > values["mix"]


def test_lv04_general_supported_beats_specific_unsupported() -> None:
    general = _lesson(
        lesson_id="gen",
        concept_id="laning.cs_maintenance",
        support=SupportLevel.STRONG,
        specificity=ConceptSpecificity.GENERAL,
    )
    specific = _lesson(
        lesson_id="spec",
        concept_id="wave.management",
        support=SupportLevel.WEAK,
        specificity=ConceptSpecificity.SPECIFIC,
        readiness=LessonReadiness.BLOCKED,
    )
    result = prioritize_lesson_candidates([general, specific])
    assert result.major
    assert result.major[0].lesson_candidate_id == "gen"
    withheld_ids = {item.lesson_candidate_id for item in result.withheld}
    assert "spec" in withheld_ids or all(
        item.lesson_candidate_id != "spec" for item in result.major
    )


def test_lv05_blocked_capability_not_major() -> None:
    blocked = _lesson(
        lesson_id="wave",
        concept_id="wave.management",
        support=SupportLevel.STRONG,
        readiness=LessonReadiness.BLOCKED,
        specificity=ConceptSpecificity.SPECIFIC,
    )
    result = prioritize_lesson_candidates([blocked])
    assert result.major == ()
    assert result.withheld
    assert result.withheld[0].exclusion_reason == "CAPABILITY_BLOCKED"


def test_lv06_no_poor_decision_bonus() -> None:
    lesson = _lesson(lesson_id="d1", concept_id="risk.threat_awareness")
    result = prioritize_lesson_candidates([lesson])
    blob = str(result.to_dict())
    assert "POOR_DECISION" not in blob
    assert "BAD_DECISION" not in blob


def test_rd01_high_overlap_detected() -> None:
    a = _lesson(
        lesson_id="a",
        concept_id="economy.resource_spending",
        finding_ids=("f1", "f2", "f3"),
        episode_ids=("e1", "e2"),
    )
    b = _lesson(
        lesson_id="b",
        concept_id="economy.reset_timing",
        finding_ids=("f1", "f2", "f3"),
        episode_ids=("e1", "e2"),
    )
    assert overlap_relation(a, b, DEFAULT_LEARNING_VALUE_CONFIG) in {
        OverlapRelation.HIGH_OVERLAP,
        OverlapRelation.DUPLICATIVE,
    }


def test_rd02_same_domain_independent_not_duplicate() -> None:
    a = _lesson(
        lesson_id="a",
        concept_id="economy.resource_spending",
        finding_ids=("f1",),
        episode_ids=("e1",),
    )
    b = _lesson(
        lesson_id="b",
        concept_id="economy.reset_timing",
        finding_ids=("f9",),
        episode_ids=("e9",),
    )
    rel = overlap_relation(a, b, DEFAULT_LEARNING_VALUE_CONFIG)
    assert rel in {OverlapRelation.DISTINCT, OverlapRelation.RELATED}
    assert rel is not OverlapRelation.DUPLICATIVE


def test_rd03_higher_value_overlap_withholds_lower() -> None:
    high = _lesson(
        lesson_id="high",
        concept_id="economy.resource_spending",
        support=SupportLevel.STRONG,
        occurrences=3,
        episode_ids=("e1", "e2", "e3"),
        finding_ids=("f1", "f2", "f3"),
    )
    low = _lesson(
        lesson_id="low",
        concept_id="economy.reset_timing",
        support=SupportLevel.MODERATE,
        occurrences=1,
        episode_ids=("e1", "e2"),
        finding_ids=("f1", "f2"),
    )
    result = prioritize_lesson_candidates([high, low])
    assert any(item.lesson_candidate_id == "high" for item in result.major)
    low_row = explain_lesson_priority(result, "low")
    assert low_row is not None
    assert low_row.tier in {LessonTier.WITHHELD, LessonTier.SECONDARY}
    if low_row.tier is LessonTier.WITHHELD:
        assert low_row.exclusion_reason in {
            "REDUNDANT_WITH_HIGHER_VALUE",
            "DUPLICATE_EVIDENCE",
            "LOW_LEARNING_VALUE",
        }


def test_rd04_diversity_does_not_force_weak() -> None:
    a = _lesson(
        lesson_id="a",
        concept_id="economy.resource_spending",
        support=SupportLevel.STRONG,
        occurrences=2,
        episode_ids=("e1", "e2"),
        finding_ids=("f1", "f2"),
    )
    b = _lesson(
        lesson_id="b",
        concept_id="economy.reset_timing",
        support=SupportLevel.STRONG,
        occurrences=2,
        episode_ids=("e3", "e4"),
        finding_ids=("f3", "f4"),
    )
    weak_vision = _lesson(
        lesson_id="v",
        concept_id="vision.control_ward_habit",
        support=SupportLevel.INSUFFICIENT,
    )
    result = prioritize_lesson_candidates([a, b, weak_vision])
    major_ids = {item.lesson_candidate_id for item in result.major}
    assert "v" not in major_ids


def test_st01_zero_strengths() -> None:
    result = prioritize_lesson_candidates(
        [_lesson(lesson_id="n", concept_id="risk.isolation", support=SupportLevel.WEAK)]
    )
    assert result.strengths == ()


def test_st02_one_strength() -> None:
    s = _lesson(
        lesson_id="s",
        concept_id="strength.clean_lane",
        polarity=LessonPolarity.CONSISTENT_POSITIVE,
        support=SupportLevel.MODERATE,
    )
    result = prioritize_lesson_candidates([s])
    assert len(result.strengths) == 1


def test_st03_several_strengths_no_forced_count() -> None:
    rows = [
        _lesson(
            lesson_id=f"s{i}",
            concept_id=concept,
            polarity=LessonPolarity.CONSISTENT_POSITIVE,
            support=SupportLevel.MODERATE,
            episode_ids=(f"e{i}",),
            finding_ids=(f"f{i}",),
        )
        for i, concept in enumerate(
            [
                "strength.clean_lane",
                "strength.efficient_resets",
                "strength.objective_discipline",
                "strength.vision_habit",
            ]
        )
    ]
    result = prioritize_lesson_candidates(rows)
    assert len(result.strengths) == 4


def test_rf_priority_01_many_findings_one_lesson() -> None:
    lesson = _lesson(
        lesson_id="one",
        concept_id="risk.threat_awareness",
        support=SupportLevel.STRONG,
        occurrences=5,
        episode_ids=tuple(f"e{i}" for i in range(5)),
        finding_ids=tuple(f"f{i}" for i in range(5)),
    )
    noise = [
        _lesson(
            lesson_id=f"n{i}",
            concept_id="risk.isolation",
            support=SupportLevel.INSUFFICIENT,
            finding_ids=(f"nx{i}",),
            episode_ids=(f"en{i}",),
        )
        for i in range(4)
    ]
    result = prioritize_lesson_candidates([lesson, *noise])
    assert len(result.major) == 1
    assert result.major[0].lesson_candidate_id == "one"


def test_rf_priority_02_weak_only_zero_major() -> None:
    rows = [
        _lesson(
            lesson_id=f"w{i}",
            concept_id="vision.preparation",
            support=SupportLevel.WEAK,
            finding_ids=(f"f{i}",),
            episode_ids=(f"e{i}",),
        )
        for i in range(5)
    ]
    # Raise major threshold so weak noise cannot fill a quota
    cfg = with_config_overrides(major_threshold=80.0)
    result = prioritize_lesson_candidates(rows, config=cfg)
    assert len(result.major) == 0


def test_rf_priority_03_recurrence_contributes() -> None:
    once = _lesson(
        lesson_id="once",
        concept_id="tempo.post_fight_conversion",
        support=SupportLevel.MODERATE,
        occurrences=1,
        episode_ids=("e1",),
        finding_ids=("f1",),
    )
    many = _lesson(
        lesson_id="many",
        concept_id="economy.resource_spending",
        support=SupportLevel.MODERATE,
        occurrences=3,
        episode_ids=("e2", "e3", "e4"),
        finding_ids=("f2", "f3", "f4"),
    )
    result = prioritize_lesson_candidates([once, many])
    values = {
        item.lesson_candidate_id: item.learning_value for item in result.ranked
    }
    assert values["many"] > values["once"]
    many_row = explain_lesson_priority(result, "many")
    assert many_row is not None
    assert any(code.code == "REPEATED_WITHIN_MATCH" for code in many_row.reason_codes)


def test_rf_priority_04_role_relevance() -> None:
    a = _lesson(lesson_id="a", concept_id="laning.cs_maintenance", support=SupportLevel.MODERATE)
    b = _lesson(
        lesson_id="b",
        concept_id="objective.presence",
        support=SupportLevel.MODERATE,
        episode_ids=("e2",),
        finding_ids=("f2",),
    )
    ctx = ScoringContext(
        role_relevance_by_concept={
            "laning.cs_maintenance": 1.0,
            "objective.presence": 0.0,
        }
    )
    result = prioritize_lesson_candidates([a, b], context=ctx)
    values = {
        item.lesson_candidate_id: item.learning_value for item in result.ranked
    }
    assert values["a"] > values["b"]


def test_rf_priority_05_no_cross_game_claims() -> None:
    lesson = _lesson(lesson_id="x", concept_id="economy.resource_spending")
    ctx = ScoringContext(cross_game_recurrence={"economy.resource_spending": 9})
    result = prioritize_lesson_candidates([lesson], context=ctx)
    blob = str(result.to_dict()).lower()
    assert "recurring across games" not in blob
    assert "improving" not in blob
    assert "regressing" not in blob
    row = result.ranked[0]
    assert any(code.code == "C6_SEAMS_IGNORED" for code in row.reason_codes)


def test_golden_explainability_snapshot() -> None:
    rows = [
        _lesson(
            lesson_id="strong_reset",
            concept_id="economy.reset_timing",
            support=SupportLevel.STRONG,
            occurrences=3,
            episode_ids=("e1", "e2", "e3"),
            finding_ids=("f1", "f2", "f3"),
        ),
        _lesson(
            lesson_id="weak_death",
            concept_id="risk.threat_awareness",
            support=SupportLevel.WEAK,
            gaps=("true_player_fog_or_vision",),
        ),
        _lesson(
            lesson_id="strength",
            concept_id="strength.clean_lane",
            polarity=LessonPolarity.CONSISTENT_POSITIVE,
            support=SupportLevel.MODERATE,
        ),
    ]
    result = prioritize_lesson_candidates(
        rows,
        context=ScoringContext(
            impact_by_lesson_id={
                "strong_reset": 150.0,
                "weak_death": 800.0,
                "strength": 50.0,
            }
        ),
    )
    assert result.major
    assert result.major[0].lesson_candidate_id == "strong_reset"
    assert result.strengths
    top = result.major[0]
    factors = top.factors.to_dict()
    assert factors["evidence_support"] > factors["impact"]
    assert top.reason_codes
    assert "you should" not in str(result.to_dict()).lower()


def test_config_sensitivity_threshold() -> None:
    lesson = _lesson(
        lesson_id="m",
        concept_id="economy.resource_spending",
        support=SupportLevel.MODERATE,
        occurrences=2,
        episode_ids=("e1", "e2"),
        finding_ids=("f1", "f2"),
    )
    low = prioritize_lesson_candidates(
        [lesson], config=with_config_overrides(major_threshold=10.0)
    )
    high = prioritize_lesson_candidates(
        [lesson], config=with_config_overrides(major_threshold=200.0)
    )
    assert len(low.major) == 1
    assert len(high.major) == 0


def test_not_actionable_blocks_major() -> None:
    lesson = _lesson(
        lesson_id="dead",
        concept_id="tempo.post_fight_conversion",
        support=SupportLevel.STRONG,
    )
    ctx = ScoringContext(
        actionability_by_lesson_id={"dead": ActionabilityHint.NOT_ACTIONABLE}
    )
    result = prioritize_lesson_candidates([lesson], context=ctx)
    assert result.major == ()
    assert result.withheld[0].exclusion_reason == "NOT_ACTIONABLE"


def test_focus_count_not_hardcoded() -> None:
    assert not hasattr(DEFAULT_LEARNING_VALUE_CONFIG, "focus_count")
    assert DEFAULT_LEARNING_VALUE_CONFIG.max_major_safety_cap != 3


def test_determinism() -> None:
    rows = [
        _lesson(lesson_id="a", concept_id="economy.resource_spending", support=SupportLevel.STRONG),
        _lesson(
            lesson_id="b",
            concept_id="tempo.post_fight_conversion",
            support=SupportLevel.STRONG,
            episode_ids=("e2",),
            finding_ids=("f2",),
        ),
    ]
    assert prioritize_lesson_candidates(rows).to_dict() == prioritize_lesson_candidates(
        rows
    ).to_dict()


def test_score_api() -> None:
    lesson = _lesson(lesson_id="a", concept_id="economy.resource_spending")
    scored = score_lesson_candidates([lesson])
    assert len(scored) == 1
    assert scored[0][1].total() > 0


def test_import_isolation_scan() -> None:
    banned = (
        "riftlens.visual",
        "riftlens.replay_host",
        "riftlens.coaching.providers",
        "openai",
        "anthropic",
    )
    for path in _ROOT.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{path.name} imports {token}"
