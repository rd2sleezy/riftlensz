"""Conservative Finding/rule → C.3 concept mappings."""

from __future__ import annotations

from riftlens.coaching.concepts.models import (
    ConceptMapping,
    ConceptSpecificity,
    ReasonCode,
    SignalDirection,
)

_RC = ReasonCode


def _map(
    rule_id: str,
    concept_id: str,
    direction: SignalDirection,
    specificity: ConceptSpecificity,
    *,
    primary: bool = True,
    reasons: tuple[ReasonCode, ...] = (),
    forbidden: tuple[str, ...] = (),
    notes: str = "",
) -> ConceptMapping:
    return ConceptMapping(
        rule_id=rule_id,
        concept_id=concept_id,
        direction=direction,
        specificity=specificity,
        primary=primary,
        reason_codes=reasons,
        forbidden_claims=forbidden,
        notes=notes,
    )


# Every production rule maps conservatively. Broader concepts preferred when
# specific root claims would invent fog, wave state, or decision quality.
RULE_CONCEPT_MAPPINGS: dict[str, tuple[ConceptMapping, ...]] = {
    "R-001": (
        _map(
            "R-001",
            "risk.threat_awareness",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_DEATH_TO_THREAT_AWARENESS"),),
            forbidden=(
                "FAILED_JUNGLE_TRACKING",
                "PLAYER_COULD_NOT_SEE_JUNGLER",
                "POOR_DECISION",
            ),
            notes="Death + inferred unseen jungler signal; fog unavailable.",
        ),
        _map(
            "R-001",
            "risk.information_discipline",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.BROAD,
            primary=False,
            reasons=(_RC("MAP_BROAD_INFO_CONTEXT"),),
            forbidden=("PLAYER_KNEW_OR_DID_NOT_KNOW",),
        ),
    ),
    "R-002": (
        _map(
            "R-002",
            "economy.resource_spending",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_UNSPENT_GOLD_AT_DEATH"),),
            forbidden=("RESET_CAUSED_DEATH", "POOR_DECISION"),
            notes="Economy state at death; not causal proof of prior reset choice.",
        ),
        _map(
            "R-002",
            "economy.post_death_economy",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.GENERAL,
            primary=False,
            reasons=(_RC("MAP_POST_DEATH_ECONOMY_CONTEXT"),),
        ),
    ),
    "R-003": (
        _map(
            "R-003",
            "risk.forward_positioning",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_FORWARD_NO_WARD_EVENT"),),
            forbidden=("WARD_COVERAGE_FAILED", "TRUE_FOG_CLAIM"),
        ),
    ),
    "R-004": (
        _map(
            "R-004",
            "risk.isolation",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_CAUGHT_ALONE"),),
            forbidden=("POOR_DECISION",),
        ),
    ),
    "R-005": (
        _map(
            "R-005",
            "laning.cs_maintenance",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_CS_COLLAPSE_AFTER_DEATH"),),
            forbidden=(
                "WAVE_MANAGEMENT_ERROR",
                "FAILED_FREEZE",
                "FAILED_SLOW_PUSH",
            ),
            notes="CS snapshot change ≠ wave-management classification.",
        ),
    ),
    "R-006": (
        _map(
            "R-006",
            "economy.resource_spending",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_DEAD_GOLD_HELD"),),
            forbidden=("POOR_DECISION", "HOLD_ALWAYS_WRONG"),
        ),
    ),
    "R-007": (
        _map(
            "R-007",
            "economy.reset_timing",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_LOW_HP_HIGH_GOLD"),),
            forbidden=("RECALL_WAS_REQUIRED", "POOR_DECISION"),
        ),
    ),
    "R-008": (
        _map(
            "R-008",
            "objective.presence",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_OBJECTIVE_NO_SHOW"),),
            forbidden=("BAD_MACRO_DECISION", "CROSS_MAP_TRADE_INVALID"),
        ),
    ),
    "R-009": (
        _map(
            "R-009",
            "vision.preparation",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_NO_WARD_PRE_OBJECTIVE"),),
            forbidden=("WARD_COVERAGE_QUALITY",),
        ),
        _map(
            "R-009",
            "objective.preparation",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.BROAD,
            primary=False,
            reasons=(_RC("MAP_OBJECTIVE_SETUP_CONTEXT"),),
        ),
    ),
    "R-010": (
        _map(
            "R-010",
            "vision.control_ward_habit",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_NO_CONTROL_WARD"),),
        ),
    ),
    "R-011": (
        _map(
            "R-011",
            "economy.itemization_condition",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_NO_ANTI_HEAL"),),
        ),
    ),
    "R-012": (
        _map(
            "R-012",
            "combat.fight_selection",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.BROAD,
            reasons=(_RC("MAP_FIGHT_INTO_UNKNOWN_SIGNAL"),),
            forbidden=("POOR_DECISION", "PLAYER_SAW_ENEMIES"),
            notes="Signal only; C.2 decision remains UNKNOWN.",
        ),
    ),
    "R-013": (
        _map(
            "R-013",
            "combat.first_death_pattern",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_DIES_FIRST"),),
            forbidden=("MECHANICAL_OUTPLAY_FAILURE",),
        ),
    ),
    "R-014": (
        _map(
            "R-014",
            "tempo.post_fight_conversion",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_NO_POST_FIGHT_CONVERSION"),),
            forbidden=("SPECIFIC_CONVERSION_TARGET_KNOWN",),
        ),
    ),
    "R-015": (
        _map(
            "R-015",
            "risk.dive_exposure",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_TOWER_DIVE_DEATH"),),
            forbidden=("POOR_DECISION",),
        ),
    ),
    "R-016": (
        _map(
            "R-016",
            "laning.level_discipline",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_LEVEL_DEFICIT"),),
        ),
    ),
    "R-017": (
        _map(
            "R-017",
            "macro.roaming_cost",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.BROAD,
            reasons=(_RC("MAP_ROAM_COST"),),
            forbidden=("ROAM_INTENT_KNOWN",),
        ),
    ),
    "R-018": (
        _map(
            "R-018",
            "risk.repeated_death_zones",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_DEATH_LOCATION_CLUSTER"),),
        ),
    ),
    "R-019": (
        _map(
            "R-019",
            "economy.damage_gold_conversion",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_LOW_DAMAGE_GOLD_CONVERSION"),),
        ),
    ),
    "R-020": (
        _map(
            "R-020",
            "combat.summoner_usage",
            SignalDirection.NEGATIVE,
            ConceptSpecificity.BROAD,
            reasons=(_RC("MAP_UNUSED_ESCAPE_SIGNAL"),),
            forbidden=("FLASH_SHOULD_HAVE_BEEN_USED",),
            notes="Loadout/cooldown often unavailable → capability BLOCKED.",
        ),
    ),
    "P-001": (
        _map(
            "P-001",
            "strength.clean_lane",
            SignalDirection.POSITIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_STRENGTH_CLEAN_LANE"),),
            forbidden=("GOOD_DECISION", "MASTERY_CLAIM"),
        ),
    ),
    "P-002": (
        _map(
            "P-002",
            "strength.efficient_resets",
            SignalDirection.POSITIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_STRENGTH_EFFICIENT_RESETS"),),
            forbidden=("GOOD_DECISION",),
        ),
        _map(
            "P-002",
            "economy.reset_timing",
            SignalDirection.POSITIVE,
            ConceptSpecificity.BROAD,
            primary=False,
            reasons=(_RC("MAP_POSITIVE_RESET_CONTEXT"),),
        ),
    ),
    "P-003": (
        _map(
            "P-003",
            "strength.objective_discipline",
            SignalDirection.POSITIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_STRENGTH_OBJECTIVE"),),
            forbidden=("GOOD_MACRO_DECISION",),
        ),
        _map(
            "P-003",
            "objective.presence",
            SignalDirection.POSITIVE,
            ConceptSpecificity.BROAD,
            primary=False,
            reasons=(_RC("MAP_POSITIVE_OBJECTIVE_PRESENCE"),),
        ),
    ),
    "P-004": (
        _map(
            "P-004",
            "strength.vision_habit",
            SignalDirection.POSITIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_STRENGTH_VISION"),),
            forbidden=("WARD_COVERAGE_QUALITY",),
        ),
    ),
    "P-005": (
        _map(
            "P-005",
            "strength.recovered_from_behind",
            SignalDirection.POSITIVE,
            ConceptSpecificity.GENERAL,
            reasons=(_RC("MAP_STRENGTH_RECOVERY"),),
            forbidden=("GOOD_DECISION",),
        ),
    ),
}


