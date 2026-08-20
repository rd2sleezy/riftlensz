"""Production Finding signal catalog for C.2.

Maps R-001..R-020 and P-001..P-005 to signal/outcome metadata.
Decision quality remains UNKNOWN unless a documented evidence contract exists.

C.2 ships with zero production GOOD/POOR/MIXED decision contracts: current GST
cannot defend those labels without inventing player knowledge or ignoring
documented false positives.
"""

from __future__ import annotations

from dataclasses import dataclass

from riftlens.coaching.interpretation.models import OutcomeKind, OutcomePolarity, SignalType


@dataclass(frozen=True)
class RuleSignalProfile:
    """Static metadata for one production rule id."""

    rule_id: str
    signal_type: SignalType
    outcome_kind: OutcomeKind
    outcome_polarity: OutcomePolarity
    decision_assessable: bool
    execution_observable: bool
    missing_for_decision: tuple[str, ...]
    notes: str


_COMMON_DECISION_GAPS = (
    "player_knowledge_of_enemy_state",
    "true_fog",
    "ward_map",
    "wave_state",
    "counterfactual_alternatives",
    "documented_false_positive_space",
)


def _profile(
    rule_id: str,
    signal: SignalType,
    kind: OutcomeKind,
    polarity: OutcomePolarity,
    *,
    notes: str,
) -> RuleSignalProfile:
    return RuleSignalProfile(
        rule_id=rule_id,
        signal_type=signal,
        outcome_kind=kind,
        outcome_polarity=polarity,
        decision_assessable=False,
        execution_observable=False,
        missing_for_decision=_COMMON_DECISION_GAPS,
        notes=notes,
    )


