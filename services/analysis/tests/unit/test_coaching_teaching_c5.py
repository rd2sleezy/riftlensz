"""C.5 teaching and practice design tests."""

from __future__ import annotations

from pathlib import Path

from riftlens.coaching.concepts.models import (
    CONCEPTS_SCHEMA_VERSION,
    ConceptSpecificity,
    LessonCandidate,
    LessonPolarity,
    LessonReadiness,
    SupportLevel,
)
from riftlens.coaching.concepts.models import (
    ReasonCode as C3Reason,
)
from riftlens.coaching.prioritization import (
    LessonTier,
    PrioritizedLesson,
    PrioritizedLessonSet,
    PriorityFactors,
    prioritize_lesson_candidates,
)
from riftlens.coaching.prioritization.models import prioritized_lesson_id
from riftlens.coaching.teaching import (
    TEACHING_SCHEMA_VERSION,
    AlternativeCertainty,
    ContentOrigin,
    Measurability,
    TeachingDepth,
    TeachingSpecificity,
    build_teaching_lessons,
    evaluate_teaching_readiness,
    get_concept_playbook,
    implemented_playbook_ids,
    render_teaching_lesson,
    render_teaching_lesson_set,
)
from riftlens.coaching.teaching.playbooks import BLOCKED_WAVE_ACTIONS
from riftlens.domain.fact import Provenance

_ROOT = Path(__file__).resolve().parents[2] / "riftlens" / "coaching" / "teaching"


def _candidate(
    *,
    lesson_id: str,
    concept_id: str,
    polarity: LessonPolarity = LessonPolarity.CONSISTENT_NEGATIVE,
    support: SupportLevel = SupportLevel.STRONG,
    occurrences: int = 3,
    resolution_notes: tuple[str, ...] = (),
) -> LessonCandidate:
    return LessonCandidate(
        id=lesson_id,
        schema_version=CONCEPTS_SCHEMA_VERSION,
        concept_id=concept_id,
        match_id="C5_MATCH",
        participant_id=1,
        episode_ids=tuple(f"e{i}" for i in range(occurrences)),
        finding_ids=tuple(f"f{i}" for i in range(occurrences)),
        interpretation_ids=(f"i-{lesson_id}",),
        positive_signal_ids=("p",) if polarity is LessonPolarity.CONSISTENT_POSITIVE else (),
        negative_signal_ids=("n",)
        if polarity is not LessonPolarity.CONSISTENT_POSITIVE
        else (),
        neutral_signal_ids=(),
        causal_hypothesis_ids=(),
        polarity=polarity,
        support_level=support,
        readiness=LessonReadiness.CANDIDATE,
        specificity=ConceptSpecificity.GENERAL,
        within_match_occurrences=occurrences,
        confidence=0.8,
        context_gaps=(),
        conflicting_evidence=(),
        condition_resolution_notes=resolution_notes,
        reason_codes=(C3Reason("TEST"),),
        provenance=Provenance(producer="test", producer_version=1, upstream=()),
    )


def _prioritized(
    candidate: LessonCandidate,
    *,
    tier: LessonTier,
    rank: int | None = 1,
    learning_value: float = 55.0,
) -> PrioritizedLesson:
    return PrioritizedLesson(
        id=prioritized_lesson_id(candidate.id, 1),
        lesson_candidate_id=candidate.id,
        concept_id=candidate.concept_id,
        rank=rank,
        tier=tier,
        learning_value=learning_value,
        factors=PriorityFactors(evidence_support=35.0),
        polarity=candidate.polarity.value,
        support_level=candidate.support_level.value,
        occurrences=candidate.within_match_occurrences,
        specificity=candidate.specificity.value,
        capability_status="PARTIAL",
        conflicts=0,
        gaps=(),
        reason_codes=(),
        provenance=Provenance(producer="test", producer_version=1, upstream=()),
    )


def _set(
    *items: PrioritizedLesson,
    withheld: tuple[PrioritizedLesson, ...] = (),
) -> PrioritizedLessonSet:
    major = tuple(item for item in items if item.tier is LessonTier.MAJOR)
    secondary = tuple(item for item in items if item.tier is LessonTier.SECONDARY)
    strengths = tuple(item for item in items if item.tier is LessonTier.STRENGTH)
    return PrioritizedLessonSet(
        schema_version="c4.0",
        match_id="C5_MATCH",
        participant_id=1,
        method="test",
        method_version=1,
        config_version="test",
        ranked=tuple(items) + withheld,
        major=major,
        secondary=secondary,
        strengths=strengths,
        withheld=withheld,
    )