_UNKNOWN_FALLBACK = (
    _map(
        "UNKNOWN",
        "context.risk_broad",
        SignalDirection.UNKNOWN,
        ConceptSpecificity.UNRESOLVED,
        reasons=(_RC("UNKNOWN_RULE_BROAD_FALLBACK"),),
        forbidden=("SPECIFIC_FABRICATED_CONCEPT",),
        notes="Unrecognized rule ids fail broad rather than inventing specificity.",
    ),
)


def mappings_for(rule_id: str) -> tuple[ConceptMapping, ...]:
    """Return concept mappings for a rule id, or a broad unresolved fallback."""
    found = RULE_CONCEPT_MAPPINGS.get(rule_id)
    if found is not None:
        return found
    return tuple(
        ConceptMapping(
            rule_id=rule_id,
            concept_id=item.concept_id,
            direction=item.direction,
            specificity=item.specificity,
            primary=item.primary,
            reason_codes=item.reason_codes,
            forbidden_claims=item.forbidden_claims,
            notes=item.notes,
        )
        for item in _UNKNOWN_FALLBACK
    )


def production_mapped_rule_ids() -> tuple[str, ...]:
    """Return sorted production rule ids with explicit mappings."""
    return tuple(sorted(RULE_CONCEPT_MAPPINGS))