PRODUCTION_RULE_PROFILES: dict[str, RuleSignalProfile] = {
    "R-001": _profile(
        "R-001",
        SignalType.OUTCOME,
        OutcomeKind.SUBJECT_DEATH,
        OutcomePolarity.UNFAVORABLE,
        notes="Death to inferred unseen jungler; info_age is not fog.",
    ),
    "R-002": _profile(
        "R-002",
        SignalType.STATE,
        OutcomeKind.RESOURCE_STATE,
        OutcomePolarity.UNFAVORABLE,
        notes="Died holding gold; outcome mixes death and economy state.",
    ),
    "R-003": _profile(
        "R-003",
        SignalType.OUTCOME,
        OutcomeKind.SUBJECT_DEATH,
        OutcomePolarity.UNFAVORABLE,
        notes="Forward death without recent ward event; ward map unavailable.",
    ),
    "R-004": _profile(
        "R-004",
        SignalType.OUTCOME,
        OutcomeKind.SUBJECT_DEATH,
        OutcomePolarity.UNFAVORABLE,
        notes="Caught-alone death heuristic.",
    ),
    "R-005": _profile(
        "R-005",
        SignalType.STATE,
        OutcomeKind.RESOURCE_STATE,
        OutcomePolarity.UNFAVORABLE,
        notes="CS collapse after death; consequence-leaning state, not decision proof.",
    ),
    "R-006": _profile(
        "R-006",
        SignalType.STATE,
        OutcomeKind.CONDITION_STATE,
        OutcomePolarity.NEUTRAL,
        notes="Unspent gold held; many valid holds exist in rule false_positives.",
    ),
    "R-007": _profile(
        "R-007",
        SignalType.STATE,
        OutcomeKind.CONDITION_STATE,
        OutcomePolarity.NEUTRAL,
        notes="Low HP + high gold in lane; recall may or may not be correct.",
    ),
    "R-008": _profile(
        "R-008",
        SignalType.OMISSION,
        OutcomeKind.OBJECTIVE_EVENT,
        OutcomePolarity.UNFAVORABLE,
        notes="Missed contestable objective presence; cross-map trades possible.",
    ),
    "R-009": _profile(
        "R-009",
        SignalType.OMISSION,
        OutcomeKind.CONDITION_STATE,
        OutcomePolarity.NEUTRAL,
        notes="No ward event before objective; ward quality/location unknown.",
    ),
    "R-010": _profile(
        "R-010",
        SignalType.OMISSION,
        OutcomeKind.CONDITION_STATE,
        OutcomePolarity.NEUTRAL,
        notes="Control ward purchase pattern.",
    ),
    "R-011": _profile(
        "R-011",
        SignalType.OMISSION,
        OutcomeKind.CONDITION_STATE,
        OutcomePolarity.NEUTRAL,
        notes="Anti-heal omission vs sustain heuristic.",
    ),
    "R-012": _profile(
        "R-012",
        SignalType.ACTION,
        OutcomeKind.FIGHT_RESULT,
        OutcomePolarity.UNFAVORABLE,
        notes="Fight into unknown enemies; player knowledge of fog unavailable.",
    ),
    "R-013": _profile(
        "R-013",
        SignalType.PATTERN,
        OutcomeKind.FIGHT_RESULT,
        OutcomePolarity.UNFAVORABLE,
        notes="Dies-first fight pattern; mechanics not observable.",
    ),
    "R-014": _profile(
        "R-014",
        SignalType.OMISSION,
        OutcomeKind.CONDITION_STATE,
        OutcomePolarity.NEUTRAL,
        notes="Tempo non-conversion after fight; conversion options unknown.",
    ),
    "R-015": _profile(
        "R-015",
        SignalType.OUTCOME,
        OutcomeKind.SUBJECT_DEATH,
        OutcomePolarity.UNFAVORABLE,
        notes="Tower-dive death.",
    ),
    "R-016": _profile(
        "R-016",
        SignalType.STATE,
        OutcomeKind.RESOURCE_STATE,
        OutcomePolarity.UNFAVORABLE,
        notes="Level deficit at spike.",
    ),
    "R-017": _profile(
        "R-017",
        SignalType.ACTION,
        OutcomeKind.CONDITION_STATE,
        OutcomePolarity.NEUTRAL,
        notes="Roam without priority heuristic; map intent unavailable.",
    ),
    "R-018": _profile(
        "R-018",
        SignalType.PATTERN,
        OutcomeKind.PATTERN_SIGNAL,
        OutcomePolarity.UNFAVORABLE,
        notes="Death location cluster.",
    ),
    "R-019": _profile(
        "R-019",
        SignalType.STATE,
        OutcomeKind.RESOURCE_STATE,
        OutcomePolarity.UNFAVORABLE,
        notes="Damage/gold conversion ratio.",
    ),
    "R-020": _profile(
        "R-020",
        SignalType.OMISSION,
        OutcomeKind.CONDITION_STATE,
        OutcomePolarity.NEUTRAL,
        notes="Unused escape summoner; production GST often lacks loadout.",
    ),
    "P-001": _profile(
        "P-001",
        SignalType.STRENGTH,
        OutcomeKind.STRENGTH_SIGNAL,
        OutcomePolarity.FAVORABLE,
        notes="Clean lane strength signal; not automatic GOOD decision.",
    ),
    "P-002": _profile(
        "P-002",
        SignalType.STRENGTH,
        OutcomeKind.STRENGTH_SIGNAL,
        OutcomePolarity.FAVORABLE,
        notes="Efficient resets strength.",
    ),
    "P-003": _profile(
        "P-003",
        SignalType.STRENGTH,
        OutcomeKind.STRENGTH_SIGNAL,
        OutcomePolarity.FAVORABLE,
        notes="Objective discipline strength.",
    ),
    "P-004": _profile(
        "P-004",
        SignalType.STRENGTH,
        OutcomeKind.STRENGTH_SIGNAL,
        OutcomePolarity.FAVORABLE,
        notes="Vision habit strength.",
    ),
    "P-005": _profile(
        "P-005",
        SignalType.STRENGTH,
        OutcomeKind.STRENGTH_SIGNAL,
        OutcomePolarity.FAVORABLE,
        notes="Recovered-from-behind strength.",
    ),
}


def profile_for(rule_id: str) -> RuleSignalProfile:
    """Return catalog profile or a safe UNKNOWN default for unrecognized ids."""
    found = PRODUCTION_RULE_PROFILES.get(rule_id)
    if found is not None:
        return found
    return RuleSignalProfile(
        rule_id=rule_id,
        signal_type=SignalType.UNKNOWN,
        outcome_kind=OutcomeKind.UNKNOWN,
        outcome_polarity=OutcomePolarity.UNKNOWN,
        decision_assessable=False,
        execution_observable=False,
        missing_for_decision=_COMMON_DECISION_GAPS + ("unknown_rule_id",),
        notes="Unrecognized rule id; fail-closed UNKNOWN profile.",
    )


def production_rule_ids() -> tuple[str, ...]:
    """Return sorted production rule ids covered by the catalog."""
    return tuple(sorted(PRODUCTION_RULE_PROFILES))
