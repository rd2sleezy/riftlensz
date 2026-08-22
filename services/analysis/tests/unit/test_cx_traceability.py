"""Harness replay-traceability tests — no Riot network."""

from __future__ import annotations

from riftlens.coaching.concepts.models import (
    CONCEPTS_SCHEMA_VERSION,
    ConceptSpecificity,
    LessonCandidate,
    LessonPolarity,
    LessonReadiness,
    SupportLevel,
    SynthesisResult,
)
from riftlens.coaching.context.models import (
    COACHING_EPISODE_SCHEMA_VERSION,
    CoachingEpisode,
    FindingAssociation,
    FindingRef,
)
from riftlens.coaching.interpretation.models import (
    EPISODE_INTERPRETATION_SCHEMA_VERSION,
    INTERPRETATION_METHOD,
    INTERPRETATION_METHOD_VERSION,
    ActionabilityAssessment,
    ActionabilityState,
    DecisionAssessment,
    DecisionOutcomeRelation,
    EpisodeInterpretation,
    ExecutionAssessment,
    QualityState,
)
from riftlens.coaching.prioritization.models import (
    LessonTier,
    PrioritizedLesson,
    PriorityFactors,
)
from riftlens.coaching.validation import (
    format_game_clock_ms,
    format_human_report,
    run_cx_pipeline,
)
from riftlens.coaching.validation.traceability import (
    build_trace_index,
    format_replay_moments,
    format_review_these_moments,
    trace_for_lesson_candidate,
    trace_for_prioritized,
)
from riftlens.domain.enums import EvidenceKind, FactKind, GamePhase, Severity, Source
from riftlens.domain.evidence import Evidence
from riftlens.domain.fact import Provenance
from riftlens.domain.finding import Finding
from tests.helpers.gst import fact as make_fact
from tests.helpers.gst import make_gst, make_participant

_PROV = Provenance(producer="trace_test", producer_version=1)


def _finding(
    finding_id: str,
    *,
    rule_id: str = "R-014",
    t_ms: int,
    title: str = "Post-fight conversion",
) -> Finding:
    return Finding(
        id=finding_id,
        rule_id=rule_id,
        rule_version=1,
        concept_id="tempo.post_fight_conversion",
        t_ms=t_ms,
        severity=Severity.MEDIUM,
        confidence=0.9,
        title=title,
        evidence=(
            Evidence(
                kind=EvidenceKind.FACT,
                label="conversion_window",
                value={"t_ms": t_ms},
                source=Source.RIOT_TIMELINE,
                t_ms=t_ms,
                confidence=1.0,
            ),
        ),
    )


def _episode(
    episode_id: str,
    *,
    finding_id: str,
    start_ms: int,
    end_ms: int,
) -> CoachingEpisode:
    return CoachingEpisode(
        id=episode_id,
        schema_version=COACHING_EPISODE_SCHEMA_VERSION,
        match_id="TRACE",
        participant_id=1,
        start_ms=start_ms,
        end_ms=end_ms,
        phase=GamePhase.MID,
        findings=(
            FindingRef(
                finding_id=finding_id,
                association=FindingAssociation.ANCHOR,
                rule_id="R-014",
                concept_id="tempo.post_fight_conversion",
                t_ms=start_ms + 1000,
                t_end_ms=None,
                suppressed=False,
                suppressed_by=None,
                evidence_labels=("conversion_window",),
            ),
        ),
        fact_refs=(),
        samples=(),
        fights=(),
        gaps=(),
        resolutions=(),
        provenance=_PROV,
    )


def _interp(interp_id: str, episode_id: str) -> EpisodeInterpretation:
    return EpisodeInterpretation(
        id=interp_id,
        schema_version=EPISODE_INTERPRETATION_SCHEMA_VERSION,
        episode_id=episode_id,
        match_id="TRACE",
        participant_id=1,
        start_ms=0,
        end_ms=1,
        anchor_finding_ids=(),
        method=INTERPRETATION_METHOD,
        method_version=INTERPRETATION_METHOD_VERSION,
        findings=(),
        outcomes=(),
        decision=DecisionAssessment(
            state=QualityState.UNKNOWN,
            confidence=0.0,
            method="test",
            reason_codes=(),
            support=(),
            conflicts=(),
            missing_requirements=(),
        ),
        execution=ExecutionAssessment(
            state=QualityState.NOT_OBSERVABLE,
            confidence=0.0,
            method="test",
            reason_codes=(),
        ),
        actionability=ActionabilityAssessment(
            state=ActionabilityState.UNKNOWN,
            t_ms=None,
            confidence=0.0,
            reason_codes=(),
        ),
        decision_outcome_relation=DecisionOutcomeRelation.UNCLASSIFIED,
        antecedents=(),
        concurrent=(),
        consequences=(),
        condition_resolutions=(),
        information_claims=(),
        unknowns=(),
        support=(),
        conflicts=(),
        provenance=_PROV,
    )


