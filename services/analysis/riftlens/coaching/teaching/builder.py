"""Build C.5 TeachingLesson packages from C.4 PrioritizedLessonSet."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from riftlens.coaching.concepts.models import LessonCandidate, LessonPolarity
from riftlens.coaching.prioritization.models import (
    LessonTier,
    PrioritizedLesson,
    PrioritizedLessonSet,
)
from riftlens.coaching.teaching.models import (
    TEACHING_METHOD,
    TEACHING_METHOD_VERSION,
    TEACHING_PRODUCER,
    TEACHING_PRODUCER_VERSION,
    TEACHING_SCHEMA_VERSION,
    Alternative,
    AlternativeCertainty,
    ContentOrigin,
    PracticeDrill,
    PracticeObjective,
    ReasonCode,
    TeachingDepth,
    TeachingLesson,
    TeachingLessonSet,
    TeachingSpecificity,
    TeachingStatement,
    empty_teaching_set,
    teaching_lesson_id,
)
from riftlens.coaching.teaching.playbooks import (
    BLOCKED_TEACHING_CONCEPTS,
    BLOCKED_WAVE_ACTIONS,
    get_concept_playbook,
)
from riftlens.domain.fact import Provenance


def _depth_for(tier: LessonTier) -> TeachingDepth:
    if tier is LessonTier.MAJOR:
        return TeachingDepth.FULL
    if tier is LessonTier.SECONDARY:
        return TeachingDepth.LIGHT
    if tier is LessonTier.STRENGTH:
        return TeachingDepth.REINFORCEMENT
    return TeachingDepth.NONE


def _specificity_for(
    tier: LessonTier,
    max_spec: TeachingSpecificity,
    *,
    mixed: bool,
) -> TeachingSpecificity:
    if max_spec is TeachingSpecificity.UNAVAILABLE:
        return TeachingSpecificity.UNAVAILABLE
    # C.2 has zero decision contracts → never claim EVENT_SPECIFIC decision judgment.
    if mixed:
        return TeachingSpecificity.CONCEPT_GENERAL
    if tier is LessonTier.MAJOR:
        # Contextual evidence summary + concept-general teaching.
        return (
            TeachingSpecificity.CONTEXTUAL
            if max_spec
            in {TeachingSpecificity.CONTEXTUAL, TeachingSpecificity.EVENT_SPECIFIC}
            else TeachingSpecificity.CONCEPT_GENERAL
        )
    return TeachingSpecificity.CONCEPT_GENERAL


def _evidence_summary(
    prioritized: PrioritizedLesson,
    candidate: LessonCandidate | None,
) -> tuple[TeachingStatement, ...]:
    parts: list[str] = []
    parts.append(
        f"{prioritized.occurrences} within-match observation(s) for concept "
        f"{prioritized.concept_id}."
    )
    parts.append(f"Support level: {prioritized.support_level}.")
    if prioritized.conflicts:
        parts.append(
            f"Mixed/conflicting evidence present ({prioritized.conflicts} conflict ref(s))."
        )
    if candidate is not None and candidate.condition_resolution_notes:
        parts.append(
            "A related measurable condition changed shortly afterward "
            "(resolution does not prove the original decision was correct)."
        )
    if candidate is not None:
        parts.append(
            f"Linked findings: {len(candidate.finding_ids)}; "
            f"episodes: {len(candidate.episode_ids)}."
        )
    return tuple(
        TeachingStatement(
            text=text,
            origin=ContentOrigin.MATCH_EVIDENCE,
            specificity=TeachingSpecificity.CONTEXTUAL,
            reason_codes=(ReasonCode("EVIDENCE_BOUNDED_SUMMARY"),),
        )
        for text in parts
    )


def _selection_codes(prioritized: PrioritizedLesson) -> tuple[ReasonCode, ...]:
    return tuple(
        ReasonCode(code=item.code, detail=item.detail)
        for item in prioritized.reason_codes
    )


def build_teaching_lesson(
    prioritized: PrioritizedLesson,
    *,
    candidate: LessonCandidate | None = None,
) -> TeachingLesson | None:
    """Build one teaching lesson. WITHHELD → None. Blocked concepts → unavailable shell."""
    if prioritized.tier is LessonTier.WITHHELD:
        return None

    depth = _depth_for(prioritized.tier)
    concept_id = prioritized.concept_id
    mixed = prioritized.polarity == LessonPolarity.MIXED.value
    codes: list[ReasonCode] = [
        ReasonCode("C4_TIER_PRESERVED", prioritized.tier.value),
        ReasonCode("C2_DECISION_UNKNOWN_RESPECTED", "no exact decision judgment"),
        ReasonCode("C3_NO_SUPPORTED_CAUSALITY", "no caused-claims"),
    ]

    if concept_id in BLOCKED_TEACHING_CONCEPTS:
        return TeachingLesson(
            id=teaching_lesson_id(prioritized.id, concept_id),
            schema_version=TEACHING_SCHEMA_VERSION,
            prioritized_lesson_id=prioritized.id,
            lesson_candidate_id=prioritized.lesson_candidate_id,
            concept_id=concept_id,
            tier=prioritized.tier.value,
            rank=prioritized.rank,
            teaching_specificity=TeachingSpecificity.UNAVAILABLE,
            teaching_depth=TeachingDepth.NONE,
            evidence_summary=_evidence_summary(prioritized, candidate),
            concept_explanation=None,
            why_it_matters=None,
            alternative=Alternative(
                action="",
                certainty=AlternativeCertainty.UNAVAILABLE,
                limitations=("capability_blocked",),
                reason_codes=(ReasonCode("CAPABILITY_BLOCKED_TEACHING"),),
            ),
            recognition_cue=None,
            memorable_rule=None,
            drill=None,
            objective=None,
            limitations=(
                "specific teaching unavailable due to blocked capability",
                "no freeze/slow-push/mechanics/summoner fabrication",
            ),
            forbidden_claims=tuple(BLOCKED_WAVE_ACTIONS)
            + (
                "MECHANICAL_CORRECTION",
                "FLASH_CORRECTION",
                "WARD_QUALITY_CLAIM",
            ),
            selection_reason_codes=_selection_codes(prioritized),
            reason_codes=tuple(codes + [ReasonCode("TEACHING_UNAVAILABLE", concept_id)]),
            provenance=Provenance(
                producer=TEACHING_PRODUCER,
                producer_version=TEACHING_PRODUCER_VERSION,
                upstream=(prioritized.id, prioritized.lesson_candidate_id),
            ),
            support_level=prioritized.support_level,
            polarity=prioritized.polarity,
            confidence=0.0,
        )

    playbook = get_concept_playbook(concept_id)
    if playbook is None:
        # No playbook: evidence-only stub, no invented teaching.
        return TeachingLesson(
            id=teaching_lesson_id(prioritized.id, concept_id),
            schema_version=TEACHING_SCHEMA_VERSION,
            prioritized_lesson_id=prioritized.id,
            lesson_candidate_id=prioritized.lesson_candidate_id,
            concept_id=concept_id,
            tier=prioritized.tier.value,
            rank=prioritized.rank,
            teaching_specificity=TeachingSpecificity.UNAVAILABLE,
            teaching_depth=TeachingDepth.NONE,
            evidence_summary=_evidence_summary(prioritized, candidate),
            concept_explanation=None,
            why_it_matters=None,
            alternative=None,
            recognition_cue=None,
            memorable_rule=None,
            drill=None,
            objective=None,
            limitations=("no curated playbook for this concept",),
            forbidden_claims=("INVENTED_TEACHING",),
            selection_reason_codes=_selection_codes(prioritized),
            reason_codes=tuple(codes + [ReasonCode("NO_PLAYBOOK", concept_id)]),
            provenance=Provenance(
                producer=TEACHING_PRODUCER,
                producer_version=TEACHING_PRODUCER_VERSION,
                upstream=(prioritized.id,),
            ),
            support_level=prioritized.support_level,
            polarity=prioritized.polarity,
            confidence=0.0,
        )

    specificity = _specificity_for(prioritized.tier, playbook.max_specificity, mixed=mixed)
    explanation = TeachingStatement(
        text=playbook.explanation,
        origin=ContentOrigin.GENERAL_GAME_PRINCIPLE,
        specificity=TeachingSpecificity.CONCEPT_GENERAL,
        reason_codes=(ReasonCode("PLAYBOOK_EXPLANATION"),),
    )
    why = TeachingStatement(
        text=playbook.why_it_matters,
        origin=ContentOrigin.GENERAL_GAME_PRINCIPLE,
        specificity=TeachingSpecificity.CONCEPT_GENERAL,
        reason_codes=(ReasonCode("PLAYBOOK_WHY"),),
    )

    alternative = Alternative(
        action=playbook.alternative_general,
        certainty=playbook.alternative_certainty,
        limitations=(
            "not an exact timestamp directive",
            "does not claim the match decision was wrong",
        ),
        evidence_contract="GENERAL_ONLY until C.2 decision contracts exist",
        reason_codes=(ReasonCode("ALTERNATIVE_GENERAL_ONLY"),),
    )

    cue = playbook.recognition_cue
    rule = playbook.memorable_rule
    drill = playbook.drill
    objective: PracticeObjective | None = playbook.objective_template
    if objective is not None:
        objective = PracticeObjective(
            concept_id=objective.concept_id,
            target_behavior=objective.target_behavior,
            observable=objective.observable,
            evaluation_mode=objective.evaluation_mode,
            success_definition=objective.success_definition,
            required_future_evidence=objective.required_future_evidence,
            measurability=objective.measurability,
            outcome_goal=False,
            prior_lesson_id=prioritized.id,
            reason_codes=objective.reason_codes,
        )

    # Depth trimming
    out_drill: PracticeDrill | None = drill
    out_objective: PracticeObjective | None = objective
    out_alternative = alternative
    if depth is TeachingDepth.LIGHT:
        out_drill = None
        out_objective = None
        codes.append(ReasonCode("LIGHT_TEACHING_DEPTH", "secondary"))
    elif depth is TeachingDepth.REINFORCEMENT:
        out_alternative = Alternative(
            action=playbook.alternative_general,
            certainty=AlternativeCertainty.GENERAL_ONLY,
            alternative_type="REINFORCEMENT",
            limitations=("not a mastery claim",),
            reason_codes=(ReasonCode("STRENGTH_REINFORCEMENT"),),
        )
        if not playbook.strength_mode:
            out_drill = None
        codes.append(ReasonCode("STRENGTH_TEACHING", "reinforce positive pattern"))

    if mixed:
        codes.append(
            ReasonCode(
                "MIXED_EVIDENCE_QUALIFIED",
                "avoid consistent-weakness overclaim",
            )
        )

    limitations = [
        "C.2 decision quality remains UNKNOWN for production",
        "C.3 has no SUPPORTED causal contracts",
        "general principles are not match evidence",
    ]
    if playbook.notes:
        limitations.append(playbook.notes)

    return TeachingLesson(
        id=teaching_lesson_id(prioritized.id, concept_id),
        schema_version=TEACHING_SCHEMA_VERSION,
        prioritized_lesson_id=prioritized.id,
        lesson_candidate_id=prioritized.lesson_candidate_id,
        concept_id=concept_id,
        tier=prioritized.tier.value,
        rank=prioritized.rank,
        teaching_specificity=specificity,
        teaching_depth=depth,
        evidence_summary=_evidence_summary(prioritized, candidate),
        concept_explanation=explanation,
        why_it_matters=why,
        alternative=out_alternative,
        recognition_cue=cue,
        memorable_rule=rule,
        drill=out_drill,
        objective=out_objective,
        limitations=tuple(limitations),
        forbidden_claims=playbook.forbidden_claims,
        selection_reason_codes=_selection_codes(prioritized),
        reason_codes=tuple(codes),
        provenance=Provenance(
            producer=TEACHING_PRODUCER,
            producer_version=TEACHING_PRODUCER_VERSION,
            upstream=(prioritized.id, prioritized.lesson_candidate_id, concept_id),
        ),
        support_level=prioritized.support_level,
        polarity=prioritized.polarity,
        confidence=min(1.0, max(0.0, prioritized.learning_value / 100.0)),
    )


def build_teaching_lessons(
    prioritized_set: PrioritizedLessonSet,
    *,
    candidates: Sequence[LessonCandidate] | Mapping[str, LessonCandidate] | None = None,
) -> TeachingLessonSet:
    """Build teaching lessons for MAJOR/SECONDARY/STRENGTH rows. Empty → empty.

    WITHHELD lessons are skipped (recorded in skipped_withheld).
    Does not change C.4 ranks/tiers.
    """
    if not prioritized_set.ranked and not prioritized_set.major:
        # Truly empty set
        if (
            not prioritized_set.major
            and not prioritized_set.secondary
            and not prioritized_set.strengths
            and not prioritized_set.withheld
        ):
            return empty_teaching_set(
                prioritized_set.match_id, prioritized_set.participant_id
            )

    by_id: dict[str, LessonCandidate] = {}
    if isinstance(candidates, Mapping):
        by_id = dict(candidates)
    elif candidates is not None:
        by_id = {item.id: item for item in candidates}

    lessons: list[TeachingLesson] = []
    skipped: list[str] = []

    # Preserve C.4 ordering: major, secondary, strengths
    ordered = [
        *prioritized_set.major,
        *prioritized_set.secondary,
        *prioritized_set.strengths,
    ]
    for item in ordered:
        built = build_teaching_lesson(
            item, candidate=by_id.get(item.lesson_candidate_id)
        )
        if built is not None:
            lessons.append(built)

    for item in prioritized_set.withheld:
        skipped.append(item.lesson_candidate_id)

    notes = [
        ReasonCode("C4_ORDER_PRESERVED"),
        ReasonCode("NO_PRODUCTION_WIRING"),
    ]
    if skipped:
        notes.append(ReasonCode("WITHHELD_UPSTREAM", f"count={len(skipped)}"))

    return TeachingLessonSet(
        schema_version=TEACHING_SCHEMA_VERSION,
        match_id=prioritized_set.match_id,
        participant_id=prioritized_set.participant_id,
        method=TEACHING_METHOD,
        method_version=TEACHING_METHOD_VERSION,
        lessons=tuple(lessons),
        skipped_withheld=tuple(skipped),
        notes=tuple(notes),
    )
