"""Deterministic lesson-candidate redundancy / overlap detection."""

from __future__ import annotations

from collections.abc import Sequence

from riftlens.coaching.concepts.models import LessonCandidate
from riftlens.coaching.prioritization.config import LearningValueConfig
from riftlens.coaching.prioritization.models import OverlapRelation


def _jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    left = set(a)
    right = set(b)
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def concept_domain(concept_id: str) -> str:
    """Return coarse domain prefix (economy, risk, …)."""
    if "." in concept_id:
        return concept_id.split(".", 1)[0]
    return concept_id


def overlap_relation(
    left: LessonCandidate,
    right: LessonCandidate,
    config: LearningValueConfig,
) -> OverlapRelation:
    """Classify evidence overlap. Same domain alone is not DUPLICATIVE."""
    if left.id == right.id:
        return OverlapRelation.DUPLICATIVE

    finding_j = _jaccard(left.finding_ids, right.finding_ids)
    episode_j = _jaccard(left.episode_ids, right.episode_ids)
    combined = max(finding_j, episode_j)

    if combined >= config.duplicative_jaccard:
        return OverlapRelation.DUPLICATIVE
    if combined >= config.high_overlap_jaccard:
        return OverlapRelation.HIGH_OVERLAP

    same_domain = concept_domain(left.concept_id) == concept_domain(right.concept_id)
    if combined >= config.related_jaccard or (
        same_domain and combined >= config.same_domain_related_bonus_jaccard
    ):
        # Independent evidence in same domain stays RELATED, not duplicate.
        if combined < config.related_jaccard and same_domain:
            return OverlapRelation.RELATED
        return OverlapRelation.RELATED
    return OverlapRelation.DISTINCT


def redundancy_penalty_for(
    relation: OverlapRelation,
    config: LearningValueConfig,
) -> float:
    """Return additive penalty for overlapping a higher-value promoted lesson."""
    if relation is OverlapRelation.DUPLICATIVE:
        return config.redundancy_penalty_duplicative
    if relation is OverlapRelation.HIGH_OVERLAP:
        return config.redundancy_penalty_high_overlap
    if relation is OverlapRelation.RELATED:
        return config.redundancy_penalty_related
    return 0.0
