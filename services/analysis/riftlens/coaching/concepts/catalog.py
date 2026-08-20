"""Initial C.3 coaching concept taxonomy justified by production rules."""

from __future__ import annotations

from riftlens.coaching.concepts.models import CapabilityStatus, CoachingConcept

# Evidence requirement tokens reused across concepts.
_E_GOLD = "unspent_gold_or_current_gold"
_E_PURCHASE = "item_purchase_events"
_E_HP = "health_snapshots"
_E_DEATH = "subject_death_events"
_E_CS = "cs_snapshots"
_E_OBJ = "objective_events"
_E_FIGHT = "fight_participation_windows"
_E_WARD_EVENT = "ward_placed_or_killed_events"
_E_POS = "coarse_position_frames"
_E_LEVEL = "level_snapshots"
_E_FOG = "true_player_fog_or_vision"
_E_WARD_MAP = "ward_positions_and_coverage"
_E_MINION = "minion_counts_hp_wave_direction"
_E_MECH = "pov_mechanical_or_visual_evidence"
_E_SUMMONER = "summoner_loadout_and_cooldown_state"


def _c(
    concept_id: str,
    name: str,
    domain: str,
    definition: str,
    status: CapabilityStatus,
    signals: tuple[str, ...],
    evidence: tuple[str, ...],
    *,
    aliases: tuple[str, ...] = (),
    notes: str = "",
) -> CoachingConcept:
    return CoachingConcept(
        id=concept_id,
        name=name,
        domain=domain,
        definition=definition,
        capability_status=status,
        supported_signal_types=signals,
        evidence_requirements=evidence,
        aliases=aliases,
        notes=notes,
    )


