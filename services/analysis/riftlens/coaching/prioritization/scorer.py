"""Score LessonCandidates into explainable PriorityFactors."""

from __future__ import annotations

from collections.abc import Sequence

from riftlens.coaching.concepts.catalog import concept_for
from riftlens.coaching.concepts.models import (
    CapabilityStatus,
    ConceptSpecificity,
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
    ActionabilityHint,
    PriorityFactors,
    ReasonCode,
    ScoringContext,
)


def _support_score(level: SupportLevel, config: LearningValueConfig) -> float:
    return {
        SupportLevel.STRONG: config.support_strong,
        SupportLevel.MODERATE: config.support_moderate,
        SupportLevel.WEAK: config.support_weak,
        SupportLevel.INSUFFICIENT: config.support_insufficient,
    }[level]


def _specificity_score(
    lesson: LessonCandidate,
    config: LearningValueConfig,
) -> tuple[float, list[ReasonCode]]:
    codes: list[ReasonCode] = []
    base = {
        ConceptSpecificity.SPECIFIC: config.specificity_specific,
        ConceptSpecificity.GENERAL: config.specificity_general,
        ConceptSpecificity.BROAD: config.specificity_broad,
        ConceptSpecificity.UNRESOLVED: config.specificity_unresolved,
    }[lesson.specificity]
    if lesson.specificity is ConceptSpecificity.GENERAL:
        codes.append(ReasonCode("GENERAL_CONCEPT", "preferred when well supported"))
    if lesson.specificity is ConceptSpecificity.BROAD:
        codes.append(ReasonCode("BROAD_CONCEPT"))
    if lesson.specificity is ConceptSpecificity.UNRESOLVED:
        codes.append(ReasonCode("TOO_BROAD", "unresolved specificity"))
    if lesson.specificity is ConceptSpecificity.SPECIFIC and lesson.support_level in {
        SupportLevel.WEAK,
        SupportLevel.INSUFFICIENT,
    }:
        base += config.unsupported_specificity_penalty
        codes.append(ReasonCode("UNSAFE_SPECIFICITY", "specific without support"))
    return base, codes


def _capability_status(concept_id: str) -> CapabilityStatus:
    concept = concept_for(concept_id)
    if concept is None:
        return CapabilityStatus.UNKNOWN
    return concept.capability_status


def _capability_score(
    status: CapabilityStatus,
    config: LearningValueConfig,
) -> tuple[float, list[ReasonCode]]:
    if status is CapabilityStatus.BLOCKED:
        return config.capability_blocked_penalty, [
            ReasonCode("CAPABILITY_LIMITED", "concept capability BLOCKED")
        ]
    if status is CapabilityStatus.PARTIAL:
        return config.capability_partial_bonus, []
    if status is CapabilityStatus.READY:
        return config.capability_ready_bonus, []
    return config.capability_unknown_penalty, [ReasonCode("CAPABILITY_UNKNOWN")]


def _material_gaps(gaps: Sequence[str], config: LearningValueConfig) -> list[str]:
    tokens = set(config.material_gap_tokens)
    return [gap for gap in gaps if gap in tokens or gap.startswith("true_")]


