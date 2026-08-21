"""Prioritize LessonCandidates into MAJOR / SECONDARY / STRENGTH / WITHHELD."""

from __future__ import annotations

from collections.abc import Sequence

from riftlens.coaching.concepts.models import (
    CapabilityStatus,
    LessonCandidate,
    LessonPolarity,
    LessonReadiness,
    SupportLevel,
)
from riftlens.coaching.prioritization.config import (
    DEFAULT_LEARNING_VALUE_CONFIG,
    LearningValueConfig,
)
from riftlens.coaching.prioritization.models import (
    PRIORITIZATION_METHOD,
    PRIORITIZATION_METHOD_VERSION,
    PRIORITIZATION_PRODUCER,
    PRIORITIZATION_PRODUCER_VERSION,
    PRIORITIZATION_SCHEMA_VERSION,
    ActionabilityHint,
    LessonTier,
    OverlapRelation,
    PrioritizedLesson,
    PrioritizedLessonSet,
    PriorityFactors,
    ReasonCode,
    ScoringContext,
    empty_prioritized_set,
    prioritized_lesson_id,
)
from riftlens.coaching.prioritization.redundancy import (
    overlap_relation,
    redundancy_penalty_for,
)
from riftlens.coaching.prioritization.scorer import score_lesson_candidates
from riftlens.domain.fact import Provenance


def _is_strength(lesson: LessonCandidate) -> bool:
    return lesson.polarity is LessonPolarity.CONSISTENT_POSITIVE


def _with_rank(item: PrioritizedLesson, rank: int) -> PrioritizedLesson:
    return PrioritizedLesson(
        id=item.id,
        lesson_candidate_id=item.lesson_candidate_id,
        concept_id=item.concept_id,
        rank=rank,
        tier=item.tier,
        learning_value=item.learning_value,
        factors=item.factors,
        polarity=item.polarity,
        support_level=item.support_level,
        occurrences=item.occurrences,
        specificity=item.specificity,
        capability_status=item.capability_status,
        conflicts=item.conflicts,
        gaps=item.gaps,
        reason_codes=item.reason_codes,
        exclusion_reason=item.exclusion_reason,
        overlap_with=item.overlap_with,
        provenance=item.provenance,
    )


def _as_withheld(item: PrioritizedLesson, reason: str) -> PrioritizedLesson:
    return PrioritizedLesson(
        id=item.id,
        lesson_candidate_id=item.lesson_candidate_id,
        concept_id=item.concept_id,
        rank=None,
        tier=LessonTier.WITHHELD,
        learning_value=item.learning_value,
        factors=item.factors,
        polarity=item.polarity,
        support_level=item.support_level,
        occurrences=item.occurrences,
        specificity=item.specificity,
        capability_status=item.capability_status,
        conflicts=item.conflicts,
        gaps=item.gaps,
        reason_codes=(*item.reason_codes, ReasonCode(reason)),
        exclusion_reason=reason,
        overlap_with=item.overlap_with,
        provenance=item.provenance,
    )


def _major_blocked(
    lesson: LessonCandidate,
    factors: PriorityFactors,
    cap_status: CapabilityStatus,
    config: LearningValueConfig,
    actionability: ActionabilityHint,
) -> str | None:
    """Return exclusion reason if MAJOR promotion is forbidden."""
    if config.block_major_if_insufficient_support and (
        lesson.support_level is SupportLevel.INSUFFICIENT
    ):
        return "INSUFFICIENT_SUPPORT"
    if config.block_major_if_readiness_blocked and (
        lesson.readiness is LessonReadiness.BLOCKED
    ):
        return "CAPABILITY_BLOCKED"
    if config.block_major_if_capability_blocked and (
        cap_status is CapabilityStatus.BLOCKED
    ):
        return "CAPABILITY_BLOCKED"
    if config.block_major_if_not_actionable and (
        actionability is ActionabilityHint.NOT_ACTIONABLE
    ):
        return "NOT_ACTIONABLE"
    if factors.total() < config.major_threshold:
        return "LOW_LEARNING_VALUE"
    return None


def _build_item(
    lesson: LessonCandidate,
    factors: PriorityFactors,
    codes: Sequence[ReasonCode],
    cap_status: CapabilityStatus,
    *,
    tier: LessonTier,
    rank: int | None,
    exclusion: str | None,
    overlap_with: tuple[str, ...] = (),
) -> PrioritizedLesson:
    return PrioritizedLesson(
        id=prioritized_lesson_id(lesson.id, PRIORITIZATION_METHOD_VERSION),
        lesson_candidate_id=lesson.id,
        concept_id=lesson.concept_id,
        rank=rank,
        tier=tier,
        learning_value=round(factors.total(), 4),
        factors=factors,
        polarity=lesson.polarity.value,
        support_level=lesson.support_level.value,
        occurrences=lesson.within_match_occurrences,
        specificity=lesson.specificity.value,
        capability_status=cap_status.value,
        conflicts=len(lesson.conflicting_evidence),
        gaps=tuple(lesson.context_gaps),
        reason_codes=tuple(codes),
        exclusion_reason=exclusion,
        overlap_with=overlap_with,
        provenance=Provenance(
            producer=PRIORITIZATION_PRODUCER,
            producer_version=PRIORITIZATION_PRODUCER_VERSION,
            upstream=(lesson.id,),
        ),
    )


