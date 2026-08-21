"""Normalize production H.8 and C.x outputs into a common evaluation view."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from riftlens.coaching.evaluation.models import NormalizedCoachingView


def normalize_production_baseline(
    items: Sequence[Mapping[str, Any]] | None = None,
    *,
    system_id: str = "production_h8",
    focus_items: Sequence[Mapping[str, Any]] | None = None,
    secondary_items: Sequence[Mapping[str, Any]] | None = None,
    strengths: Sequence[Mapping[str, Any]] | None = None,
) -> NormalizedCoachingView:
    """Normalize H.8/H.11 CoachingItem-like dicts. Missing fields stay missing."""
    focus = list(focus_items or ())
    secondary = list(secondary_items or ())
    strength_items = list(strengths or ())
    all_items = list(items or ()) or focus + secondary + strength_items

    concepts = tuple(
        str(item.get("root_concept_id") or item.get("concept_id") or "")
        for item in all_items
        if item.get("root_concept_id") or item.get("concept_id")
    )
    primary = focus[0] if focus else (all_items[0] if all_items else {})
    return NormalizedCoachingView(
        system_id=system_id,
        observation=None,
        lesson=str(primary.get("title") or primary.get("the_fix") or "") or None,
        why=str(primary.get("body") or "") or None,
        alternative=None,  # production often lacks structured alternative
        cue=None,
        drill=str(primary.get("next_game_check") or "") or None,
        objective=None,
        limitations=("missing_structured_teaching_fields",)
        if primary
        else ("empty_baseline",),
        concept_ids=tuple(c for c in concepts if c),
        major_count=len(focus) if focus else min(3, len(all_items)),
        decision_quality=None,
        causal_status=None,
        player_knowledge=None,
        language_text=str(primary.get("body") or primary.get("title") or "") or None,
        structural={
            "focus_count": len(focus),
            "secondary_count": len(secondary),
            "strength_count": len(strength_items),
            "item_ids": [str(item.get("id", "")) for item in all_items],
        },
    )


def normalize_cx_candidate(
    payload: Mapping[str, Any],
    *,
    system_id: str = "cx_candidate",
) -> NormalizedCoachingView:
    """Normalize structured C.1–C.6 evaluation payload.

    Expected keys (all optional): observation, lesson, why, alternative, cue,
    drill, objective, limitations, concept_ids, major_count, decision_quality,
    causal_status, player_knowledge, capability_statuses, longitudinal_status,
    opportunity_status, objective_result, measurability, language_text, structural.
    """
    caps = payload.get("capability_statuses") or {}
    if not isinstance(caps, dict):
        caps = {}
    concepts_raw = payload.get("concept_ids") or ()
    concepts = tuple(str(item) for item in concepts_raw)
    limitations_raw = payload.get("limitations") or ()
    limitations = tuple(str(item) for item in limitations_raw)
    structural = payload.get("structural") or {}
    if not isinstance(structural, dict):
        structural = {}

    return NormalizedCoachingView(
        system_id=system_id,
        observation=_opt_str(payload.get("observation")),
        lesson=_opt_str(payload.get("lesson")),
        why=_opt_str(payload.get("why")),
        alternative=_opt_str(payload.get("alternative")),
        cue=_opt_str(payload.get("cue")),
        drill=_opt_str(payload.get("drill")),
        objective=_opt_str(payload.get("objective")),
        limitations=limitations,
        concept_ids=concepts,
        major_count=int(payload.get("major_count") or 0),
        decision_quality=_opt_str(payload.get("decision_quality")),
        causal_status=_opt_str(payload.get("causal_status")),
        player_knowledge=_opt_str(payload.get("player_knowledge")),
        capability_statuses={str(k): str(v) for k, v in caps.items()},
        longitudinal_status=_opt_str(payload.get("longitudinal_status")),
        opportunity_status=_opt_str(payload.get("opportunity_status")),
        objective_result=_opt_str(payload.get("objective_result")),
        measurability=_opt_str(payload.get("measurability")),
        language_text=_opt_str(payload.get("language_text")),
        structural=dict(structural),
    )


def normalize_reference_manual(
    payload: Mapping[str, Any],
    *,
    system_id: str = "manual_reference",
) -> NormalizedCoachingView:
    """Normalize manually entered external reference coaching."""
    return NormalizedCoachingView(
        system_id=system_id,
        observation=_opt_str(payload.get("observation")),
        lesson=_opt_str(payload.get("primary_lesson") or payload.get("lesson")),
        why=_opt_str(payload.get("why")),
        alternative=_opt_str(payload.get("alternative")),
        cue=_opt_str(payload.get("cue")),
        drill=_opt_str(payload.get("drill")),
        objective=_opt_str(payload.get("objective")),
        limitations=tuple(str(item) for item in payload.get("limitations") or ()),
        concept_ids=tuple(str(item) for item in payload.get("concept_ids") or ()),
        structural={"provenance": "manual_entry"},
    )


def _opt_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