def test_ts05_empty_input() -> None:
    empty = PrioritizedLessonSet(
        schema_version="c4.0",
        match_id="",
        participant_id=0,
        method="test",
        method_version=1,
        config_version="test",
        ranked=(),
        major=(),
        secondary=(),
        strengths=(),
        withheld=(),
    )
    result = build_teaching_lessons(empty)
    assert result.schema_version == TEACHING_SCHEMA_VERSION
    assert result.lessons == ()


def test_ts04_withheld_no_teaching() -> None:
    cand = _candidate(lesson_id="w", concept_id="economy.resource_spending")
    withheld = _prioritized(cand, tier=LessonTier.WITHHELD, rank=None)
    result = build_teaching_lessons(_set(withheld= (withheld,)), candidates=[cand])
    assert result.lessons == ()
    assert "w" in result.skipped_withheld


def test_ts01_major_full_package() -> None:
    cand = _candidate(lesson_id="m", concept_id="economy.resource_spending")
    major = _prioritized(cand, tier=LessonTier.MAJOR)
    result = build_teaching_lessons(_set(major), candidates=[cand])
    assert len(result.lessons) == 1
    lesson = result.lessons[0]
    assert lesson.teaching_depth is TeachingDepth.FULL
    assert lesson.concept_explanation is not None
    assert lesson.why_it_matters is not None
    assert lesson.recognition_cue is not None
    assert lesson.memorable_rule is not None
    assert lesson.drill is not None
    assert lesson.objective is not None
    assert lesson.objective.measurability is Measurability.MEASURABLE_NOW
    assert lesson.concept_explanation.origin is ContentOrigin.GENERAL_GAME_PRINCIPLE
    assert all(
        item.origin is ContentOrigin.MATCH_EVIDENCE for item in lesson.evidence_summary
    )


def test_ts02_secondary_light() -> None:
    cand = _candidate(lesson_id="s", concept_id="objective.presence")
    row = _prioritized(cand, tier=LessonTier.SECONDARY)
    lesson = build_teaching_lessons(_set(row), candidates=[cand]).lessons[0]
    assert lesson.teaching_depth is TeachingDepth.LIGHT
    assert lesson.drill is None
    assert lesson.objective is None
    assert lesson.recognition_cue is not None


def test_ts03_strength_reinforcement() -> None:
    cand = _candidate(
        lesson_id="st",
        concept_id="strength.clean_lane",
        polarity=LessonPolarity.CONSISTENT_POSITIVE,
    )
    row = _prioritized(cand, tier=LessonTier.STRENGTH)
    lesson = build_teaching_lessons(_set(row), candidates=[cand]).lessons[0]
    assert lesson.teaching_depth is TeachingDepth.REINFORCEMENT
    assert lesson.alternative is not None
    assert lesson.alternative.alternative_type == "REINFORCEMENT"
    blob = str(lesson.to_dict()).lower()
    assert "mastered" not in blob


def test_te01_no_decision_wrong_claim() -> None:
    cand = _candidate(lesson_id="m", concept_id="risk.threat_awareness")
    lesson = build_teaching_lessons(
        _set(_prioritized(cand, tier=LessonTier.MAJOR)), candidates=[cand]
    ).lessons[0]
    rendered = render_teaching_lesson(lesson).lower()
    assert "decision was wrong" not in rendered
    assert "you should not have" not in rendered
    assert any(code.code == "C2_DECISION_UNKNOWN_RESPECTED" for code in lesson.reason_codes)


def test_te02_no_caused_claim() -> None:
    cand = _candidate(lesson_id="m", concept_id="economy.resource_spending")
    lesson = build_teaching_lessons(
        _set(_prioritized(cand, tier=LessonTier.MAJOR)), candidates=[cand]
    ).lessons[0]
    rendered = render_teaching_lesson(lesson).lower()
    assert " caused " not in f" {rendered} "
    assert "root cause" not in rendered
    assert "DECISION_WAS_WRONG" in lesson.forbidden_claims
    assert "CAUSED_THE_OUTCOME" in lesson.forbidden_claims
    assert any(code.code == "C3_NO_SUPPORTED_CAUSALITY" for code in lesson.reason_codes)


