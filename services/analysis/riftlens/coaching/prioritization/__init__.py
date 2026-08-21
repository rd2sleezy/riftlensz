"""C.4 learning-value prioritization over C.3 LessonCandidates."""

from __future__ import annotations

from riftlens.coaching.prioritization.config import (
    DEFAULT_LEARNING_VALUE_CONFIG,
    LearningValueConfig,
    with_config_overrides,
)
from riftlens.coaching.prioritization.models import (
    PRIORITIZATION_METHOD,
    PRIORITIZATION_METHOD_VERSION,
    PRIORITIZATION_SCHEMA_VERSION,
    TEACHING_OUTPUT,
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
from riftlens.coaching.prioritization.prioritizer import (
    explain_lesson_priority,
    prioritize_lesson_candidates,
)
from riftlens.coaching.prioritization.redundancy import (
    concept_domain,
    overlap_relation,
)
from riftlens.coaching.prioritization.scorer import (
    score_lesson_candidate,
    score_lesson_candidates,
)

__all__ = [
    "DEFAULT_LEARNING_VALUE_CONFIG",
    "PRIORITIZATION_METHOD",
    "PRIORITIZATION_METHOD_VERSION",
    "PRIORITIZATION_SCHEMA_VERSION",
    "TEACHING_OUTPUT",
    "ActionabilityHint",
    "LearningValueConfig",
    "LessonTier",
    "OverlapRelation",
    "PrioritizedLesson",
    "PrioritizedLessonSet",
    "PriorityFactors",
    "ReasonCode",
    "ScoringContext",
    "concept_domain",
    "empty_prioritized_set",
    "explain_lesson_priority",
    "overlap_relation",
    "prioritize_lesson_candidates",
    "prioritized_lesson_id",
    "score_lesson_candidate",
    "score_lesson_candidates",
    "with_config_overrides",
]