def _apply_safety_cap(
    items: list[PrioritizedLesson],
    cap: int | None,
) -> tuple[list[PrioritizedLesson], list[PrioritizedLesson]]:
    if cap is None or len(items) <= cap:
        return items, []
    return items[:cap], [_as_withheld(item, "SAFETY_CAP") for item in items[cap:]]


def prioritize_lesson_candidates(
    lessons: Sequence[LessonCandidate],
    *,
    config: LearningValueConfig | None = None,
    context: ScoringContext | None = None,
    match_id: str | None = None,
    participant_id: int | None = None,
) -> PrioritizedLessonSet:
    """Promote LessonCandidates by learning value. Empty → empty set.

    Major count is threshold-driven (not focus_count=3). Strengths ranked
    separately. Redundancy can withhold overlapping lower-value lessons.
    """
    cfg = config or DEFAULT_LEARNING_VALUE_CONFIG
    ctx = context or ScoringContext()

    if not lessons:
        return empty_prioritized_set(
            match_id or "",
            participant_id or 0,
            config_version=cfg.version,
        )

    mid = match_id if match_id is not None else lessons[0].match_id
    pid = participant_id if participant_id is not None else lessons[0].participant_id

    scored = score_lesson_candidates(lessons, config=cfg, context=ctx)
    notes: list[ReasonCode] = [
        ReasonCode(
            "EVIDENCE_DRIVEN_COUNTS",
            "major/secondary counts come from thresholds, not a fixed quota",
        )
    ]

    strength_rows = [row for row in scored if _is_strength(row[0])]
    weakness_rows = [row for row in scored if not _is_strength(row[0])]

    # Strengths — separate track, variable count, no forced 2–3.
    strength_promoted: list[PrioritizedLesson] = []
    strength_withheld: list[PrioritizedLesson] = []
    for lesson, factors, codes, cap in strength_rows:
        ok = (
            factors.total() >= cfg.strength_threshold
            and lesson.support_level is not SupportLevel.INSUFFICIENT
            and lesson.readiness is not LessonReadiness.BLOCKED
            and cap is not CapabilityStatus.BLOCKED
        )
        if ok:
            strength_promoted.append(
                _build_item(
                    lesson,
                    factors,
                    codes,
                    cap,
                    tier=LessonTier.STRENGTH,
                    rank=None,
                    exclusion=None,
                )
            )
        else:
            reason = "LOW_LEARNING_VALUE"
            if lesson.support_level is SupportLevel.INSUFFICIENT:
                reason = "INSUFFICIENT_SUPPORT"
            elif (
                cap is CapabilityStatus.BLOCKED
                or lesson.readiness is LessonReadiness.BLOCKED
            ):
                reason = "CAPABILITY_BLOCKED"
            strength_withheld.append(
                _build_item(
                    lesson,
                    factors,
                    codes,
                    cap,
                    tier=LessonTier.WITHHELD,
                    rank=None,
                    exclusion=reason,
                )
            )

    strength_promoted.sort(
        key=lambda item: (-item.learning_value, item.concept_id, item.lesson_candidate_id)
    )
    strength_promoted, strength_cap_extra = _apply_safety_cap(
        strength_promoted, cfg.max_strength_safety_cap
    )
    if strength_cap_extra:
        notes.append(ReasonCode("STRENGTH_SAFETY_CAP", "pathological cap only"))
    strength_withheld.extend(strength_cap_extra)
    strength_promoted = [
        _with_rank(item, index) for index, item in enumerate(strength_promoted, start=1)
    ]

    # Weakness / mixed path
    major: list[PrioritizedLesson] = []
    secondary: list[PrioritizedLesson] = []
    withheld: list[PrioritizedLesson] = []
    selected_for_overlap: list[LessonCandidate] = []
    major_lessons: list[LessonCandidate] = []

    ordered = sorted(
        weakness_rows,
        key=lambda row: (-row[1].total(), row[0].concept_id, row[0].id),
    )

    for lesson, factors, codes, cap in ordered:
        action = ctx.actionability_by_lesson_id.get(
            lesson.id, ActionabilityHint.UNKNOWN
        )
        adj_factors = factors
        adj_codes = list(codes)
        overlap_ids: list[str] = []
        worst = OverlapRelation.DISTINCT
        severity = {
            OverlapRelation.DISTINCT: 0,
            OverlapRelation.RELATED: 1,
            OverlapRelation.HIGH_OVERLAP: 2,
            OverlapRelation.DUPLICATIVE: 3,
        }

        for selected in selected_for_overlap:
            rel = overlap_relation(lesson, selected, cfg)
            if rel is OverlapRelation.DISTINCT:
                continue
            if rel is OverlapRelation.RELATED and selected not in major_lessons:
                continue
            penalty = redundancy_penalty_for(rel, cfg)
            adj_factors = adj_factors.with_updates(
                redundancy_penalty=adj_factors.redundancy_penalty + penalty
            )
            overlap_ids.append(selected.id)
            if severity[rel] > severity[worst]:
                worst = rel
            adj_codes.append(
                ReasonCode(
                    "OVERLAPS_HIGHER_VALUE_LESSON",
                    f"{rel.value}:{selected.concept_id}",
                )
            )

        overlap_exclusion: str | None = None
        if worst is OverlapRelation.DUPLICATIVE:
            overlap_exclusion = "DUPLICATE_EVIDENCE"
        elif worst is OverlapRelation.HIGH_OVERLAP:
            overlap_exclusion = "REDUNDANT_WITH_HIGHER_VALUE"

        if overlap_exclusion is not None:
            withheld.append(
                _build_item(
                    lesson,
                    adj_factors,
                    adj_codes,
                    cap,
                    tier=LessonTier.WITHHELD,
                    rank=None,
                    exclusion=overlap_exclusion,
                    overlap_with=tuple(overlap_ids),
                )
            )
            continue

        block = _major_blocked(lesson, adj_factors, cap, cfg, action)
        value = adj_factors.total()

        if block is None:
            major.append(
                _build_item(
                    lesson,
                    adj_factors,
                    adj_codes,
                    cap,
                    tier=LessonTier.MAJOR,
                    rank=None,
                    exclusion=None,
                    overlap_with=tuple(overlap_ids),
                )
            )
            selected_for_overlap.append(lesson)
            major_lessons.append(lesson)
            continue

        # NOT_ACTIONABLE / capability blocks should not linger as secondary coaching.
        hard_withhold = block in {
            "NOT_ACTIONABLE",
            "CAPABILITY_BLOCKED",
            "INSUFFICIENT_SUPPORT",
        }
        if (
            not hard_withhold
            and value >= cfg.secondary_threshold
            and lesson.support_level is not SupportLevel.INSUFFICIENT
        ):
            secondary.append(
                _build_item(
                    lesson,
                    adj_factors,
                    [*adj_codes, ReasonCode(block)],
                    cap,
                    tier=LessonTier.SECONDARY,
                    rank=None,
                    exclusion=None,
                    overlap_with=tuple(overlap_ids),
                )
            )
            selected_for_overlap.append(lesson)
        else:
            reason = block or "LOW_LEARNING_VALUE"
            if lesson.support_level is SupportLevel.INSUFFICIENT:
                reason = "INSUFFICIENT_SUPPORT"
            withheld.append(
                _build_item(
                    lesson,
                    adj_factors,
                    adj_codes,
                    cap,
                    tier=LessonTier.WITHHELD,
                    rank=None,
                    exclusion=reason,
                    overlap_with=tuple(overlap_ids),
                )
            )

    major, major_extra = _apply_safety_cap(major, cfg.max_major_safety_cap)
    if major_extra:
        notes.append(
            ReasonCode("MAJOR_SAFETY_CAP", f"capped at {cfg.max_major_safety_cap}")
        )
        withheld.extend(major_extra)

    secondary, secondary_extra = _apply_safety_cap(
        secondary, cfg.max_secondary_safety_cap
    )
    if secondary_extra:
        withheld.extend(secondary_extra)

    major = [_with_rank(item, index) for index, item in enumerate(major, start=1)]
    secondary = [
        _with_rank(item, index) for index, item in enumerate(secondary, start=1)
    ]

    all_withheld = tuple(
        sorted(
            [*withheld, *strength_withheld],
            key=lambda item: (-item.learning_value, item.concept_id),
        )
    )

    if not major:
        notes.append(ReasonCode("ZERO_MAJOR_VALID", "no lesson cleared major threshold"))

    ranked = tuple(
        sorted(
            [*major, *secondary, *strength_promoted, *all_withheld],
            key=lambda item: (
                0
                if item.tier is LessonTier.MAJOR
                else 1
                if item.tier is LessonTier.SECONDARY
                else 2
                if item.tier is LessonTier.STRENGTH
                else 3,
                item.rank if item.rank is not None else 10_000,
                -item.learning_value,
                item.concept_id,
            ),
        )
    )

    return PrioritizedLessonSet(
        schema_version=PRIORITIZATION_SCHEMA_VERSION,
        match_id=mid,
        participant_id=pid,
        method=PRIORITIZATION_METHOD,
        method_version=PRIORITIZATION_METHOD_VERSION,
        config_version=cfg.version,
        ranked=ranked,
        major=tuple(major),
        secondary=tuple(secondary),
        strengths=tuple(strength_promoted),
        withheld=all_withheld,
        selection_notes=tuple(notes),
        provenance=Provenance(
            producer=PRIORITIZATION_PRODUCER,
            producer_version=PRIORITIZATION_PRODUCER_VERSION,
            upstream=tuple(sorted(lesson.id for lesson in lessons)),
        ),
    )


def explain_lesson_priority(
    result: PrioritizedLessonSet,
    lesson_candidate_id: str,
) -> PrioritizedLesson | None:
    """Return the prioritized row for a lesson id, if present."""
    for item in result.ranked:
        if item.lesson_candidate_id == lesson_candidate_id:
            return item
    return None
