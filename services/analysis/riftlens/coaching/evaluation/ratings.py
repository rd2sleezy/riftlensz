"""Human rating import/validation and benchmark reporting."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from riftlens.coaching.evaluation.models import (
    EvaluatorExpertise,
    HardFailKind,
    HumanEvaluation,
    PairwisePreference,
    RubricDimension,
    RubricRating,
    RubricScore,
)
from riftlens.coaching.evaluation.rubric import is_valid_rubric_score


def parse_human_evaluation(payload: Mapping[str, Any]) -> HumanEvaluation:
    """Parse a single human evaluation from JSON-compatible dict."""
    scores: list[RubricRating] = []
    for item in payload.get("rubric_scores") or ():
        dim = RubricDimension(str(item["dimension"]))
        score = RubricScore(str(item["score"]))
        if not is_valid_rubric_score(score):
            raise ValueError(f"Invalid rubric score: {score}")
        scores.append(
            RubricRating(dimension=dim, score=score, note=str(item.get("note", "")))
        )
    hard_fails = tuple(
        HardFailKind(str(item)) for item in payload.get("hard_fail_flags") or ()
    )
    if hard_fails and not any(
        rating.note or payload.get("notes") for rating in scores
    ):
        # Require reason when hard fail — notes or per-score note
        if not str(payload.get("notes") or "").strip():
            raise ValueError("hard_fail_flags require notes explaining the failure")

    pairwise = None
    if payload.get("pairwise"):
        pairwise = PairwisePreference(str(payload["pairwise"]))

    return HumanEvaluation(
        evaluator_id=str(payload["evaluator_id"]),
        expertise=EvaluatorExpertise(str(payload.get("expertise", "PLAYER"))),
        case_id=str(payload["case_id"]),
        system_label_shown=str(payload.get("system_label_shown", "A")),
        evaluated_at_ms=int(payload.get("evaluated_at_ms", 0)),
        rubric_scores=tuple(scores),
        hard_fail_flags=hard_fails,
        pairwise=pairwise,
        pairwise_question=str(payload["pairwise_question"])
        if payload.get("pairwise_question")
        else None,
        confidence=float(payload.get("confidence", 0.5)),
        notes=str(payload.get("notes", "")),
        unjudgeable_reasons=tuple(
            str(item) for item in payload.get("unjudgeable_reasons") or ()
        ),
        adjudication_of=tuple(
            str(item) for item in payload.get("adjudication_of") or ()
        ),
    )


def ingest_human_evaluations(
    payloads: Sequence[Mapping[str, Any]],
) -> tuple[HumanEvaluation, ...]:
    return tuple(parse_human_evaluation(item) for item in payloads)


def load_human_evaluations_json(path: Path | str) -> tuple[HumanEvaluation, ...]:
    """Load ratings from a JSON file (list or {evaluations: [...]})."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        rows = data.get("evaluations") or data.get("ratings") or []
    else:
        rows = data
    if not isinstance(rows, list):
        raise ValueError("Expected list of evaluations")
    return ingest_human_evaluations(rows)


def rating_template() -> dict[str, Any]:
    """Serializable template for human evaluators (no UI required)."""
    return {
        "evaluator_id": "anon_001",
        "expertise": "COACH",
        "case_id": "c7_economy_reset",
        "system_label_shown": "A",
        "evaluated_at_ms": 0,
        "rubric_scores": [
            {
                "dimension": "Q1_FACTUAL_GROUNDING",
                "score": "N/A",
                "note": "",
            }
        ],
        "hard_fail_flags": [],
        "pairwise": "UNJUDGEABLE",
        "pairwise_question": "Which gives more useful coaching?",
        "confidence": 0.5,
        "notes": "",
        "unjudgeable_reasons": [],
    }
