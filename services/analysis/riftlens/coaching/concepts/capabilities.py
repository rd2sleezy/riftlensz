"""Reference capability readiness catalog for C.3.

External coaching products are benchmark references only — not runtime deps.
Statuses are verified against current GST/C.1/C.2 evidence realities.
"""

from __future__ import annotations

from riftlens.coaching.concepts.models import (
    CapabilityStatus,
    CoachingCapability,
    ReasonCode,
)

_RC = ReasonCode


def _cap(
    cap_id: str,
    domain: str,
    desired: str,
    required: tuple[str, ...],
    available: tuple[str, ...],
    missing: tuple[str, ...],
    unsafe: tuple[str, ...],
    readiness: CapabilityStatus,
    reasons: tuple[ReasonCode, ...],
    *,
    can_mimic: bool,
    future: str,
    notes: str = "",
) -> CoachingCapability:
    return CoachingCapability(
        id=cap_id,
        domain=domain,
        desired_output=desired,
        required_evidence=required,
        available_evidence=available,
        missing_evidence=missing,
        unsafe_assumptions=unsafe,
        readiness=readiness,
        reason_codes=reasons,
        can_safely_mimic=can_mimic,
        future_upstream=future,
        notes=notes,
    )


COACHING_CAPABILITIES: dict[str, CoachingCapability] = {
    "CAP-WAVE-STATE": _cap(
        "CAP-WAVE-STATE",
        "LANING",
        "Classify current wave state (freeze/slow-push/fast-push/crash/hold/bounce).",
        (
            "lane_minion_counts",
            "minion_hp",
            "wave_position",
            "wave_direction",
            "subject_and_opponent_lane_presence",
        ),
        ("cs_snapshots_60s", "coarse_position_frames"),
        (
            "lane_minion_counts",
            "minion_hp",
            "wave_position",
            "wave_direction",
            "exact_lane_minion_state",
        ),
        (
            "CS_SNAPSHOT_IS_WAVE_STATE",
            "POSITION_SAMPLE_IS_MINION_STATE",
        ),
        CapabilityStatus.BLOCKED,
        (_RC("WAVE_STATE_REQUIRES_MINION_LEVEL_EVIDENCE"),),
        can_mimic=False,
        future="minion-level timeline or equivalent wave facts in GST",
        notes="A related rule existing (e.g. CS collapse) does not make this READY.",
    ),
    "CAP-WAVE-ACTION": _cap(
        "CAP-WAVE-ACTION",
        "LANING",
        "Recommend freeze / slow push / hard push / crash / hold / bounce.",
        (
            "CAP-WAVE-STATE",
            "strategic_context_objectives_recalls_threats",
        ),
        (),
        (
            "CAP-WAVE-STATE",
            "minion_state",
            "wave_direction",
            "counterfactual_wave_outcomes",
        ),
        ("INFER_WAVE_ACTION_FROM_CS_OR_DEATH",),
        CapabilityStatus.BLOCKED,
        (_RC("WAVE_ACTION_BLOCKED_WITHOUT_WAVE_STATE"),),
        can_mimic=False,
        future="wave-state facts plus strategic context model",
    ),
    "CAP-RESET": _cap(
        "CAP-RESET",
        "ECONOMY",
        "Evaluate reset/resource timing quality.",
        ("unspent_gold", "purchase_events", "hp", "time", "optional_fight_objective_context"),
        ("unspent_gold_estimation", "purchase_events", "hp_snapshots", "time_ms", "C1_resolution"),
        ("full_strategic_context", "player_intent", "wave_state_for_recall_after_crash"),
        ("RESOLVED_CONDITION_MEANS_GOOD_DECISION",),
        CapabilityStatus.PARTIAL,
        (_RC("RESET_PARTIAL_FROM_GOLD_HP_PURCHASE"),),
        can_mimic=True,
        future="richer lane/wave context around recall windows",
        notes="Can signal resource/reset concepts; cannot prove decision GOOD/POOR.",
    ),
    "CAP-FIGHT-SELECTION": _cap(
        "CAP-FIGHT-SELECTION",
        "COMBAT",
        "Evaluate whether taking a fight was correct.",
        (
            "fight_windows",
            "player_visible_information",
            "enemy_threat_state",
            "decision_evidence_contract",
        ),
        ("fight_participation_windows", "coarse_positions", "C2_decision_UNKNOWN"),
        ("true_fog", "player_vision", "defensible_decision_contract"),
        ("NEGATIVE_RULE_EQUALS_POOR_FIGHT_DECISION",),
        CapabilityStatus.BLOCKED,
        (_RC("FIGHT_SELECTION_BLOCKED_DECISION_UNKNOWN"),),
        can_mimic=False,
        future="player-knowledge evidence and decision contracts",
    ),
    "CAP-OBJECTIVE-PRESENCE": _cap(
        "CAP-OBJECTIVE-PRESENCE",
        "OBJECTIVE",
        "Evaluate objective attendance/presence (narrow).",
        ("objective_events", "subject_position_near_window"),
        ("objective_events", "coarse_position", "R-008_predicate"),
        ("full_macro_trade_evaluation", "cross_map_value_model"),
        ("NO_SHOW_EQUALS_BAD_MACRO_DECISION",),
        CapabilityStatus.PARTIAL,
        (_RC("OBJECTIVE_PRESENCE_PARTIAL_NARROW"),),
        can_mimic=True,
        future="macro trade / cross-map valuation",
        notes="READY only for narrow presence questions, not full macro correctness.",
    ),
    "CAP-VISION-QUALITY": _cap(
        "CAP-VISION-QUALITY",
        "VISION",
        "Evaluate ward placement quality and actual coverage.",
        ("ward_positions", "ward_type", "fog_regions", "entrance_coverage"),
        ("ward_placed_or_killed_events_without_position",),
        ("ward_positions", "fog_regions", "coverage_geometry"),
        ("WARD_EVENT_EQUALS_COVERAGE_QUALITY",),
        CapabilityStatus.BLOCKED,
        (_RC("VISION_QUALITY_BLOCKED_NO_WARD_MAP"),),
        can_mimic=False,
        future="ward positions + fog model in GST",
    ),
    "CAP-JUNGLE-INFORMATION": _cap(
        "CAP-JUNGLE-INFORMATION",
        "RISK",
        "Determine whether the player should have known enemy jungler location.",
        ("true_player_vision", "jungler_visibility_timeline", "info_age_semantics"),
        ("omniscient_enemy_positions", "info_age_on_facts", "broad_threat_signals"),
        ("true_player_fog", "player_vision_proof"),
        ("INFO_AGE_EQUALS_PLAYER_BLINDNESS", "OMNISCIENT_EQUALS_PLAYER_KNEW"),
        CapabilityStatus.BLOCKED,
        (_RC("JUNGLE_INFO_BLOCKED_NO_PLAYER_VISION"),),
        can_mimic=False,
        future="player-vision / fog facts",
        notes="Broad risk/threat signals remain allowed; knowledge claims are not.",
    ),
    "CAP-MECHANICAL-EXECUTION": _cap(
        "CAP-MECHANICAL-EXECUTION",
        "COMBAT",
        "Skillshot accuracy, spacing, combos, target selection, dodges.",
        ("pov_or_visual_mechanics", "ability_timings", "cast_targets"),
        (),
        ("pov_visual", "mechanical_timelines", "ability_hit_miss"),
        ("DEATH_OR_KILL_EQUALS_MECHANICAL_QUALITY",),
        CapabilityStatus.BLOCKED,
        (_RC("EXECUTION_BLOCKED_C2_NOT_OBSERVABLE"),),
        can_mimic=False,
        future="visual/mechanical evidence layer",
    ),
    "CAP-SUMMONER-USAGE": _cap(
        "CAP-SUMMONER-USAGE",
        "COMBAT",
        "Evaluate Flash/heal/etc. usage correctness.",
        ("summoner_loadout", "cooldown_state", "cast_events"),
        ("occasional_omission_heuristics",),
        ("reliable_loadout", "cooldown_state", "cast_timeline"),
        ("UNUSED_ESCAPE_RULE_PROVES_SHOULD_HAVE_FLASHED",),
        CapabilityStatus.BLOCKED,
        (_RC("SUMMONER_BLOCKED_INCOMPLETE_LOADOUT"),),
        can_mimic=False,
        future="summoner loadout + cooldown facts in production GST",
    ),
    "CAP-RESOURCE-SPENDING": _cap(
        "CAP-RESOURCE-SPENDING",
        "ECONOMY",
        "Evaluate unspent gold / purchase timing signals.",
        ("current_or_unspent_gold", "purchase_events", "time"),
        ("gold_facts", "purchase_events", "R-002_R-006_heuristics", "C1_resolution"),
        ("full_intent_model", "all_valid_hold_reasons"),
        ("UNSPENT_GOLD_ALWAYS_MISTAKE",),
        CapabilityStatus.PARTIAL,
        (_RC("RESOURCE_SPENDING_PARTIAL_SUPPORTED"),),
        can_mimic=True,
        future="richer spend/hold intent context",
        notes="Most supported specialized economy capability currently.",
    ),
}