def test_te03_no_wave_action_recommendations() -> None:
    cand = _candidate(lesson_id="wave", concept_id="wave.management")
    lesson = build_teaching_lessons(
        _set(_prioritized(cand, tier=LessonTier.MAJOR)), candidates=[cand]
    ).lessons[0]
    assert lesson.teaching_specificity is TeachingSpecificity.UNAVAILABLE
    blob = str(lesson.to_dict()).lower()
    for token in BLOCKED_WAVE_ACTIONS:
        assert token.replace("_", " ") not in blob or lesson.recognition_cue is None
    assert lesson.memorable_rule is None
    assert lesson.drill is None


def test_te04_cue_not_omniscient_position() -> None:
    cue = get_concept_playbook("risk.threat_awareness")
    assert cue is not None
    text = (cue.recognition_cue.trigger + cue.recognition_cue.intended_check).lower()
    assert "coordinates" not in text
    assert "x/y" not in text
    assert cue.recognition_cue.player_observable is True
    assert "exact_enemy_jungler_coordinates_as_known" in cue.recognition_cue.unavailable_conditions


def test_te05_no_mechanics_correction() -> None:
    cand = _candidate(lesson_id="mech", concept_id="mechanics.execution")
    lesson = build_teaching_lessons(
        _set(_prioritized(cand, tier=LessonTier.MAJOR)), candidates=[cand]
    ).lessons[0]
    assert lesson.drill is None
    assert "MECHANICAL_CORRECTION" in lesson.forbidden_claims


def test_te06_no_flash_correction() -> None:
    cand = _candidate(lesson_id="sum", concept_id="combat.summoner_usage")
    lesson = build_teaching_lessons(
        _set(_prioritized(cand, tier=LessonTier.MAJOR)), candidates=[cand]
    ).lessons[0]
    assert lesson.alternative is not None
    assert lesson.alternative.certainty is AlternativeCertainty.UNAVAILABLE
    assert "FLASH_CORRECTION" in lesson.forbidden_claims


def test_rc01_rc04_cue_structure() -> None:
    pb = get_concept_playbook("economy.resource_spending")
    assert pb is not None
    assert pb.recognition_cue.trigger
    assert pb.recognition_cue.intended_check
    assert pb.recognition_cue.player_observable is True


def test_rule_01_to_03() -> None:
    pb = get_concept_playbook("economy.reset_timing")
    assert pb is not None
    rule = pb.memorable_rule
    compact = rule.to_dict()["compact"]
    assert "WHEN" in compact and "THEN" in compact
    assert len(compact) < 160
    assert rule.absolute is False


def test_rule_04_blocked_no_rule() -> None:
    cand = _candidate(lesson_id="w", concept_id="wave.management")
    lesson = build_teaching_lessons(
        _set(_prioritized(cand, tier=LessonTier.MAJOR)), candidates=[cand]
    ).lessons[0]
    assert lesson.memorable_rule is None


def test_dr01_dr02_safe_drill() -> None:
    pb = get_concept_playbook("tempo.post_fight_conversion")
    assert pb is not None
    assert pb.drill.safe is True
    text = pb.drill.instruction.lower()
    assert "intentionally" not in text
    assert "play more games" not in text


def test_ob01_ob02_process_not_outcome() -> None:
    pb = get_concept_playbook("economy.resource_spending")
    assert pb is not None
    assert pb.objective_template.outcome_goal is False
    text = pb.objective_template.target_behavior.lower()
    assert "win next game" not in text
    assert "get more kills" not in text


def test_ob03_resource_measurable_now() -> None:
    pb = get_concept_playbook("economy.resource_spending")
    assert pb is not None
    assert pb.objective_template.measurability is Measurability.MEASURABLE_NOW


def test_ob04_wave_not_measurable() -> None:
    rows = evaluate_teaching_readiness(("wave.management",))
    assert rows[0].objective_measurability is Measurability.NOT_MEASURABLE


def test_ob05_future_evidence_exposed() -> None:
    cand = _candidate(lesson_id="m", concept_id="economy.resource_spending")
    lesson = build_teaching_lessons(
        _set(_prioritized(cand, tier=LessonTier.MAJOR)), candidates=[cand]
    ).lessons[0]
    assert lesson.objective is not None
    assert lesson.objective.required_future_evidence
    assert lesson.objective.prior_lesson_id == lesson.prioritized_lesson_id


def test_coach_01_clear_rule_and_drill() -> None:
    cand = _candidate(lesson_id="m", concept_id="economy.resource_spending")
    lesson = build_teaching_lessons(
        _set(_prioritized(cand, tier=LessonTier.MAJOR)), candidates=[cand]
    ).lessons[0]
    rendered = render_teaching_lesson(lesson)
    assert "RULE:" in rendered
    assert "DRILL" in rendered
    assert "CUE:" in rendered


