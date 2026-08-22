"""RiftLens parity capability registry (RP.0). Statuses follow GST/C.3 evidence."""

from __future__ import annotations

from riftlens.coaching.parity.models import (
    ALL_PARITY_DIMENSIONS,
    ParityCapability,
    ReferenceEvidenceLevel,
    RiftLensParityStatus,
)
from riftlens.coaching.parity.references import notes_for_capability

_VC = ReferenceEvidenceLevel.VENDOR_CLAIM
_HR = ReferenceEvidenceLevel.HUMAN_REFERENCE
_DIM = ALL_PARITY_DIMENSIONS

_BLOCKED = RiftLensParityStatus.BLOCKED
_PARTIAL = RiftLensParityStatus.PARTIAL
_READY = RiftLensParityStatus.READY
_REF = RiftLensParityStatus.REFERENCE_ONLY


def _systems_for(capability_id: str) -> tuple[str, ...]:
    return tuple(
        note.system_id
        for note in notes_for_capability(capability_id)
        if note.coverage.value not in {"N/A", "NONE"}
    )


def _cap(
    capability_id: str,
    name: str,
    description: str,
    status: RiftLensParityStatus,
    required: tuple[str, ...],
    available: tuple[str, ...],
    missing: tuple[str, ...],
    current_sources: tuple[str, ...],
    upstream: tuple[str, ...],
    evaluation: str,
    notes: str,
    track: str,
    blocker: str,
    *,
    evidence: ReferenceEvidenceLevel = _VC,
    unlocks: tuple[str, ...] = (),
    baseline: bool = False,
    material: bool = True,
    c3: tuple[str, ...] = (),
) -> ParityCapability:
    return ParityCapability(
        capability_id=capability_id,
        name=name,
        description=description,
        reference_systems=_systems_for(capability_id),
        reference_evidence_level=evidence,
        riftlens_status=status,
        required_inputs=required,
        currently_available_inputs=available,
        missing_inputs=missing,
        current_riftlens_sources=current_sources,
        candidate_upstream_sources=upstream,
        evaluation_method=evaluation,
        parity_dimensions=_DIM,
        notes=notes,
        proposed_rp_track=track,
        primary_blocker=blocker,
        unlocks=unlocks,
        exposed_by_baseline=baseline,
        materially_improves_coaching=material,
        related_c3_ids=c3,
    )