def capability_for(capability_id: str) -> CoachingCapability | None:
    """Return one capability definition or None."""
    return COACHING_CAPABILITIES.get(capability_id)


def all_capabilities() -> tuple[CoachingCapability, ...]:
    """Return capabilities in stable id order."""
    return tuple(COACHING_CAPABILITIES[key] for key in sorted(COACHING_CAPABILITIES))


def evaluate_capability_readiness(
    capability_ids: list[str] | tuple[str, ...] | None = None,
) -> tuple[CoachingCapability, ...]:
    """Return readiness snapshots for requested (or all) capabilities.

    Deterministic and pure — does not inspect live match state. Statuses encode
    repository-verified evidence boundaries for C.3.
    """
    if not capability_ids:
        return all_capabilities()
    rows: list[CoachingCapability] = []
    for cap_id in capability_ids:
        found = capability_for(cap_id)
        if found is not None:
            rows.append(found)
    return tuple(rows)


def wave_action_readiness() -> dict[str, CapabilityStatus]:
    """Explicit freeze/push/crash/etc. readiness — all BLOCKED without minion state."""
    blocked = CapabilityStatus.BLOCKED
    return {
        "freeze": blocked,
        "slow_push": blocked,
        "hard_push": blocked,
        "crash": blocked,
        "bounce": blocked,
        "hold": blocked,
        "thin": blocked,
        "recall_after_crash": blocked,
        "roam_after_crash": blocked,
    }
