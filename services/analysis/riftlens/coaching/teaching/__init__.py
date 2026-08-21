"""C.5 coaching teaching and practice design."""

from __future__ import annotations

from riftlens.coaching.teaching.builder import (
    build_teaching_lesson,
    build_teaching_lessons,
)
from riftlens.coaching.teaching.models import (
    TEACHING_METHOD,
    TEACHING_METHOD_VERSION,
    TEACHING_SCHEMA_VERSION,
    Alternative,
    AlternativeCertainty,
    ConceptPlaybook,
    ContentOrigin,
    DrillKind,
    Measurability,
    MemorableRule,
    PracticeDrill,
    PracticeObjective,
    RecognitionCue,
    TeachingDepth,
    TeachingLesson,
    TeachingLessonSet,
    TeachingReadiness,
    TeachingSpecificity,
    TeachingStatement,
    empty_teaching_set,
    teaching_lesson_id,
)
from riftlens.coaching.teaching.playbooks import (
    BLOCKED_TEACHING_CONCEPTS,
    BLOCKED_WAVE_ACTIONS,
    CONCEPT_PLAYBOOKS,
    all_playbooks,
    get_concept_playbook,
    implemented_playbook_ids,
)
from riftlens.coaching.teaching.readiness import evaluate_teaching_readiness
from riftlens.coaching.teaching.render import (
    render_teaching_lesson,
    render_teaching_lesson_set,
)

__all__ = [
    "BLOCKED_TEACHING_CONCEPTS",
    "BLOCKED_WAVE_ACTIONS",
    "CONCEPT_PLAYBOOKS",
    "TEACHING_METHOD",
    "TEACHING_METHOD_VERSION",
    "TEACHING_SCHEMA_VERSION",
    "Alternative",
    "AlternativeCertainty",
    "ConceptPlaybook",
    "ContentOrigin",
    "DrillKind",
    "Measurability",
    "MemorableRule",
    "PracticeDrill",
    "PracticeObjective",
    "RecognitionCue",
    "TeachingDepth",
    "TeachingLesson",
    "TeachingLessonSet",
    "TeachingReadiness",
    "TeachingSpecificity",
    "TeachingStatement",
    "all_playbooks",
    "build_teaching_lesson",
    "build_teaching_lessons",
    "empty_teaching_set",
    "evaluate_teaching_readiness",
    "get_concept_playbook",
    "implemented_playbook_ids",
    "render_teaching_lesson",
    "render_teaching_lesson_set",
    "teaching_lesson_id",
]