PARITY_CAPABILITIES: dict[str, ParityCapability] = {
    "RP-CAP-WAVE-STATE": _cap(
        "RP-CAP-WAVE-STATE",
        "Exact lane wave state",
        "Minion counts, wave position, push direction, relative size, "
        "crash/bounce conditions.",
        _BLOCKED,
        (
            "lane_minion_counts",
            "minion_hp",
            "wave_position",
            "wave_direction",
            "lane_presence",
        ),
        ("cs_snapshots_60s", "coarse_position_frames"),
        (
            "lane_minion_counts",
            "minion_hp",
            "wave_position",
            "wave_direction",
        ),
        ("GST.CS", "GST.POSITION", "C.3 CAP-WAVE-STATE BLOCKED"),
        ("replay_video_frames", "object_detection", "tracking", "derived_wave_state"),
        "Compare reconstructed wave state to human/CV labels on replay frames.",
        "CS snapshots are not wave state. First real match conversion review "
        "was blocked without wave state. Inference: CS_SNAPSHOT_IS_WAVE_STATE "
        "is unsafe.",
        "RP.2",
        "No minion-level GST facts; MATCH-V5 has no wave geometry.",
        unlocks=("RP-CAP-WAVE-ACTION", "RP-CAP-RECALL", "RP-CAP-TEMPO-CONVERSION"),
        baseline=True,
        c3=("CAP-WAVE-STATE", "wave.management"),
    ),
    "RP-CAP-WAVE-ACTION": _cap(
        "RP-CAP-WAVE-ACTION",
        "Wave action recommendation",
        "Freeze, slow push, hard/fast push, crash, hold, thin, bounce, catch, "
        "push-out.",
        _BLOCKED,
        ("RP-CAP-WAVE-STATE", "strategic_context"),
        (),
        ("RP-CAP-WAVE-STATE", "counterfactual_wave_outcomes"),
        ("C.3 CAP-WAVE-ACTION BLOCKED",),
        ("wave_state_engine", "objective_context", "recall_windows"),
        "Same-case freeze/push/crash labels vs human or reference tool.",
        "Depends on wave-state reconstruction. Do not infer from deaths or CS.",
        "RP.2",
        "Blocked until RP-CAP-WAVE-STATE exists.",
        unlocks=("RP-CAP-RECALL", "RP-CAP-TEMPO-CONVERSION"),
        baseline=True,
        c3=("CAP-WAVE-ACTION",),
    ),
    "RP-CAP-RECALL": _cap(
        "RP-CAP-RECALL",
        "Recall window quality",
        "Recall timing vs wave, item spike, and tempo loss from poor recall.",
        _PARTIAL,
        ("unspent_gold", "purchase_events", "hp", "wave_state", "threat_context"),
        ("unspent_gold_estimation", "purchase_events", "hp_snapshots_60s"),
        ("wave_state_for_recall", "crash_then_reset_proof"),
        ("GST.GOLD", "GST.ITEM_PURCHASED", "GST.HEALTH", "C.3 CAP-RESET PARTIAL"),
        ("wave_state", "live_client_hp", "hud_ocr"),
        "Recall windows labeled good/poor/unjudgeable against wave+item context.",
        "Gold/HP/purchase can flag reset concepts; cannot prove recall quality "
        "without wave crash/bounce context.",
        "RP.2",
        "Missing wave-dependent recall evidence.",
        unlocks=("RP-CAP-TEMPO-CONVERSION", "RP-CAP-ITEMIZATION"),
        c3=("CAP-RESET", "economy.reset_timing"),
    ),
    "RP-CAP-FIGHT-CONTEXT": _cap(
        "RP-CAP-FIGHT-CONTEXT",
        "Fight context reconstruction",
        "Participants, local numbers, reinforcements, engagement timing, "
        "fight availability.",
        _PARTIAL,
        (
            "dense_champion_positions",
            "team_identity",
            "resources_at_t",
            "reinforcement_etas",
        ),
        (
            "kill_events",
            "coarse_60s_positions",
            "interpolated_positions",
            "C.1_fight_windows",
        ),
        ("sub_second_positions", "reliable_local_numbers", "reinforcement_model"),
        ("GST.CHAMPION_KILL", "GST.POSITION", "C.1 fight windows", "H.5 fights"),
        ("replay_frames", "tracking", "live_client", "derived_temporal"),
        "Reconstruct who was present at commit vs human replay inspection.",
        "Observed: fights are detected from kills. Inference: 60s frames cannot "
        "prove local numbers at engagement.",
        "RP.3",
        "Positions sampled ~60s; no identity-stable visual tracks in production.",
        unlocks=("RP-CAP-FIGHT-SELECTION", "RP-CAP-TEMPO-CONVERSION"),
        baseline=True,
        c3=("combat.fight_selection",),
    ),
    "RP-CAP-FIGHT-SELECTION": _cap(
        "RP-CAP-FIGHT-SELECTION",
        "Fight selection / commitment discipline",
        "Favorable vs unfavorable entry; knowingly outnumbered vs unaccounted "
        "enemy; target/threat; disengage/avoid.",
        _BLOCKED,
        (
            "RP-CAP-FIGHT-CONTEXT",
            "RP-CAP-PLAYER-KNOWLEDGE",
            "resource_state",
            "decision_evidence_contract",
        ),
        ("fight_participation_windows", "C.2_decision_UNKNOWN"),
        (
            "player_visible_information",
            "knowingly_outnumbered_vs_unaccounted",
            "defensible_decision_contract",
        ),
        ("C.3 CAP-FIGHT-SELECTION BLOCKED", "combat.fight_selection BLOCKED"),
        ("player_vision_model", "fight_context_engine", "C.2_decision_contracts"),
        "Same-case classification: favorable / outnumbered / unaccounted / avoid.",
        "Baseline 31:24: detector noticed a bad fight but assigned unaccounted "
        "enemies; human: knowingly entered 1v3. Wrong reason is a parity gap. "
        "24:06 AGREE on commitment without accounting for enemy positions.",
        "RP.3",
        "Cannot distinguish unaccounted vs knowingly outnumbered without "
        "player-knowledge + local numbers.",
        unlocks=("RP-CAP-HUMAN-DECISION-REASONING",),
        baseline=True,
        c3=("CAP-FIGHT-SELECTION", "combat.fight_selection"),
    ),
    "RP-CAP-PLAYER-KNOWLEDGE": _cap(
        "RP-CAP-PLAYER-KNOWLEDGE",
        "Player-visible information",
        "What was visible, recently visible, reasonably trackable, or unknown.",
        _BLOCKED,
        ("true_player_fog", "visibility_timeline", "info_age"),
        ("omniscient_timeline_positions", "info_age_on_some_facts"),
        ("true_player_vision", "fog_proof"),
        ("GST omniscient positions", "C.2 player_knowledge claims conservative"),
        ("minimap_analysis", "replay_fog", "temporal_last_seen", "VLM"),
        "Label visible/recent/unknown at commit; penalize omniscient leakage.",
        "MATCH-V5 is omniscient. Baseline 24:28 AGREE jungler from fog; 31:24 "
        "shows information was largely sufficient — knowledge model must not "
        "always blame fog.",
        "RP.4",
        "No true fog-of-war in Riot timeline.",
        unlocks=("RP-CAP-FIGHT-SELECTION", "RP-CAP-JUNGLE-INFORMATION"),
        baseline=True,
        c3=("CAP-JUNGLE-INFORMATION", "risk.information_discipline"),
    ),
    "RP-CAP-JUNGLE-INFORMATION": _cap(
        "RP-CAP-JUNGLE-INFORMATION",
        "Jungle tracking and threat arrival",
        "Jungler last seen, plausible pathing, threat arrival, tracking mistakes.",
        _BLOCKED,
        ("player_vision", "jungler_visibility_timeline", "pathing_model"),
        ("omniscient_jungler_positions", "broad_threat_signals"),
        ("player_vision_proof", "pathing_likelihood"),
        ("C.3 CAP-JUNGLE-INFORMATION BLOCKED", "risk.threat_awareness PARTIAL"),
        ("minimap", "last_seen_clock", "derived_pathing"),
        "Last-seen vs actual arrival on labeled jungler-gank cases.",
        "Broad threat signals allowed; 'you should have known jungler was there' "
        "is not, without player vision.",
        "RP.4",
        "No player-vision / fog facts.",
        unlocks=("RP-CAP-FIGHT-SELECTION",),
        baseline=True,
        c3=("CAP-JUNGLE-INFORMATION",),
    ),
    "RP-CAP-VISION": _cap(
        "RP-CAP-VISION",
        "Vision coverage and ward quality",
        "Wards, visible areas, coverage, blind zones, ward timing.",
        _BLOCKED,
        ("ward_positions", "ward_type", "fog_regions", "coverage_geometry"),
        ("WARD_PLACED_WARD_KILL_without_position",),
        ("ward_positions", "fog_regions"),
        ("GST.WARD_PLACED", "GST.WARD_KILL", "C.3 CAP-VISION-QUALITY BLOCKED"),
        ("replay_minimap", "HUD_CV", "manual_annotation"),
        "Ward map vs human labels; coverage claims require geometry.",
        "Riot ward events have no position field (CURSOR.md). Timing-only "
        "vision.preparation is PARTIAL in C.3, not coverage quality.",
        "RP.4",
        "WARD_PLACED/KILL lack positions; no fog coverage model.",
        unlocks=("RP-CAP-OBJECTIVE-DECISION", "RP-CAP-PLAYER-KNOWLEDGE"),
        c3=("CAP-VISION-QUALITY", "vision.preparation"),
    ),
    "RP-CAP-RESOURCE-STATE": _cap(
        "RP-CAP-RESOURCE-STATE",
        "HP / resource / gold / items / buffs / level",
        "Combat-relevant resource state at decision time.",
        _PARTIAL,
        ("hp", "mana_or_resource", "gold", "items", "buffs", "level", "xp"),
        (
            "hp_gold_xp_level_cs_60s",
            "item_purchase_events",
            "end_of_game_items",
        ),
        ("fight_time_hp", "mana", "buffs", "item_set_at_t"),
        ("GST.HEALTH/GOLD/XP/LEVEL/CS", "GST.ITEM_*", "C.1 snapshots"),
        ("live_client_playerlist", "HUD_OCR", "replay_scoreboard"),
        "Compare resources at t vs HUD/LCD/human at the same timestamp.",
        "Timeline championStats.health is ~60s. R.0: liveclientdata/activeplayer "
        "returned HTTP 400 in replay; playerlist exists but field map unproven.",
        "RP.6",
        "Coarse 60s snapshots; mana/buffs absent from production GST.",
        unlocks=("RP-CAP-FIGHT-SELECTION", "RP-CAP-RECALL"),
        baseline=True,
        c3=("CAP-RESOURCE-SPENDING",),
    ),
    "RP-CAP-COOLDOWNS": _cap(
        "RP-CAP-COOLDOWNS",
        "Ability and summoner cooldown state",
        "Own abilities; enemy abilities where observable; summoner spells; ultimates.",
        _BLOCKED,
        ("summoner_loadout", "cooldown_state", "cast_events"),
        ("match_dto_summoner_ids", "occasional_omission_heuristics"),
        ("cooldown_clock", "cast_timeline", "observable_enemy_cds"),
        ("C.3 CAP-SUMMONER-USAGE BLOCKED",),
        ("HUD_OCR", "live_client", "scoreboard_cv", "VLM"),
        "Flash/ult available vs used on labeled windows; UNJUDGEABLE if unseen.",
        "Production GST often lacks loadout/cooldown state. Do not infer "
        "'should have flashed' from death alone.",
        "RP.6",
        "No reliable cooldown or cast timeline in GST.",
        unlocks=("RP-CAP-MECHANICS", "RP-CAP-FIGHT-SELECTION"),
        c3=("CAP-SUMMONER-USAGE", "combat.summoner_usage"),
    ),
    "RP-CAP-MECHANICS": _cap(
        "RP-CAP-MECHANICS",
        "Mechanical execution",
        "Skillshots, ability usage, combo order, spacing, target selection, "
        "execution errors.",
        _BLOCKED,
        ("pov_or_visual_mechanics", "ability_hit_miss", "spacing_geometry"),
        (),
        ("pov_visual", "hit_miss", "combo_order"),
        ("C.2 execution NOT_OBSERVABLE", "C.3 CAP-MECHANICAL-EXECUTION BLOCKED"),
        ("replay_video", "object_detection", "tracking", "VLM"),
        "Hit/miss and spacing labels on short POV or replay clips.",
        "Death/kill ≠ mechanical quality. V.0–V.6 are champion-bar spikes, "
        "not skillshot analytics.",
        "RP.6",
        "No mechanical visual evidence in GST.",
        c3=("CAP-MECHANICAL-EXECUTION", "mechanics.execution"),
    ),
    "RP-CAP-TEMPO-CONVERSION": _cap(
        "RP-CAP-TEMPO-CONVERSION",
        "Post-fight tempo conversion",
        "Tower, objective, wave, vision, reset, invade, tempo denial, and "
        "whether 'doing nothing' actually occurred.",
        _PARTIAL,
        (
            "fight_windows",
            "subject_actionable",
            "wave_state",
            "objective_state",
            "position_after_fight",
        ),
        (
            "R-014_tempo_no_conversion",
            "subject_actionable_after_fight",
            "coarse_post_fight_position",
        ),
        ("wave_state", "whether_pushing_waves_is_conversion"),
        ("H.7 R-014", "C.3 tempo.post_fight_conversion PARTIAL"),
        ("wave_state_engine", "building_events", "objective_events"),
        "After won fights, label conversion quality including wave push-out.",
        "Baseline: AGREE fights won and player survived at 25:56 / 28:07 / "
        "35:21; overall conversion PARTLY because pushing incoming waves was "
        "itself conversion. Without wave state RiftLens cannot judge this.",
        "RP.5",
        "Cannot tell conversion from wave correction without wave state.",
        unlocks=("RP-CAP-OBJECTIVE-DECISION",),
        baseline=True,
        c3=("tempo.post_fight_conversion",),
    ),
    "RP-CAP-OBJECTIVE-DECISION": _cap(
        "RP-CAP-OBJECTIVE-DECISION",
        "Objective contestability and trades",
        "Contestability, lane priority, numerical state, cross-map trade, "
        "timing, setup.",
        _PARTIAL,
        (
            "objective_events",
            "lane_priority",
            "jungler_intent",
            "wave_opportunity_cost",
            "cross_map_value",
        ),
        ("objective_kill_events", "coarse_position", "R-008_presence"),
        ("contestability", "priority", "jungler_intent", "wave_cost"),
        ("C.3 CAP-OBJECTIVE-PRESENCE PARTIAL", "objective.presence"),
        ("wave_state", "fight_context", "player_knowledge"),
        "Presence vs contest-value labels; UNJUDGEABLE without wave/priority.",
        "Baseline 7:07 PARTLY: dragon existed and a rotate window existed, but "
        "allies lacked lane priority and jungler was not attempting dragon. "
        "Presence alone is not enough.",
        "RP.5",
        "Presence detector without contestability / priority / cost model.",
        unlocks=("RP-CAP-ROAM",),
        baseline=True,
        c3=("CAP-OBJECTIVE-PRESENCE", "objective.presence"),
    ),
    "RP-CAP-ROAM": _cap(
        "RP-CAP-ROAM",
        "Roam timing and lane cost",
        "Roam timing, lane cost, urgency, payoff, objective/teamfight context.",
        _PARTIAL,
        ("position_leave_lane", "wave_cost", "game_phase", "objective_urgency"),
        ("coarse_position", "cs_snapshots", "macro.roaming_cost PARTIAL"),
        ("wave_cost", "phase_aware_urgency", "teamfight_risk"),
        ("C.3 macro.roaming_cost PARTIAL",),
        ("wave_state", "objective_timers", "fight_context"),
        "Roam vs hold-lane labels with phase and objective urgency.",
        "Baseline 24:00 DISAGREE: laning effectively over, dragon active; "
        "joining team likely beat first pushing top. Roam-cost needs phase.",
        "RP.5",
        "Roam heuristic lacks phase/objective urgency/wave cost.",
        baseline=True,
        c3=("macro.roaming_cost",),
    ),
    "RP-CAP-LANE-PERFORMANCE": _cap(
        "RP-CAP-LANE-PERFORMANCE",
        "Lane outcome and stability",
        "CS, deaths, trades, pressure, lane outcome, stability.",
        _PARTIAL,
        ("cs_timeline", "deaths", "trade_windows", "wave_pressure"),
        ("cs_snapshots_60s", "death_events", "gold_xp_level"),
        ("per_minion_cs", "trade_quality", "wave_pressure"),
        ("GST.CS", "GST.CHAMPION_KILL", "laning.cs_maintenance PARTIAL"),
        ("wave_state", "HUD_CS", "middiff_style_per_minion"),
        "Lane outcome vs human (won/lost/stable) plus CS delta, not per-minion.",
        "Baseline 14:00 AGREE: won lane, good CS, no unnecessary deaths. "
        "Per-minion missed-CS (middiff claim) is not available.",
        "RP.2",
        "No per-minion CS or trade reconstruction.",
        baseline=True,
        c3=("laning.cs_maintenance", "laning.level_discipline"),
    ),
    "RP-CAP-ITEMIZATION": _cap(
        "RP-CAP-ITEMIZATION",
        "Purchase quality and spikes",
        "Purchase quality, situational items, power spikes.",
        _PARTIAL,
        ("purchase_events", "item_ids", "matchup_context", "patch_data"),
        ("ITEM_PURCHASED/SOLD", "PatchDataProvider", "antiheal_heuristics"),
        ("full_situational_eval", "inventory_at_t"),
        ("GST.ITEM_*", "C.3 economy.itemization_condition PARTIAL"),
        ("live_client_items", "HUD_OCR", "patch_item_graph"),
        "Situational purchase windows vs human; UNJUDGEABLE without context.",
        "Events exist; quality of buys is only weakly supported.",
        "RP.6",
        "No inventory snapshot at arbitrary t; limited situational model.",
        c3=("economy.itemization_condition", "CAP-RESOURCE-SPENDING"),
    ),
    "RP-CAP-LONGITUDINAL": _cap(
        "RP-CAP-LONGITUDINAL",
        "Multi-game habits and active focus",
        "Recurrence, active focus, improvement, regression, resolved habits.",
        _PARTIAL,
        ("multi_game_concept_history", "opportunity_denominators", "hysteresis"),
        ("C.6 engine", "single_game_adapter_partial"),
        ("production_persistence", "stable_opportunity_denominators"),
        ("riftlens.coaching.longitudinal", "C.6 PARTIAL"),
        ("future_persistence", "RP.7 case expansion"),
        "Multi-game focus stability vs flapping; C.7 longitudinal hard fails.",
        "C.6 exists and is not production-wired. Single-game adapter is "
        "explicitly partial. Generic Trenix/Mobalytics/iTero-like analog only.",
        "RP.7",
        "No production persistence; denominators incomplete.",
        evidence=_VC,
        c3=(),
        material=True,
    ),
    "RP-CAP-HUMAN-DECISION-REASONING": _cap(
        "RP-CAP-HUMAN-DECISION-REASONING",
        "Human-grade decision reasoning",
        "Intent, alternatives, decision quality, counterfactuals, cue, drill, "
        "next-game focus.",
        _PARTIAL,
        (
            "supported_decision_quality",
            "counterfactual_alternatives",
            "recognition_cue",
            "drill",
        ),
        ("C.2 interpretation scaffold", "C.5 teaching playbooks", "C.4 tiers"),
        ("reliable_decision_GOOD_POOR", "calibrated_counterfactuals"),
        ("C.2/C.4/C.5 experimental", "C.7 HUMAN VALIDATION NOT PERFORMED"),
        ("RP.3 fight reasoning", "C.7 human studies"),
        "Blinded human preference vs C.5 on same cases; C.7 Q-scores.",
        "Scaffold exists. C.2 fight decisions are typically UNKNOWN. C.5 copy "
        "issues (e.g. contestorsecure) are out of RP.0 scope. Not independent "
        "expert validation.",
        "RP.7",
        "Decision contracts and perception still missing for high-value fights.",
        evidence=_HR,
        unlocks=(),
        baseline=True,
        c3=("combat.fight_selection",),
    ),
    "RP-CAP-REPLAY-NAVIGATION": _cap(
        "RP-CAP-REPLAY-NAVIGATION",
        "Timestamped replay inspection",
        "Seek to coaching timestamps; key-moment navigation.",
        _PARTIAL,
        ("clock_map", "replay_host_seek", "finding_t_ms"),
        ("ROFL Replay API seek", "C.x traceability MM:SS", "H.8 timestamps"),
        ("auto_record_like_replays_lol", "vendor_key_moment_labels"),
        ("riftlens.replay_host", "coaching.validation.traceability"),
        ("existing R-series",),
        "Seek accuracy to integer t_ms; not a coaching-judgment metric.",
        "Observed: native .rofl seek is Phase 1 primary. This is navigation, "
        "not perception. Replays.lol auto-record is a vendor claim.",
        "R-series",
        "Key-moment auto-labeling and always-on recording are not RP coaching.",
        material=False,
    ),
}

CAPABILITY_IDS: tuple[str, ...] = tuple(sorted(PARITY_CAPABILITIES))


def all_capabilities() -> tuple[ParityCapability, ...]:
    """Stable capability-id order."""
    return tuple(PARITY_CAPABILITIES[key] for key in CAPABILITY_IDS)


def capability_by_id(capability_id: str) -> ParityCapability | None:
    """Return one capability or None."""
    return PARITY_CAPABILITIES.get(capability_id)