def score_lesson_candidate(
    lesson: LessonCandidate,
    *,
    config: LearningValueConfig | None = None,
    context: ScoringContext | None = None,
) -> tuple[PriorityFactors, tuple[ReasonCode, ...], CapabilityStatus]:
    """Compute provisional learning-value factors for one LessonCandidate.

    Does not assign tier/rank. Priority value ≠ Finding confidence ≠ decision quality.
    """
    cfg = config or DEFAULT_LEARNING_VALUE_CONFIG
    ctx = context or ScoringContext()
    codes: list[ReasonCode] = []

    evidence = _support_score(lesson.support_level, cfg)
    if lesson.support_level is SupportLevel.STRONG:
        codes.append(ReasonCode("STRONG_MULTI_EPISODE_SUPPORT"))
    elif lesson.support_level is SupportLevel.MODERATE:
        codes.append(ReasonCode("MODERATE_SUPPORT"))
    elif lesson.support_level is SupportLevel.WEAK:
        codes.append(ReasonCode("WEAK_EVIDENCE"))
    else:
        codes.append(ReasonCode("INSUFFICIENT_SUPPORT"))

    # Recurrence: prefer distinct episodes when configured.
    if cfg.recurrence_use_episode_count and lesson.episode_ids:
        occ = max(len(set(lesson.episode_ids)), 1)
    else:
        occ = max(int(lesson.within_match_occurrences), 1)
    # occurrences beyond 1 contribute
    recurrence = min(cfg.recurrence_cap, max(0, occ - 1) * cfg.recurrence_per_occurrence)
    if occ >= 2:
        codes.append(ReasonCode("REPEATED_WITHIN_MATCH", f"occurrences={occ}"))

    raw_impact = float(
        ctx.impact_by_lesson_id.get(lesson.id, cfg.default_impact)
    )
    impact = min(cfg.impact_cap, max(0.0, raw_impact) * cfg.impact_weight)
    if impact >= cfg.impact_cap * 0.75:
        codes.append(ReasonCode("HIGH_IMPACT", f"raw={raw_impact}"))

    plausible = int(ctx.causal_plausible_by_lesson_id.get(lesson.id, 0))
    supported = int(ctx.causal_supported_by_lesson_id.get(lesson.id, 0))
    causal = min(cfg.causal_plausible_cap, plausible * cfg.causal_plausible_bonus) + min(
        cfg.causal_supported_cap, supported * cfg.causal_supported_bonus
    )
    if plausible:
        codes.append(ReasonCode("PLAUSIBLE_CAUSAL_PRIOR", f"count={plausible}"))
    if supported:
        codes.append(ReasonCode("SUPPORTED_CAUSAL_LEVERAGE", f"count={supported}"))

    action_hint = ctx.actionability_by_lesson_id.get(
        lesson.id, ActionabilityHint.UNKNOWN
    )
    actionability = 0.0
    if action_hint is ActionabilityHint.NOT_ACTIONABLE:
        actionability = cfg.not_actionable_penalty
        codes.append(ReasonCode("NOT_ACTIONABLE"))
    # UNKNOWN / ACTIONABLE → no bonus (do not manufacture controllability)

    teach = float(
        ctx.teachability_by_concept.get(lesson.concept_id, cfg.default_teachability)
    )
    teach = min(1.0, max(0.0, teach))
    teachability = teach * cfg.teachability_weight
    if teach >= 0.8:
        codes.append(ReasonCode("HIGH_TEACHABILITY", f"teachability={teach}"))

    spec_score, spec_codes = _specificity_score(lesson, cfg)
    codes.extend(spec_codes)

    cap_status = _capability_status(lesson.concept_id)
    cap_score, cap_codes = _capability_score(cap_status, cfg)
    codes.extend(cap_codes)
    if lesson.readiness is LessonReadiness.BLOCKED:
        cap_score = min(cap_score, cfg.capability_blocked_penalty)
        codes.append(ReasonCode("CAPABILITY_BLOCKED", "lesson readiness BLOCKED"))

    conflict = 0.0
    if lesson.polarity is LessonPolarity.MIXED or lesson.conflicting_evidence:
        conflict = cfg.conflict_mixed_penalty
        codes.append(ReasonCode("MIXED_SIGNALS"))

    material = _material_gaps(lesson.context_gaps, cfg)
    gap = max(cfg.gap_penalty_cap, -len(material) * abs(cfg.gap_penalty_per_item))
    if material:
        codes.append(ReasonCode("MATERIAL_CONTEXT_GAPS", ",".join(material[:4])))

    resolution = 0.0
    if lesson.condition_resolution_notes:
        resolution = cfg.resolution_penalty
        codes.append(ReasonCode("RAPIDLY_RESOLVED", "persistence reduced"))

    role_raw = float(
        ctx.role_relevance_by_concept.get(
            lesson.concept_id, cfg.default_role_relevance
        )
    )
    role = role_raw * cfg.role_relevance_weight
    if role_raw > 0:
        codes.append(ReasonCode("ROLE_RELEVANT", f"role_factor={role_raw}"))

    rank_raw = float(
        ctx.rank_relevance_by_concept.get(
            lesson.concept_id, cfg.default_rank_relevance
        )
    )
    rank_raw = min(1.5, max(0.0, rank_raw))
    # Convert 1.0 baseline to contribution around weight * (rank_raw - 0.5)*2 roughly
    # Simpler: contribution = (rank_raw - 1.0) * weight  so default 1.0 → 0
    rank_rel = (rank_raw - 1.0) * cfg.rank_relevance_weight
    if abs(rank_raw - 1.0) > 0.05:
        codes.append(ReasonCode("RANK_RELEVANT", f"rank_factor={rank_raw}"))

    # Cross-game seams must stay unused in C.4
    if ctx.cross_game_recurrence or ctx.active_focus or ctx.trend_by_concept:
        codes.append(
            ReasonCode(
                "C6_SEAMS_IGNORED",
                "cross-game history inputs are reserved for C.6",
            )
        )

    factors = PriorityFactors(
        evidence_support=evidence,
        within_match_recurrence=recurrence,
        impact=impact,
        causal_leverage=causal,
        actionability=actionability,
        teachability=teachability,
        specificity=spec_score,
        capability_readiness=cap_score,
        conflict_penalty=conflict,
        gap_penalty=gap,
        resolution_penalty=resolution,
        redundancy_penalty=0.0,
        role_relevance=role,
        rank_relevance=rank_rel,
    )
    return factors, tuple(codes), cap_status


def score_lesson_candidates(
    lessons: Sequence[LessonCandidate],
    *,
    config: LearningValueConfig | None = None,
    context: ScoringContext | None = None,
) -> list[tuple[LessonCandidate, PriorityFactors, tuple[ReasonCode, ...], CapabilityStatus]]:
    """Score all candidates. Empty input → []. Deterministic order by lesson id."""
    if not lessons:
        return []
    rows = [
        (lesson, *score_lesson_candidate(lesson, config=config, context=context))
        for lesson in lessons
    ]
    rows.sort(key=lambda item: (-item[1].total(), item[0].concept_id, item[0].id))
    return rows
