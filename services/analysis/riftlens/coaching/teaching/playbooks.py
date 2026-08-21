"""Curated C.5 concept playbooks — deterministic coaching knowledge, not GST facts."""

from __future__ import annotations

from riftlens.coaching.teaching.models import (
    AlternativeCertainty,
    ConceptPlaybook,
    DrillKind,
    Measurability,
    MemorableRule,
    PracticeDrill,
    PracticeObjective,
    RecognitionCue,
    TeachingSpecificity,
)

_COMMON_FORBIDDEN = (
    "DECISION_WAS_WRONG",
    "DECISION_WAS_CORRECT",
    "ROOT_CAUSE_CLAIM",
    "CAUSED_THE_OUTCOME",
    "YOU_SHOULD_HAVE_AT_TIMESTAMP",
    "ALWAYS_NEVER_ABSOLUTE",
)


def _cue(
    trigger: str,
    check: str,
    *,
    required: tuple[str, ...] = (),
    unavailable: tuple[str, ...] = (),
) -> RecognitionCue:
    return RecognitionCue(
        trigger=trigger,
        intended_check=check,
        required_conditions=required,
        unavailable_conditions=unavailable,
        specificity=TeachingSpecificity.CONCEPT_GENERAL,
        player_observable=True,
    )


def _rule(when: str, then: str, *, qualifier: str = "reassess") -> MemorableRule:
    return MemorableRule(
        when_trigger=when,
        then_response=then,
        qualifier=qualifier,
        absolute=False,
        specificity=TeachingSpecificity.CONCEPT_GENERAL,
    )


def _drill(
    drill_id: str,
    concept_id: str,
    kind: DrillKind,
    instruction: str,
    observation: str,
    success: str,
    *,
    reps: str = "next game",
) -> PracticeDrill:
    return PracticeDrill(
        id=drill_id,
        concept_id=concept_id,
        kind=kind,
        instruction=instruction,
        repetition_target=reps,
        observation_target=observation,
        success_condition=success,
        supported_scope=TeachingSpecificity.CONCEPT_GENERAL,
        safe=True,
    )


def _objective(
    concept_id: str,
    behavior: str,
    observable: str,
    success: str,
    evidence: tuple[str, ...],
    measurability: Measurability,
    *,
    mode: str = "count_condition_occurrences",
) -> PracticeObjective:
    return PracticeObjective(
        concept_id=concept_id,
        target_behavior=behavior,
        observable=observable,
        evaluation_mode=mode,
        success_definition=success,
        required_future_evidence=evidence,
        measurability=measurability,
        outcome_goal=False,
    )


def _pb(
    concept_id: str,
    explanation: str,
    why: str,
    cue: RecognitionCue,
    rule: MemorableRule,
    alt: str,
    drill: PracticeDrill,
    objective: PracticeObjective,
    *,
    forbidden: tuple[str, ...] = (),
    caps: tuple[str, ...] = (),
    max_spec: TeachingSpecificity = TeachingSpecificity.CONCEPT_GENERAL,
    alt_cert: AlternativeCertainty = AlternativeCertainty.GENERAL_ONLY,
    strength: bool = False,
    notes: str = "",
) -> ConceptPlaybook:
    return ConceptPlaybook(
        concept_id=concept_id,
        version=1,
        explanation=explanation,
        why_it_matters=why,
        recognition_cue=cue,
        memorable_rule=rule,
        alternative_general=alt,
        drill=drill,
        objective_template=objective,
        required_capabilities=caps,
        forbidden_claims=_COMMON_FORBIDDEN + forbidden,
        max_specificity=max_spec,
        alternative_certainty=alt_cert,
        strength_mode=strength,
        notes=notes,
    )


