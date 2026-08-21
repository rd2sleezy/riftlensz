"""Blinded evaluation packet generation."""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping, Sequence

from riftlens.coaching.evaluation.models import (
    BlindMapping,
    CoachingBenchmarkCase,
    EvaluationPacket,
    NormalizedCoachingView,
)
from riftlens.coaching.evaluation.rubric import get_rubric_definitions

DEFAULT_INSTRUCTIONS = (
    "Compare System A and System B for the same match/situation. "
    "Score only dimensions that apply; use N/A or UNJUDGEABLE when evidence is "
    "insufficient. Do not guess. Coaching logic matters more than fluent prose."
)

DEFAULT_PAIRWISE_QUESTIONS = (
    "Which identifies the better lesson?",
    "Which gives more useful coaching?",
    "Which would you rather give the player?",
    "Which better respects uncertainty?",
)


def _stable_swap(seed: int, case_id: str) -> bool:
    digest = hashlib.sha256(f"{seed}:{case_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 2 == 1


def build_evaluation_packet(
    case: CoachingBenchmarkCase,
    system_left: NormalizedCoachingView,
    system_right: NormalizedCoachingView,
    *,
    seed: int = 7,
    blind: bool = True,
    instructions: str = DEFAULT_INSTRUCTIONS,
) -> EvaluationPacket:
    """Build a blinded comparison packet. Mapping stored separately from export."""
    swap = _stable_swap(seed, case.case_id) if blind else False
    a_view, b_view = (system_right, system_left) if swap else (system_left, system_right)
    mapping = BlindMapping(
        seed=seed,
        case_id=case.case_id,
        label_a_system_id=a_view.system_id,
        label_b_system_id=b_view.system_id,
    )
    # Evaluator context: case facts only — no gold references
    context = {
        "match_ref": case.match_ref,
        "role": case.role,
        "champion": case.champion,
        "domains": list(case.domains),
        "tags": list(case.tags),
        "system_input": dict(case.system_input),
        "levels": [item.value for item in case.evaluation_levels],
    }
    rubric_dims = tuple(item.dimension.value for item in get_rubric_definitions())
    packet_id = f"pkt_{case.case_id}_{seed}"
    return EvaluationPacket(
        packet_id=packet_id,
        case_id=case.case_id,
        instructions=instructions,
        context_for_evaluator=context,
        system_a=_view_for_packet(a_view, blind=blind),
        system_b=_view_for_packet(b_view, blind=blind),
        rubric_dimensions=rubric_dims,
        pairwise_questions=DEFAULT_PAIRWISE_QUESTIONS,
        blind=blind,
        seed=seed,
        mapping=mapping,
    )


def _view_for_packet(view: NormalizedCoachingView, *, blind: bool) -> dict[str, object]:
    data = view.to_dict()
    if blind:
        data["system_id"] = "REDACTED"
        # Strip implementation hints from structural
        structural = dict(data.get("structural") or {})
        for key in list(structural):
            if "version" in key.lower() or "producer" in key.lower():
                structural.pop(key, None)
        data["structural"] = structural
    return data


def recover_systems_from_mapping(
    mapping: BlindMapping,
    label: str,
) -> str:
    """Map evaluator label A/B back to original system id."""
    if label.upper() in {"A", "SYSTEM_A"}:
        return mapping.label_a_system_id
    if label.upper() in {"B", "SYSTEM_B"}:
        return mapping.label_b_system_id
    raise KeyError(f"Unknown label: {label}")


def shuffle_packet_order(
    packets: Sequence[EvaluationPacket],
    *,
    seed: int,
) -> tuple[EvaluationPacket, ...]:
    """Deterministic packet presentation order."""
    items = list(packets)
    rng = random.Random(seed)
    rng.shuffle(items)
    return tuple(items)


def assert_no_gold_leakage(
    system_input: Mapping[str, object],
    case: CoachingBenchmarkCase,
) -> None:
    """Architectural guard: gold must not appear in system-facing payload."""
    payload = case.system_facing_payload()
    if "evaluator_only" in payload or "human_references" in payload:
        raise AssertionError("Gold leaked into system-facing payload")
    if case.evaluator_only_notes and case.evaluator_only_notes in str(system_input):
        raise AssertionError("Evaluator notes leaked into system input")