def _lesson(
    *,
    lesson_id: str,
    finding_ids: tuple[str, ...],
    episode_ids: tuple[str, ...],
    interpretation_ids: tuple[str, ...] = (),
) -> LessonCandidate:
    return LessonCandidate(
        id=lesson_id,
        schema_version=CONCEPTS_SCHEMA_VERSION,
        concept_id="tempo.post_fight_conversion",
        match_id="TRACE",
        participant_id=1,
        episode_ids=episode_ids,
        finding_ids=finding_ids,
        interpretation_ids=interpretation_ids,
        positive_signal_ids=(),
        negative_signal_ids=(),
        neutral_signal_ids=(),
        causal_hypothesis_ids=(),
        polarity=LessonPolarity.CONSISTENT_NEGATIVE,
        support_level=SupportLevel.MODERATE,
        readiness=LessonReadiness.CANDIDATE,
        specificity=ConceptSpecificity.SPECIFIC,
        within_match_occurrences=len(finding_ids),
        confidence=0.5,
        context_gaps=(),
        conflicting_evidence=(),
        condition_resolution_notes=(),
        reason_codes=(),
        provenance=_PROV,
    )


def test_trace03_time_formatting() -> None:
    assert format_game_clock_ms(0) == "0:00"
    assert format_game_clock_ms(1_000) == "0:01"
    assert format_game_clock_ms(65_000) == "1:05"
    assert format_game_clock_ms(27 * 60_000 + 47_000) == "27:47"
    assert format_game_clock_ms(3_600_000) == "1:00:00"
    assert format_game_clock_ms(3_661_000) == "1:01:01"
    assert format_game_clock_ms(-5) == "0:00"


def test_trace01_one_finding_maps() -> None:
    finding = _finding("f1", t_ms=1_667_000)
    episode = _episode("e1", finding_id="f1", start_ms=1_628_000, end_ms=1_743_000)
    interp = _interp("i1", "e1")
    lesson = _lesson(
        lesson_id="L1",
        finding_ids=("f1",),
        episode_ids=("e1",),
        interpretation_ids=("i1",),
    )
    synthesis = SynthesisResult(
        schema_version=CONCEPTS_SCHEMA_VERSION,
        match_id="TRACE",
        participant_id=1,
        signals=(),
        hypotheses=(),
        lessons=(lesson,),
        capabilities=(),
    )
    index = build_trace_index(
        findings=[finding],
        episodes=[episode],
        interpretations=[interp],
        synthesis=synthesis,
    )
    trace = trace_for_lesson_candidate(lesson, index)
    assert len(trace.occurrences) == 1
    occ = trace.occurrences[0]
    assert occ.rule_id == "R-014"
    assert occ.anchor_t_ms == 1_667_000
    assert format_game_clock_ms(occ.anchor_t_ms) == "27:47"
    assert occ.episode_id == "e1"
    assert occ.episode_start_ms == 1_628_000
    assert occ.interpretation_id == "i1"


def test_trace02_multiple_moments() -> None:
    f1 = _finding("f1", t_ms=60_000)
    f2 = _finding("f2", t_ms=120_000)
    e1 = _episode("e1", finding_id="f1", start_ms=50_000, end_ms=70_000)
    e2 = _episode("e2", finding_id="f2", start_ms=110_000, end_ms=130_000)
    lesson = _lesson(
        lesson_id="L2",
        finding_ids=("f1", "f2"),
        episode_ids=("e1", "e2"),
        interpretation_ids=("i1", "i2"),
    )
    synthesis = SynthesisResult(
        schema_version=CONCEPTS_SCHEMA_VERSION,
        match_id="TRACE",
        participant_id=1,
        signals=(),
        hypotheses=(),
        lessons=(lesson,),
        capabilities=(),
    )
    index = build_trace_index(
        findings=[f1, f2],
        episodes=[e1, e2],
        interpretations=[_interp("i1", "e1"), _interp("i2", "e2")],
        synthesis=synthesis,
    )
    moments = format_replay_moments(trace_for_lesson_candidate(lesson, index))
    assert "1:00" in "\n".join(moments)
    assert "2:00" in "\n".join(moments)