COACHING_CONCEPTS: dict[str, CoachingConcept] = {
    "economy.resource_spending": _c(
        "economy.resource_spending",
        "resource_spending",
        "ECONOMY",
        "Managing unspent gold and converting gold into items.",
        CapabilityStatus.PARTIAL,
        ("STATE", "OUTCOME", "STRENGTH"),
        (_E_GOLD, _E_PURCHASE),
        aliases=("ECONOMY.SPENDING",),
        notes="Supported by R-002/R-006/P-002 style signals; not decision proof.",
    ),
    "economy.reset_timing": _c(
        "economy.reset_timing",
        "reset_timing",
        "ECONOMY",
        "Choosing when to recall/reset given HP, gold, and map context.",
        CapabilityStatus.PARTIAL,
        ("STATE", "OMISSION", "STRENGTH"),
        (_E_GOLD, _E_HP, _E_PURCHASE),
        aliases=("LANING.RECALL_TIMING", "STRENGTH.EFFICIENT_RESETS"),
    ),
    "economy.post_death_economy": _c(
        "economy.post_death_economy",
        "post_death_economy",
        "ECONOMY",
        "Resource consequences and spending state around deaths.",
        CapabilityStatus.PARTIAL,
        ("OUTCOME", "STATE"),
        (_E_DEATH, _E_GOLD, _E_CS),
    ),
    "economy.itemization_condition": _c(
        "economy.itemization_condition",
        "itemization_condition",
        "ITEMIZATION",
        "Conditional build responses such as anti-heal timing.",
        CapabilityStatus.PARTIAL,
        ("OMISSION",),
        (_E_PURCHASE,),
        aliases=("ECONOMY.BUILD",),
    ),
    "economy.damage_gold_conversion": _c(
        "economy.damage_gold_conversion",
        "damage_gold_conversion",
        "ITEMIZATION",
        "Converting damage output into gold/economy efficiently.",
        CapabilityStatus.PARTIAL,
        ("STATE",),
        (_E_GOLD,),
        aliases=("ECONOMY.INCOME",),
    ),
    "tempo.post_fight_conversion": _c(
        "tempo.post_fight_conversion",
        "post_fight_conversion",
        "TEMPO",
        "Using post-fight actionability to convert tempo on the map.",
        CapabilityStatus.PARTIAL,
        ("OMISSION", "ACTION"),
        (_E_FIGHT, _E_POS),
        aliases=("MACRO.TEMPO",),
        notes="R-014 predicate establishes omission condition only.",
    ),
    "risk.threat_awareness": _c(
        "risk.threat_awareness",
        "threat_awareness",
        "RISK",
        "Broad awareness of lethal threats around deaths and fights.",
        CapabilityStatus.PARTIAL,
        ("OUTCOME", "PATTERN"),
        (_E_DEATH, _E_POS),
        notes="Does not claim the player saw or failed to see a specific threat.",
    ),
    "risk.information_discipline": _c(
        "risk.information_discipline",
        "information_discipline",
        "RISK",
        "Playing with incomplete information without inventing fog knowledge.",
        CapabilityStatus.BLOCKED,
        ("OUTCOME", "ACTION"),
        (_E_DEATH, _E_FOG, _E_WARD_MAP),
        notes="True fog unavailable; concept exists as broad risk context only.",
    ),
    "risk.isolation": _c(
        "risk.isolation",
        "isolation_risk",
        "RISK",
        "Dying or fighting while isolated from allies.",
        CapabilityStatus.PARTIAL,
        ("OUTCOME",),
        (_E_DEATH, _E_POS),
    ),
    "risk.forward_positioning": _c(
        "risk.forward_positioning",
        "forward_positioning_risk",
        "RISK",
        "Forward exposure relative to available setup signals.",
        CapabilityStatus.PARTIAL,
        ("OUTCOME", "OMISSION"),
        (_E_DEATH, _E_POS, _E_WARD_EVENT),
    ),
    "risk.dive_exposure": _c(
        "risk.dive_exposure",
        "dive_exposure",
        "POSITIONAL",
        "Tower-dive death exposure signals.",
        CapabilityStatus.PARTIAL,
        ("OUTCOME",),
        (_E_DEATH,),
    ),
    "risk.repeated_death_zones": _c(
        "risk.repeated_death_zones",
        "repeated_death_zones",
        "POSITIONAL",
        "Within-match death location clustering.",
        CapabilityStatus.PARTIAL,
        ("PATTERN",),
        (_E_DEATH, _E_POS),
    ),
    "vision.preparation": _c(
        "vision.preparation",
        "vision_preparation",
        "VISION",
        "Ward-event timing around objectives/forward play (events only, not coverage).",
        CapabilityStatus.PARTIAL,
        ("OMISSION", "STRENGTH"),
        (_E_WARD_EVENT, _E_OBJ),
        notes="Ward map / coverage quality unavailable.",
    ),
    "vision.control_ward_habit": _c(
        "vision.control_ward_habit",
        "control_ward_habit",
        "VISION",
        "Control-ward purchase/habit signals.",
        CapabilityStatus.PARTIAL,
        ("OMISSION", "STRENGTH"),
        (_E_PURCHASE, _E_WARD_EVENT),
    ),
    "laning.cs_maintenance": _c(
        "laning.cs_maintenance",
        "cs_maintenance",
        "LANING",
        "CS snapshot changes and farm maintenance context.",
        CapabilityStatus.PARTIAL,
        ("STATE",),
        (_E_CS,),
        notes="CS change is not wave-management classification.",
    ),
    "laning.level_discipline": _c(
        "laning.level_discipline",
        "level_discipline",
        "LANING",
        "Level/XP deficit at spike windows.",
        CapabilityStatus.PARTIAL,
        ("STATE",),
        (_E_LEVEL,),
    ),
    "objective.presence": _c(
        "objective.presence",
        "objective_presence",
        "OBJECTIVE",
        "Attendance/presence around objective events.",
        CapabilityStatus.PARTIAL,
        ("OMISSION", "STRENGTH"),
        (_E_OBJ, _E_POS),
        notes="Presence ≠ full macro correctness.",
    ),
    "objective.preparation": _c(
        "objective.preparation",
        "objective_preparation",
        "OBJECTIVE",
        "Setup signals before objectives (ward events, tempo).",
        CapabilityStatus.PARTIAL,
        ("OMISSION",),
        (_E_OBJ, _E_WARD_EVENT),
    ),
    "combat.fight_selection": _c(
        "combat.fight_selection",
        "fight_selection_signal",
        "COMBAT",
        "Signals about entering fights under incomplete information.",
        CapabilityStatus.BLOCKED,
        ("ACTION", "OUTCOME"),
        (_E_FIGHT, _E_FOG),
        notes="C.2 decision quality remains UNKNOWN for production fights.",
    ),
    "combat.first_death_pattern": _c(
        "combat.first_death_pattern",
        "first_death_pattern",
        "COMBAT",
        "Dies-first fight participation patterns.",
        CapabilityStatus.PARTIAL,
        ("PATTERN",),
        (_E_FIGHT, _E_DEATH),
    ),
    "macro.roaming_cost": _c(
        "macro.roaming_cost",
        "roaming_cost_context",
        "OBJECTIVE",
        "Roam without priority / roam-cost heuristics.",
        CapabilityStatus.PARTIAL,
        ("ACTION",),
        (_E_POS, _E_CS),
    ),
    "combat.summoner_usage": _c(
        "combat.summoner_usage",
        "summoner_usage",
        "COMBAT",
        "Summoner spell usage evaluation.",
        CapabilityStatus.BLOCKED,
        ("OMISSION",),
        (_E_SUMMONER,),
        notes="Production GST often lacks loadout/cooldown state.",
    ),
    "wave.management": _c(
        "wave.management",
        "wave_management",
        "LANING",
        "Freeze / slow-push / crash / bounce style wave decisions.",
        CapabilityStatus.BLOCKED,
        ("STATE",),
        (_E_MINION, _E_POS),
        notes="CS snapshots and coarse position are not wave state.",
    ),
    "mechanics.execution": _c(
        "mechanics.execution",
        "mechanical_execution",
        "COMBAT",
        "Skillshots, spacing, combos, target selection.",
        CapabilityStatus.BLOCKED,
        ("ACTION",),
        (_E_MECH,),
        notes="C.2 execution is NOT_OBSERVABLE under GST-only evidence.",
    ),
    "strength.clean_lane": _c(
        "strength.clean_lane",
        "clean_lane_phase",
        "STRENGTH",
        "Positive clean-lane strength signal.",
        CapabilityStatus.PARTIAL,
        ("STRENGTH",),
        (_E_CS, _E_GOLD),
    ),
    "strength.efficient_resets": _c(
        "strength.efficient_resets",
        "efficient_resets",
        "STRENGTH",
        "Positive efficient-reset strength signal.",
        CapabilityStatus.PARTIAL,
        ("STRENGTH",),
        (_E_PURCHASE, _E_GOLD),
    ),
    "strength.objective_discipline": _c(
        "strength.objective_discipline",
        "objective_discipline",
        "STRENGTH",
        "Positive objective discipline strength.",
        CapabilityStatus.PARTIAL,
        ("STRENGTH",),
        (_E_OBJ,),
    ),
    "strength.vision_habit": _c(
        "strength.vision_habit",
        "vision_habit",
        "STRENGTH",
        "Positive vision habit strength (event-based, not coverage quality).",
        CapabilityStatus.PARTIAL,
        ("STRENGTH",),
        (_E_WARD_EVENT,),
    ),
    "strength.recovered_from_behind": _c(
        "strength.recovered_from_behind",
        "recovered_from_behind",
        "STRENGTH",
        "Positive recovery strength signal.",
        CapabilityStatus.PARTIAL,
        ("STRENGTH",),
        (_E_GOLD,),
    ),
    "context.economy_broad": _c(
        "context.economy_broad",
        "economy_context",
        "ECONOMY",
        "Broad economy context when specificity cannot be defended.",
        CapabilityStatus.PARTIAL,
        ("STATE", "OUTCOME", "UNKNOWN"),
        (_E_GOLD,),
    ),
    "context.risk_broad": _c(
        "context.risk_broad",
        "risk_context",
        "RISK",
        "Broad risk context when a specific risk claim cannot be defended.",
        CapabilityStatus.PARTIAL,
        ("OUTCOME", "UNKNOWN"),
        (_E_DEATH,),
    ),
}


def concept_for(concept_id: str) -> CoachingConcept | None:
    """Return a registered concept or None."""
    return COACHING_CONCEPTS.get(concept_id)


def all_concepts() -> tuple[CoachingConcept, ...]:
    """Return concepts in stable id order."""
    return tuple(COACHING_CONCEPTS[key] for key in sorted(COACHING_CONCEPTS))
