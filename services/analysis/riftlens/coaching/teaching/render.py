"""Deterministic debug renderer for TeachingLesson (not production UI)."""

from __future__ import annotations

from riftlens.coaching.teaching.models import TeachingLesson, TeachingLessonSet


def render_teaching_lesson(lesson: TeachingLesson) -> str:
    """Render a concise debug/reference text block for tests."""
    lines = [
        f"[{lesson.tier}] {lesson.concept_id} (depth={lesson.teaching_depth.value})",
        f"specificity={lesson.teaching_specificity.value}",
    ]
    for stmt in lesson.evidence_summary:
        lines.append(f"EVIDENCE ({stmt.origin.value}): {stmt.text}")
    if lesson.concept_explanation:
        lines.append(
            f"EXPLAIN ({lesson.concept_explanation.origin.value}): "
            f"{lesson.concept_explanation.text}"
        )
    if lesson.why_it_matters:
        lines.append(
            f"WHY ({lesson.why_it_matters.origin.value}): {lesson.why_it_matters.text}"
        )
    if lesson.alternative:
        lines.append(
            f"ALT ({lesson.alternative.certainty.value}): {lesson.alternative.action}"
        )
    if lesson.recognition_cue:
        lines.append(
            f"CUE: WHEN {lesson.recognition_cue.trigger} "
            f"THEN {lesson.recognition_cue.intended_check}"
        )
    if lesson.memorable_rule:
        lines.append(f"RULE: {lesson.memorable_rule.to_dict()['compact']}")
    if lesson.drill:
        lines.append(f"DRILL ({lesson.drill.kind.value}): {lesson.drill.instruction}")
    if lesson.objective:
        lines.append(
            f"OBJECTIVE ({lesson.objective.measurability.value}): "
            f"{lesson.objective.target_behavior}"
        )
    if lesson.limitations:
        lines.append("LIMITS: " + "; ".join(lesson.limitations))
    return "\n".join(lines)


def render_teaching_lesson_set(result: TeachingLessonSet) -> str:
    """Render all lessons in a set for golden/debug inspection."""
    if not result.lessons:
        return "NO_TEACHING_LESSONS"
    return "\n\n".join(render_teaching_lesson(item) for item in result.lessons)