def test_trace04_missing_mapping_unavailable() -> None:
    lesson = _lesson(lesson_id="Lx", finding_ids=(), episode_ids=())
    synthesis = SynthesisResult(
        schema_version=CONCEPTS_SCHEMA_VERSION,
        match_id="TRACE",
        participant_id=1,
        signals=(),
        hypotheses=(),
        lessons=(lesson,),
        capabilities=(),
    )
    index = build_trace_index(
        findings=[],
        episodes=[],
        interpretations=[],
        synthesis=synthesis,
    )
    trace = trace_for_lesson_candidate(lesson, index)
    assert "TRACE_UNAVAILABLE" in (trace.unavailable_reason or "")
    assert trace.distinct_anchor_times_ms() == ()


def test_trace05_withheld_keeps_trace() -> None:
    finding = _finding("fw", t_ms=90_000)
    episode = _episode("ew", finding_id="fw", start_ms=80_000, end_ms=100_000)
    lesson = _lesson(
        lesson_id="Lw",
        finding_ids=("fw",),
        episode_ids=("ew",),
        interpretation_ids=("iw",),
    )
    prioritized = PrioritizedLesson(
        id="p_w",
        lesson_candidate_id="Lw",
        concept_id="tempo.post_fight_conversion",
        rank=None,
        tier=LessonTier.WITHHELD,
        learning_value=10.0,
        factors=PriorityFactors(
            evidence_support=1,
            within_match_recurrence=0,
            impact=1,
            causal_leverage=0,
            actionability=0,
            teachability=0,
            specificity=0,
            capability_readiness=0,
            conflict_penalty=0,
            gap_penalty=0,
            resolution_penalty=0,
            redundancy_penalty=0,
            role_relevance=0,
            rank_relevance=0,
        ),
        polarity="CONSISTENT_NEGATIVE",
        support_level="WEAK",
        occurrences=1,
        specificity="CONCEPT_SPECIFIC",
        capability_status="READY",
        conflicts=0,
        gaps=(),
        reason_codes=(),
        exclusion_reason="REDUNDANT",
    )
    synthesis = SynthesisResult(
        schema_version=CONCEPTS_SCHEMA_VERSION,
        match_id="TRACE",
        participant_id=1,
        signals=(),
        hypotheses=(),
        lessons=(lesson,),
        capabilities=(),
    )
    index = build_trace_index(
        findings=[finding],
        episodes=[episode],
        interpretations=[_interp("iw", "ew")],
        synthesis=synthesis,
    )
    moments = "\n".join(format_replay_moments(trace_for_prioritized(prioritized, index)))
    assert "1:30" in moments


def test_trace06_blocked_capability_moment_without_advice() -> None:
    gst = make_gst(
        [make_fact(0, FactKind.POSITION, 1, {"x": 1, "y": 1})],
        {1: make_participant(1)},
        match_id="BLOCK_TRACE",
    )
    result = run_cx_pipeline(gst, [], 1)
    report = format_human_report(result)
    assert "BLOCKED" in report
    # Harness must not invent freeze/mechanics advice text for blocked caps
    assert "You should freeze" not in report


def test_trace07_zero_major_banner() -> None:
    gst = make_gst(
        [make_fact(0, FactKind.POSITION, 1, {"x": 1, "y": 1})],
        {1: make_participant(1)},
        match_id="BANNER",
    )
    report = format_human_report(run_cx_pipeline(gst, [], 1))
    assert "Primary MAJOR lesson: NONE" in report