def test_coach_02_general_without_exact_judgment() -> None:
    cand = _candidate(lesson_id="m", concept_id="economy.reset_timing")
    lesson = build_teaching_lessons(
        _set(_prioritized(cand, tier=LessonTier.MAJOR)), candidates=[cand]
    ).lessons[0]
    assert lesson.alternative is not None
    assert lesson.alternative.certainty is AlternativeCertainty.GENERAL_ONLY
    assert lesson.teaching_specificity in {
        TeachingSpecificity.CONTEXTUAL,
        TeachingSpecificity.CONCEPT_GENERAL,
    }


def test_coach_04_mixed_qualified() -> None:
    cand = _candidate(
        lesson_id="mix",
        concept_id="economy.reset_timing",
        polarity=LessonPolarity.MIXED,
    )
    row = _prioritized(cand, tier=LessonTier.MAJOR)
    row = PrioritizedLesson(
        id=row.id,
        lesson_candidate_id=row.lesson_candidate_id,
        concept_id=row.concept_id,
        rank=row.rank,
        tier=row.tier,
        learning_value=row.learning_value,
        factors=row.factors,
        polarity=LessonPolarity.MIXED.value,
        support_level=row.support_level,
        occurrences=row.occurrences,
        specificity=row.specificity,
        capability_status=row.capability_status,
        conflicts=2,
        gaps=(),
        reason_codes=(),
    )
    lesson = build_teaching_lessons(_set(row), candidates=[cand]).lessons[0]
    assert any(code.code == "MIXED_EVIDENCE_QUALIFIED" for code in lesson.reason_codes)


def test_resolution_acknowledged_not_decision_good() -> None:
    cand = _candidate(
        lesson_id="r",
        concept_id="economy.reset_timing",
        resolution_notes=("f1:RESOLVED:purchase",),
    )
    lesson = build_teaching_lessons(
        _set(_prioritized(cand, tier=LessonTier.MAJOR)), candidates=[cand]
    ).lessons[0]
    text = " ".join(item.text for item in lesson.evidence_summary).lower()
    assert "changed shortly afterward" in text
    assert "corrected the mistake" not in text


def test_golden_major_package() -> None:
    cand = _candidate(lesson_id="gold", concept_id="economy.resource_spending")
    result = build_teaching_lessons(
        _set(_prioritized(cand, tier=LessonTier.MAJOR)), candidates=[cand]
    )
    lesson = result.lessons[0]
    assert lesson.evidence_summary
    assert lesson.why_it_matters is not None
    assert lesson.recognition_cue is not None
    assert lesson.memorable_rule is not None
    assert lesson.drill is not None
    assert lesson.objective is not None
    assert lesson.limitations
    assert "CAUSED_THE_OUTCOME" in lesson.forbidden_claims
    rendered = render_teaching_lesson_set(result)
    assert "EVIDENCE" in rendered
    assert "you should have recalled at" not in rendered.lower()


def test_end_to_end_c4_to_c5() -> None:
    from riftlens.coaching.prioritization import ScoringContext

    cand = _candidate(lesson_id="e2e", concept_id="economy.resource_spending")
    prioritized = prioritize_lesson_candidates(
        [cand],
        context=ScoringContext(teachability_by_concept={"economy.resource_spending": 0.9}),
    )
    assert prioritized.major
    taught = build_teaching_lessons(prioritized, candidates=[cand])
    assert taught.lessons
    assert taught.lessons[0].tier == LessonTier.MAJOR.value
    assert taught.lessons[0].rank == prioritized.major[0].rank


def test_playbook_coverage_table_shape() -> None:
    ids = implemented_playbook_ids()
    assert "economy.resource_spending" in ids
    assert "wave.management" not in ids
    rows = evaluate_teaching_readiness()
    assert any(item.concept_id == "wave.management" and not item.playbook_exists for item in rows)


def test_determinism() -> None:
    cand = _candidate(lesson_id="d", concept_id="laning.cs_maintenance")
    a = build_teaching_lessons(_set(_prioritized(cand, tier=LessonTier.MAJOR)), candidates=[cand])
    b = build_teaching_lessons(_set(_prioritized(cand, tier=LessonTier.MAJOR)), candidates=[cand])
    assert a.to_dict() == b.to_dict()


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
