"""Behaviorally anchored C.7 quality rubric."""

from __future__ import annotations

from dataclasses import dataclass

from riftlens.coaching.evaluation.models import RubricDimension, RubricScore

ORDINAL_SCORES = (
    RubricScore.FAIL,
    RubricScore.POOR,
    RubricScore.ACCEPTABLE,
    RubricScore.GOOD,
    RubricScore.EXCELLENT,
)


@dataclass(frozen=True)
class RubricAnchor:
    dimension: RubricDimension
    title: str
    anchors: dict[str, str]
    applies_to_levels: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "dimension": self.dimension.value,
            "title": self.title,
            "anchors": dict(self.anchors),
            "applies_to_levels": list(self.applies_to_levels),
        }


def _anchors(
    fail: str, poor: str, acceptable: str, good: str, excellent: str
) -> dict[str, str]:
    return {
        RubricScore.FAIL.value: fail,
        RubricScore.POOR.value: poor,
        RubricScore.ACCEPTABLE.value: acceptable,
        RubricScore.GOOD.value: good,
        RubricScore.EXCELLENT.value: excellent,
    }


RUBRIC_DEFINITIONS: tuple[RubricAnchor, ...] = (
    RubricAnchor(
        RubricDimension.Q1_FACTUAL_GROUNDING,
        "Factual grounding",
        _anchors(
            "Claims match facts unsupported by available evidence",
            "Mostly grounded but mixes in unsupported details",
            "Core claims supported; minor unsupported color",
            "Claims clearly tied to evidence",
            "Precise, evidence-bound claims with clear limits",
        ),
    ),
    RubricAnchor(
        RubricDimension.Q2_EPISTEMIC_CALIBRATION,
        "Epistemic calibration",
        _anchors(
            "Presents unknowns as facts",
            "Often overconfident relative to evidence",
            "Usually marks uncertainty, occasional slips",
            "Consistently distinguishes fact/inference/unknown",
            "Exemplary uncertainty discipline",
        ),
    ),
    RubricAnchor(
        RubricDimension.Q3_CONCEPT_CORRECTNESS,
        "Concept correctness",
        _anchors(
            "Wrong coaching concept for the situation",
            "Related but misleading concept",
            "Plausible concept, not clearly best framing",
            "Appropriate concept a coach would recognize",
            "Best available concept framing for the evidence",
        ),
    ),
    RubricAnchor(
        RubricDimension.Q4_CAUSAL_DISCIPLINE,
        "Causal discipline",
        _anchors(
            "States definite causation without support",
            "Implies causation beyond evidence",
            "Mostly careful; mild overreach",
            "Causal claims match support level",
            "Explicitly refuses unsupported causal stories",
        ),
    ),
    RubricAnchor(
        RubricDimension.Q5_PRIORITY_QUALITY,
        "Priority quality",
        _anchors(
            "Focuses on irrelevant/unsupported issue",
            "Valid issue but misses much more important problem",
            "Reasonable topic; uncertain if best priority",
            "Strong priority a knowledgeable coach would likely select",
            "Highest-leverage lesson; appropriately suppresses distractions",
        ),
    ),
    RubricAnchor(
        RubricDimension.Q6_NON_REDUNDANCY,
        "Non-redundancy",
        _anchors(
            "Same lesson repeated as multiple symptoms",
            "Heavy overlap with little new information",
            "Some redundancy but still usable",
            "Clean consolidation of related signals",
            "Minimal overlap; each item earns its place",
        ),
    ),
    RubricAnchor(
        RubricDimension.Q7_RELEVANCE_SPECIFICITY,
        "Relevance / specificity",
        _anchors(
            "Generic advice disconnected from the case",
            "Vague relative to available evidence",
            "Adequately specific without overclaiming",
            "Specific and useful within evidence limits",
            "Highly specific without exceeding evidence",
        ),
    ),
    RubricAnchor(
        RubricDimension.Q8_ACTIONABILITY,
        "Actionability",
        _anchors(
            "Player cannot act on the coaching",
            "Action is unclear or unrealistic",
            "Actionable with effort / interpretation",
            "Clear next-game action",
            "Immediately usable deliberate-practice action",
        ),
    ),
    RubricAnchor(
        RubricDimension.Q9_RECOGNITION_CUE_QUALITY,
        "Recognition cue quality",
        _anchors(
            "Cue is wrong or unusable",
            "Cue exists but unlikely to help recognition",
            "Cue is okay; may help sometimes",
            "Cue would help recognize the situation",
            "Excellent pre-repeat recognition trigger",
        ),
    ),
    RubricAnchor(
        RubricDimension.Q10_ALTERNATIVE_QUALITY,
        "Alternative quality",
        _anchors(
            "Alternative contradicts evidence or invents certainty",
            "Weak/misleading alternative",
            "Acceptable alternative at claimed certainty",
            "Strategically reasonable alternative",
            "Strong alternative with honest certainty limits",
        ),
    ),
    RubricAnchor(
        RubricDimension.Q11_DRILL_QUALITY,
        "Drill quality",
        _anchors(
            "Drill trains the wrong behavior or is impossible",
            "Weak drill; little training value",
            "Adequate practice suggestion",
            "Useful drill for the target behavior",
            "High-leverage deliberate-practice drill",
        ),
    ),
    RubricAnchor(
        RubricDimension.Q12_OBJECTIVE_QUALITY,
        "Objective quality",
        _anchors(
            "Outcome/win-based or unmeasurable as if measurable",
            "Process claim but poorly defined",
            "Process-based with limited measurability",
            "Clear process objective with measurable success",
            "Excellent process metric + opportunity awareness",
        ),
    ),
    RubricAnchor(
        RubricDimension.Q13_COGNITIVE_LOAD,
        "Cognitive load",
        _anchors(
            "Overloaded / many simultaneous focuses",
            "Too much for one review",
            "Acceptable load",
            "Focused, manageable coaching set",
            "Ideal focus for deliberate practice",
        ),
    ),
    RubricAnchor(
        RubricDimension.Q14_LONGITUDINAL_QUALITY,
        "Longitudinal quality",
        _anchors(
            "False success / flapping / opportunity ignored",
            "Weak longitudinal reasoning",
            "Mostly reasonable keep/switch logic",
            "Sound continuity and opportunity awareness",
            "Excellent multi-game curriculum logic",
        ),
        applies_to_levels=("LEVEL_5_LONGITUDINAL", "LEVEL_6_END_TO_END"),
    ),
    RubricAnchor(
        RubricDimension.Q15_OVERALL_COACHING_VALUE,
        "Overall coaching value",
        _anchors(
            "Not useful / harmful if trusted",
            "Limited usefulness",
            "Somewhat useful",
            "Genuinely useful to the player",
            "High-value coaching a strong coach would endorse",
        ),
    ),
    RubricAnchor(
        RubricDimension.LANGUAGE_CLARITY,
        "Language clarity (presentation only)",
        _anchors(
            "Unintelligible",
            "Hard to parse",
            "Understandable",
            "Clear",
            "Exceptionally clear",
        ),
    ),
)


def get_rubric_definitions() -> tuple[RubricAnchor, ...]:
    return RUBRIC_DEFINITIONS


def is_valid_rubric_score(score: RubricScore) -> bool:
    return score in (*ORDINAL_SCORES, RubricScore.NA, RubricScore.UNJUDGEABLE)


def ordinal_value(score: RubricScore) -> int | None:
    if score in {RubricScore.NA, RubricScore.UNJUDGEABLE}:
        return None
    return int(score.value[0])