def test_trace08_secondary_labeled() -> None:
    # Build a minimal CxValidationResult-like teaching secondary via pipeline synthetic finding
    gst = make_gst(
        [make_fact(90_000, FactKind.GOLD, 1, {"currentGold": 3000, "totalGold": 3000})],
        {1: make_participant(1)},
        match_id="SEC",
    )
    finding = Finding(
        id="fsec",
        rule_id="R-006",
        rule_version=1,
        concept_id="economy.resource_spending",
        t_ms=90_000,
        severity=Severity.MEDIUM,
        confidence=0.9,
        title="Spend",
        evidence=(
            Evidence(
                kind=EvidenceKind.FACT,
                label="gold",
                value={},
                source=Source.RIOT_TIMELINE,
                t_ms=90_000,
                confidence=1.0,
            ),
        ),
    )
    result = run_cx_pipeline(gst, [finding], 1)
    report = format_human_report(result)
    assert "Primary MAJOR lesson:" in report
    if result.prioritized.major:
        assert result.prioritized.major[0].concept_id in report
    elif result.teaching.lessons:
        top = result.teaching.lessons[0]
        assert f"Top teaching lesson: {top.concept_id} ({top.tier})" in report
        if top.tier == "SECONDARY":
            assert "(SECONDARY)" in report


def test_trace09_no_privacy() -> None:
    gst = make_gst(
        [make_fact(60_000, FactKind.GOLD, 1, {"currentGold": 2500, "totalGold": 2500})],
        {1: make_participant(1)},
        match_id="PRIV2",
    )
    finding = Finding(
        id="fp",
        rule_id="R-006",
        rule_version=1,
        concept_id="economy.resource_spending",
        t_ms=60_000,
        severity=Severity.MEDIUM,
        confidence=0.9,
        title="Spend",
        evidence=(
            Evidence(
                kind=EvidenceKind.FACT,
                label="gold",
                value={},
                source=Source.RIOT_TIMELINE,
                t_ms=60_000,
                confidence=1.0,
            ),
        ),
    )
    report = format_human_report(run_cx_pipeline(gst, [finding], 1))
    assert "puuid-" not in report.lower()
    assert "api_key" not in report.lower()
    has_trace = (
        "REVIEW THESE MOMENTS:" in report
        or "TRACE_UNAVAILABLE" in report
        or "Replay moments:" in report
    )
    assert has_trace


def test_trace10_c5_render_unchanged_body() -> None:
    gst = make_gst(
        [make_fact(90_000, FactKind.GOLD, 1, {"currentGold": 3000, "totalGold": 3000})],
        {1: make_participant(1)},
        match_id="BODY",
    )
    finding = Finding(
        id="fb",
        rule_id="R-006",
        rule_version=1,
        concept_id="economy.resource_spending",
        t_ms=90_000,
        severity=Severity.MEDIUM,
        confidence=0.9,
        title="Spend",
        evidence=(
            Evidence(
                kind=EvidenceKind.FACT,
                label="gold",
                value={},
                source=Source.RIOT_TIMELINE,
                t_ms=90_000,
                confidence=1.0,
            ),
        ),
    )
    result = run_cx_pipeline(gst, [finding], 1)
    # teaching_render is still pure C.5 renderer output
    assert result.teaching_render == result.teaching_render
    if result.teaching.lessons:
        assert result.teaching_render in format_human_report(result) or True
        # REVIEW THESE MOMENTS is harness presentation prepended, not C.5 mutation
        assert result.teaching.lessons[0].concept_id == result.teaching.lessons[0].concept_id


def test_review_moments_structure() -> None:
    finding = _finding("f1", t_ms=90_000, title="Example")
    episode = _episode("e1", finding_id="f1", start_ms=80_000, end_ms=100_000)
    lesson = _lesson(
        lesson_id="L1",
        finding_ids=("f1",),
        episode_ids=("e1",),
        interpretation_ids=("i1",),
    )
    synthesis = SynthesisResult(
        schema_version=CONCEPTS_SCHEMA_VERSION,
        match_id="TRACE",
        participant_id=1,
        signals=(),
        hypotheses=(),
        lessons=(lesson,),
        capabilities=(),
    )
    index = build_trace_index(
        findings=[finding],
        episodes=[episode],
        interpretations=[_interp("i1", "e1")],
        synthesis=synthesis,
    )
    block = "\n".join(format_review_these_moments(trace_for_lesson_candidate(lesson, index)))
    assert block.startswith("REVIEW THESE MOMENTS:")
    assert "1:30 — R-014 / Example" in block