CONCEPT_PLAYBOOKS: dict[str, ConceptPlaybook] = {
    "economy.resource_spending": _pb(
        "economy.resource_spending",
        "Resource spending is about converting held gold into item power.",
        "Unspent gold does not increase combat stats until converted into purchases.",
        _cue(
            "You finish an immediate action while holding gold for a meaningful purchase",
            "make a deliberate stay-versus-reset check",
            required=("self_gold_awareness", "purchase_threshold_known"),
            unavailable=("exact_optimal_recall_timestamp",),
        ),
        _rule(
            "a meaningful purchase is available",
            "whether staying on the map still has a specific purpose",
            qualifier="check",
        ),
        "Look for a reset when a meaningful purchase is available and staying lacks purpose.",
        _drill(
            "drill_resource_spending_verbal",
            "economy.resource_spending",
            DrillKind.VERBAL_CUE,
            "After major lane/map actions, verbally ask: stay with purpose, or reset to buy?",
            "stay/reset checks performed when purchase gold is available",
            "completed the stay/reset check at least several times during the game",
        ),
        _objective(
            "economy.resource_spending",
            "Reduce repeated high-unspent-gold condition signals",
            "supported unspent-gold / resource-spending finding occurrences",
            "fewer supported high-unspent-gold condition occurrences than prior focus baseline",
            ("gold_facts", "purchase_events", "resource_spending_findings"),
            Measurability.MEASURABLE_NOW,
        ),
        forbidden=("RESET_CAUSED_DEATH", "HOLD_ALWAYS_WRONG"),
        notes="General spend/reset discipline; not exact timestamp recall advice.",
    ),
    "economy.reset_timing": _pb(
        "economy.reset_timing",
        "Reset timing is choosing when to leave the map given HP, gold, and purpose.",
        "Staying low-HP with buyable gold can turn a recoverable state into lost tempo and stats.",
        _cue(
            "You are low on health and holding gold for a meaningful purchase",
            "reassess whether continuing the current action is worth delaying the reset",
            required=("self_hp_awareness", "self_gold_awareness"),
            unavailable=("exact_wave_state_for_recall",),
        ),
        _rule(
            "HP is low and a purchase is available",
            "whether continuing on the map still has a clear purpose",
            qualifier="reassess",
        ),
        "When low HP coincides with buyable gold, prioritize an intentional reset check.",
        _drill(
            "drill_reset_timing_pause",
            "economy.reset_timing",
            DrillKind.PAUSE_CHECK,
            "When low HP + buyable gold, pause briefly and answer: purpose to stay, or reset now?",
            "low-HP + gold moments and the stay/reset choice",
            "each noticed moment gets an explicit stay/reset answer",
        ),
        _objective(
            "economy.reset_timing",
            "Reduce repeated low-HP high-gold stay signals",
            "supported reset-timing / low-HP high-gold findings",
            "fewer supported reset-timing condition occurrences under focus",
            ("health_snapshots", "gold_facts", "reset_timing_findings"),
            Measurability.MEASURABLE_NOW,
        ),
        forbidden=("RECALL_WAS_REQUIRED", "RESOLVED_MEANS_GOOD_DECISION"),
    ),
    "tempo.post_fight_conversion": _pb(
        "tempo.post_fight_conversion",
        "Post-fight conversion is using a won or settled fight window to take map value.",
        "Winning a fight without converting tempo often gives the enemy time to reset the map.",
        _cue(
            "A fight has just ended and you are still able to act",
            "ask what immediate map conversion is available before wandering",
            required=("fight_just_ended", "self_still_able_to_act"),
            unavailable=("exact_best_conversion_target",),
        ),
        _rule(
            "a fight ends and you can still act",
            "what immediate conversion is available",
            qualifier="identify",
        ),
        "After a fight you can still act in, look for an immediate conversion before drifting.",
        _drill(
            "drill_tempo_conversion_verbal",
            "tempo.post_fight_conversion",
            DrillKind.VERBAL_CUE,
            "After each fight you survive, say aloud one conversion option you considered.",
            "post-fight conversion checks",
            "each survived fight gets one named conversion consideration",
        ),
        _objective(
            "tempo.post_fight_conversion",
            "Reduce supported no-conversion omission signals after fights",
            "supported post-fight no-conversion findings",
            "fewer supported no-conversion signals while focused",
            ("fight_windows", "post_fight_conversion_findings"),
            Measurability.PARTIALLY_MEASURABLE,
        ),
        forbidden=("SPECIFIC_CONVERSION_TARGET_KNOWN",),
    ),
    "objective.presence": _pb(
        "objective.presence",
        "Objective presence is being able to contest or secure major objectives on time.",
        "Missing contestable objectives can concede large tempo and map control swings.",
        _cue(
            "A major objective window is approaching",
            "check whether your current action still lets you arrive in time",
            required=("objective_timer_or_setup_visible",),
            unavailable=("full_cross_map_trade_value",),
        ),
        _rule(
            "a major objective is approaching",
            "whether current action preserves arrival/contest options",
            qualifier="check",
        ),
        "As an objective approaches, prioritize being able to arrive or contest when present.",
        _drill(
            "drill_objective_presence_tracking",
            "objective.presence",
            DrillKind.TRACKING,
            "Before each dragon/baron/herald window, note whether you planned arrival in time.",
            "objective windows and arrival/contest readiness",
            "each major objective window has a recorded arrival plan check",
        ),
        _objective(
            "objective.presence",
            "Improve arrival/contest readiness around major objectives",
            "supported objective no-show / presence findings",
            "fewer supported objective-absence signals under focus",
            ("objective_events", "position_near_window", "objective_presence_findings"),
            Measurability.PARTIALLY_MEASURABLE,
        ),
        forbidden=("BAD_MACRO_DECISION", "CROSS_MAP_TRADE_INVALID"),
    ),
    "laning.cs_maintenance": _pb(
        "laning.cs_maintenance",
        "CS maintenance is protecting farm rhythm when the lane state allows it.",
        "Sustained CS gaps compound into item and level disadvantages over a match.",
        _cue(
            "You return to lane or stabilize after a disruption",
            "refocus on collecting available farm cleanly",
            required=("back_in_lane_or_stable",),
            unavailable=("exact_wave_freeze_or_push_state",),
        ),
        _rule(
            "the lane is stable enough to farm",
            "collect available CS deliberately",
            qualifier="prioritize",
        ),
        "When the lane is stable, prioritize collecting available farm before optional roaming.",
        _drill(
            "drill_cs_maintenance_review",
            "laning.cs_maintenance",
            DrillKind.REVIEW,
            "After the game, review one CS-drop window and note what disrupted farming focus.",
            "CS trend around disruptions",
            "one reviewed CS-drop window with a named disruption cause candidate",
        ),
        _objective(
            "laning.cs_maintenance",
            "Reduce supported CS-collapse condition signals",
            "supported CS maintenance / collapse findings",
            "fewer supported CS-collapse signals under focus",
            ("cs_snapshots", "cs_findings"),
            Measurability.PARTIALLY_MEASURABLE,
        ),
        forbidden=(
            "WAVE_MANAGEMENT_ERROR",
            "FAILED_FREEZE",
            "FAILED_SLOW_PUSH",
            "HARD_PUSH_RECOMMENDATION",
        ),
        notes="CS teaching only — wave action remains BLOCKED.",
    ),
    "laning.level_discipline": _pb(
        "laning.level_discipline",
        "Level discipline is protecting XP timing around important spike windows.",
        "Falling behind a key level spike can lose otherwise even trades and fights.",
        _cue(
            "A key level spike is near for you or the opponent",
            "check whether your current choice protects or delays that spike",
            required=("level_or_xp_bar_visible",),
        ),
        _rule(
            "a key level spike is approaching",
            "whether the current play protects spike timing",
            qualifier="check",
        ),
        "Near a key spike, prefer actions that protect XP timing over low-value detours.",
        _drill(
            "drill_level_discipline_verbal",
            "laning.level_discipline",
            DrillKind.VERBAL_CUE,
            "When nearing a spike level, say whether your next action protects XP.",
            "pre-spike decisions",
            "each noticed pre-spike window gets an XP-protection check",
        ),
        _objective(
            "laning.level_discipline",
            "Reduce supported level-deficit-at-spike signals",
            "supported level-discipline findings",
            "fewer supported level-deficit signals under focus",
            ("level_snapshots", "level_findings"),
            Measurability.PARTIALLY_MEASURABLE,
        ),
    ),
    "risk.isolation": _pb(
        "risk.isolation",
        "Isolation risk is moving or fighting far from teammates without a clear information edge.",
        "Isolated positions turn otherwise manageable threats into high-leverage deaths.",
        _cue(
            "You are about to move farther from teammates",
            "identify what information makes the path acceptably safe",
            required=("ally_proximity_awareness",),
            unavailable=("true_enemy_fog_state", "exact_enemy_coordinates_as_known"),
        ),
        _rule(
            "you move farther from teammates",
            "what information makes the path safe enough",
            qualifier="identify",
        ),
        "Before extending away from teammates, identify the information that makes the path safe.",
        _drill(
            "drill_isolation_pause",
            "risk.isolation",
            DrillKind.PAUSE_CHECK,
            "Before a deep solo move, pause and name one information reason the path is safe.",
            "solo extensions and named safety reasons",
            "each deep solo extension gets a named safety reason or is aborted",
        ),
        _objective(
            "risk.isolation",
            "Reduce supported isolation-risk signals",
            "supported isolation / caught-alone findings",
            "fewer supported isolation-risk signals under focus",
            ("death_events", "ally_proximity_context", "isolation_findings"),
            Measurability.PARTIALLY_MEASURABLE,
        ),
        forbidden=("PLAYER_COULD_NOT_SEE_JUNGLER", "OMNISCIENT_POSITION_AS_PLAYER_KNOWLEDGE"),
    ),
    "risk.forward_positioning": _pb(
        "risk.forward_positioning",
        "Forward positioning risk is playing ahead without corresponding setup or information.",
        "Forward exposure without setup increases the chance of being punished first.",
        _cue(
            "You are about to play significantly forward of your team or safety line",
            "check whether you have a concrete setup or purpose for that depth",
            required=("self_position_relative_to_safety",),
            unavailable=("ward_coverage_quality", "true_fog"),
        ),
        _rule(
            "you play significantly forward",
            "whether setup/purpose justifies the depth",
            qualifier="check",
        ),
        "Before playing deep forward, confirm a concrete purpose or setup for that depth.",
        _drill(
            "drill_forward_positioning_verbal",
            "risk.forward_positioning",
            DrillKind.VERBAL_CUE,
            "When stepping past your usual safety line, say the purpose of that depth.",
            "forward steps and stated purposes",
            "deep forward steps have a stated purpose",
        ),
        _objective(
            "risk.forward_positioning",
            "Reduce supported forward-exposure signals",
            "supported forward-positioning findings",
            "fewer supported forward-exposure signals under focus",
            ("position_samples", "forward_positioning_findings"),
            Measurability.PARTIALLY_MEASURABLE,
        ),
        forbidden=("WARD_COVERAGE_FAILED", "TRUE_FOG_CLAIM"),
    ),
    "risk.threat_awareness": _pb(
        "risk.threat_awareness",
        "Threat awareness is noticing lethal map threats before committing to risky actions.",
        "Many deaths become preventable when threat checks happen before the commit, not after.",
        _cue(
            "You are about to commit to a risky play with unclear recent threat information",
            "run a brief threat check before committing",
            required=("about_to_commit_risky_action",),
            unavailable=(
                "exact_enemy_jungler_coordinates_as_known",
                "true_player_fog_proof",
            ),
        ),
        _rule(
            "a risky commit is about to happen with unclear threat info",
            "a brief threat check before committing",
            qualifier="perform",
        ),
        "Before a risky commit with unclear threat information, perform a brief threat check.",
        _drill(
            "drill_threat_awareness_verbal",
            "risk.threat_awareness",
            DrillKind.VERBAL_CUE,
            "Before risky commits, ask: what is the biggest unchecked threat right now?",
            "pre-commit threat checks",
            "risky commits are preceded by a spoken threat check",
        ),
        _objective(
            "risk.threat_awareness",
            "Reduce supported threat-awareness risk signals",
            "supported threat-awareness / related death findings",
            "fewer supported threat-awareness signals under focus",
            ("death_events", "threat_awareness_findings"),
            Measurability.PARTIALLY_MEASURABLE,
        ),
        forbidden=(
            "FAILED_JUNGLE_TRACKING",
            "PLAYER_COULD_NOT_SEE_JUNGLER",
            "OMNISCIENT_EQUALS_PLAYER_KNEW",
        ),
        notes="Broad threat concept only; jungle-information capability remains BLOCKED.",
    ),
    "vision.control_ward_habit": _pb(
        "vision.control_ward_habit",
        "Control-ward habit is converting gold into map information and denial regularly.",
        "Consistent control-ward usage improves information quality over many skirmishes.",
        _cue(
            "You return to map with gold available for a control ward and an open slot",
            "decide whether buying/placing a control ward is part of the reset plan",
            required=("control_ward_affordable", "ward_slot_available"),
            unavailable=("exact_best_bush_coverage",),
        ),
        _rule(
            "a control ward is affordable on reset",
            "whether buying/placing one is part of the plan",
            qualifier="decide",
        ),
        "On resets with gold and an open slot, include control-ward purchase in the plan.",
        _drill(
            "drill_control_ward_tracking",
            "vision.control_ward_habit",
            DrillKind.TRACKING,
            "Track how many resets included a control-ward purchase when affordable.",
            "affordable-reset control-ward purchases",
            "most affordable resets include a control-ward decision",
        ),
        _objective(
            "vision.control_ward_habit",
            "Increase supported control-ward habit consistency",
            "control-ward purchase / habit findings",
            "improved control-ward habit signals under focus",
            ("purchase_events", "control_ward_findings"),
            Measurability.PARTIALLY_MEASURABLE,
        ),
        forbidden=("WARD_COVERAGE_QUALITY", "THIS_WARD_WAS_BAD"),
    ),
    "vision.preparation": _pb(
        "vision.preparation",
        "Vision preparation is placing wards before committing to objective or forward plays.",
        "Entering contested spaces without recent vision setup increases surprise risk.",
        _cue(
            "An objective or forward play is about to start",
            "check whether a recent ward setup exists for the approach",
            required=("objective_or_forward_play_imminent",),
            unavailable=("ward_map_coverage_geometry", "fog_regions"),
        ),
        _rule(
            "an objective/forward play is about to start",
            "whether recent vision setup exists for the approach",
            qualifier="check",
        ),
        "Before objective or forward commits, check for recent vision setup on the approach.",
        _drill(
            "drill_vision_preparation_pause",
            "vision.preparation",
            DrillKind.PAUSE_CHECK,
            "Before objective setups, pause and confirm a recent ward event or planned ward.",
            "pre-objective vision checks",
            "each objective setup includes a vision-prep check",
        ),
        _objective(
            "vision.preparation",
            "Reduce supported no-ward-pre-objective signals",
            "supported vision-preparation findings",
            "fewer supported missing pre-objective ward signals under focus",
            ("ward_events", "objective_events", "vision_prep_findings"),
            Measurability.PARTIALLY_MEASURABLE,
        ),
        forbidden=("WARD_COVERAGE_QUALITY", "YOU_COULD_NOT_SEE_THEM"),
    ),
    "economy.itemization_condition": _pb(
        "economy.itemization_condition",
        "Conditional itemization is responding to match conditions with the right purchase timing.",
        "Delayed situational items can leave otherwise winnable fights poorly answered.",
        _cue(
            "A known situational condition appears (for example heavy sustain) and you can buy",
            "check whether the matching situational purchase is now appropriate",
            required=("situational_condition_noticed", "purchase_available"),
        ),
        _rule(
            "a situational condition is present and you can buy",
            "whether the matching item response is due",
            qualifier="check",
        ),
        "When a situational condition appears and gold is available, check the item response.",
        _drill(
            "drill_itemization_review",
            "economy.itemization_condition",
            DrillKind.REVIEW,
            "After the game, note one situational condition and any item response considered.",
            "situational conditions and item responses",
            "one situational condition reviewed with a yes/no item-response note",
        ),
        _objective(
            "economy.itemization_condition",
            "Reduce supported itemization-omission signals",
            "supported itemization-condition findings",
            "fewer supported itemization-omission signals under focus",
            ("purchase_events", "itemization_findings"),
            Measurability.PARTIALLY_MEASURABLE,
        ),
    ),
    # Strength reinforcement playbooks
    "strength.clean_lane": _pb(
        "strength.clean_lane",
        "Clean lane phase is maintaining stable farm and lane control early.",
        "A clean lane phase builds durable gold/XP leads that simplify later decisions.",
        _cue(
            "Lane is stable and farm is available",
            "continue the same deliberate farm focus that produced the clean phase",
            required=("lane_stable",),
        ),
        _rule(
            "lane is stable",
            "the deliberate farm focus that is working",
            qualifier="continue",
        ),
        "Continue the stable-lane farm focus that produced positive evidence this match.",
        _drill(
            "drill_strength_clean_lane",
            "strength.clean_lane",
            DrillKind.REINFORCEMENT,
            "Notice moments where stable-lane farm focus is working and briefly acknowledge them.",
            "stable-lane farm successes",
            "several positive farm-focus moments noticed mid-game",
        ),
        _objective(
            "strength.clean_lane",
            "Maintain supported clean-lane strength signals",
            "supported clean-lane strength findings",
            "clean-lane strength signals continue under focus",
            ("cs_snapshots", "strength_findings"),
            Measurability.PARTIALLY_MEASURABLE,
        ),
        forbidden=("MASTERY_CLAIM", "GOOD_DECISION_CLAIM"),
        strength=True,
    ),
    "strength.efficient_resets": _pb(
        "strength.efficient_resets",
        "Efficient resets convert gold into items without wasting large windows of tempo.",
        "Efficient resets keep combat power current while preserving map timing.",
        _cue(
            "A reset window appears with buyable gold",
            "repeat the efficient reset check that worked in this match",
            required=("buyable_gold",),
        ),
        _rule(
            "a reset window appears with buyable gold",
            "the efficient reset check",
            qualifier="repeat",
        ),
        "When buyable gold and a reset window align, repeat the efficient reset habit.",
        _drill(
            "drill_strength_efficient_resets",
            "strength.efficient_resets",
            DrillKind.REINFORCEMENT,
            "On reset windows with buyable gold, consciously repeat the efficient reset check.",
            "efficient reset checks",
            "reset windows with buyable gold include the efficient-reset check",
        ),
        _objective(
            "strength.efficient_resets",
            "Maintain supported efficient-reset strength signals",
            "supported efficient-reset strength findings",
            "efficient-reset strength signals continue under focus",
            ("purchase_events", "strength_findings"),
            Measurability.PARTIALLY_MEASURABLE,
        ),
        forbidden=("MASTERY_CLAIM", "GOOD_DECISION_CLAIM"),
        strength=True,
    ),
}


# Explicitly blocked concepts: no event-specific teaching playbook content beyond UNAVAILABLE.
BLOCKED_TEACHING_CONCEPTS: frozenset[str] = frozenset(
    {
        "wave.management",
        "mechanics.execution",
        "combat.summoner_usage",
        "risk.information_discipline",
    }
)

BLOCKED_WAVE_ACTIONS: frozenset[str] = frozenset(
    {
        "freeze",
        "slow push",
        "slow_push",
        "hard push",
        "hard_push",
        "crash",
        "bounce",
        "hold",
        "thin",
    }
)


def get_concept_playbook(concept_id: str) -> ConceptPlaybook | None:
    """Return curated playbook or None."""
    return CONCEPT_PLAYBOOKS.get(concept_id)


def all_playbooks() -> tuple[ConceptPlaybook, ...]:
    """Return playbooks in stable concept-id order."""
    return tuple(CONCEPT_PLAYBOOKS[key] for key in sorted(CONCEPT_PLAYBOOKS))


def implemented_playbook_ids() -> tuple[str, ...]:
    """Return sorted concept ids with playbooks."""
    return tuple(sorted(CONCEPT_PLAYBOOKS))
