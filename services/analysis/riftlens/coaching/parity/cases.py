"""Parity-case format and the anonymized Vladimir PILOT_SELF_REVIEW baseline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from riftlens.coaching.parity.models import (
    BASELINE_ADJUDICATION_LABEL,
    PARITY_SCHEMA_VERSION,
    AdjudicationVerdict,
    ParityCaseSource,
    ParityDimension,
    ParityLevel,
    ReferenceEvidenceLevel,
)
from riftlens.coaching.parity.privacy import assert_no_sensitive

BASELINE_MATCH_ID = "NA1_5620410094"
BASELINE_PARTICIPANT_ID = 6
BASELINE_CHAMPION = "Vladimir"
BASELINE_ROLE = "TOP"


def _ms(clock: str) -> int:
    """Parse MM:SS or H:MM:SS to integer milliseconds (floor seconds)."""
    parts = [int(item) for item in clock.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        hours = 0
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError(f"invalid clock {clock!r}")
    return ((hours * 3600) + (minutes * 60) + seconds) * 1000


@dataclass(frozen=True)
class GameContext:
    match_id: str | None
    participant_id: int | None
    champion: str | None
    role: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "participant_id": self.participant_id,
            "champion": self.champion,
            "role": self.role,
        }


@dataclass(frozen=True)
class SystemOutput:
    """Short paraphrase of what a system said. Not copyrighted long-form."""

    system_id: str
    paraphrase: str
    evidence_level: ReferenceEvidenceLevel
    reason_code: str | None = None
    t_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_id": self.system_id,
            "paraphrase": self.paraphrase,
            "evidence_level": self.evidence_level.value,
            "reason_code": self.reason_code,
            "t_ms": self.t_ms,
        }


@dataclass(frozen=True)
class HumanAdjudication:
    verdict: AdjudicationVerdict
    reason: str
    label: str
    reason_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "reason": self.reason,
            "label": self.label,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class DimensionScore:
    dimension: ParityDimension
    level: ParityLevel
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "level": int(self.level),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ParityCase:
    """Reusable same-situation comparison record."""

    case_id: str
    source_type: ParityCaseSource
    game_context: GameContext
    t_ms: int | None
    t_end_ms: int | None
    clock_label: str
    subject: str
    observed_state: str
    reference_outputs: tuple[SystemOutput, ...]
    riftlens_output: SystemOutput | None
    human_adjudication: HumanAdjudication
    required_capabilities: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    parity_scores: tuple[DimensionScore, ...]
    notes: str
    statement_kind: str

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": PARITY_SCHEMA_VERSION,
            "case_id": self.case_id,
            "source_type": self.source_type.value,
            "game_context": self.game_context.to_dict(),
            "t_ms": self.t_ms,
            "t_end_ms": self.t_end_ms,
            "clock_label": self.clock_label,
            "subject": self.subject,
            "observed_state": self.observed_state,
            "reference_outputs": [item.to_dict() for item in self.reference_outputs],
            "riftlens_output": (
                None if self.riftlens_output is None else self.riftlens_output.to_dict()
            ),
            "human_adjudication": self.human_adjudication.to_dict(),
            "required_capabilities": list(self.required_capabilities),
            "missing_inputs": list(self.missing_inputs),
            "parity_scores": [item.to_dict() for item in self.parity_scores],
            "notes": self.notes,
            "statement_kind": self.statement_kind,
        }
        assert_no_sensitive(payload, context=self.case_id)
        return payload


def _ctx() -> GameContext:
    return GameContext(
        match_id=BASELINE_MATCH_ID,
        participant_id=BASELINE_PARTICIPANT_ID,
        champion=BASELINE_CHAMPION,
        role=BASELINE_ROLE,
    )


def _adj(
    verdict: AdjudicationVerdict,
    reason: str,
    *,
    reason_code: str | None = None,
) -> HumanAdjudication:
    return HumanAdjudication(
        verdict=verdict,
        reason=reason,
        label=BASELINE_ADJUDICATION_LABEL,
        reason_code=reason_code,
    )


def _rl(
    paraphrase: str,
    *,
    reason_code: str | None = None,
    t_ms: int | None = None,
) -> SystemOutput:
    return SystemOutput(
        system_id="riftlens",
        paraphrase=paraphrase,
        evidence_level=ReferenceEvidenceLevel.DEMONSTRATED,
        reason_code=reason_code,
        t_ms=t_ms,
    )


def _case(
    case_id: str,
    clock: str,
    subject: str,
    observed: str,
    riftlens: SystemOutput | None,
    human: HumanAdjudication,
    caps: tuple[str, ...],
    missing: tuple[str, ...],
    notes: str,
    *,
    scores: tuple[DimensionScore, ...] = (),
    t_end: str | None = None,
) -> ParityCase:
    t_ms = _ms(clock)
    return ParityCase(
        case_id=case_id,
        source_type=ParityCaseSource.REAL_MATCH_LOCAL,
        game_context=_ctx(),
        t_ms=t_ms,
        t_end_ms=None if t_end is None else _ms(t_end),
        clock_label=clock if t_end is None else f"{clock}–{t_end}",
        subject=subject,
        observed_state=observed,
        reference_outputs=(),
        riftlens_output=riftlens,
        human_adjudication=human,
        required_capabilities=caps,
        missing_inputs=missing,
        parity_scores=scores,
        notes=notes,
        statement_kind="HUMAN_JUDGMENT",
    )


def build_vladimir_baseline_cases() -> tuple[ParityCase, ...]:
    """Manual anonymized PILOT_SELF_REVIEW cases. Not independent expert validation."""
    fight_reason_gap = DimensionScore(
        ParityDimension.CAUSAL_EXPLANATION,
        ParityLevel.DETECTS_EVENT_ONLY,
        "Detector reason ≠ human-adjudicated reason.",
    )
    wave_block = DimensionScore(
        ParityDimension.STATE_RECONSTRUCTION,
        ParityLevel.DETECTS_EVENT_ONLY,
        "Won-fight detected; wave state missing so conversion cannot be judged.",
    )
    return (
        _case(
            "RP0-VLAD-0707-OBJECTIVE",
            "7:07",
            "objective.presence",
            "Dragon existed; a rotate window existed.",
            _rl(
                "Objective presence / attendance signal around dragon.",
                reason_code="objective.presence",
                t_ms=_ms("7:07"),
            ),
            _adj(
                AdjudicationVerdict.PARTLY,
                "Dragon existed and a rotate window existed, but allies lacked "
                "lane priority and jungler was not attempting dragon; rotating "
                "likely loses wave XP/gold for a low-value contest.",
                reason_code="low_value_contest",
            ),
            ("RP-CAP-OBJECTIVE-DECISION", "RP-CAP-WAVE-STATE"),
            (
                "contestability",
                "lane_priority",
                "jungler_intent",
                "wave_opportunity_cost",
                "cross_map_value",
            ),
            "Parity gap: objective presence alone is not enough.",
        ),
        _case(
            "RP0-VLAD-1400-LANE",
            "14:00",
            "clean lane",
            "Lane won; CS good; no unnecessary deaths.",
            _rl("Lane-performance / CS-maintenance style signals available.", t_ms=_ms("14:00")),
            _adj(
                AdjudicationVerdict.AGREE,
                "Won lane, good CS, no unnecessary deaths.",
                reason_code="clean_lane",
            ),
            ("RP-CAP-LANE-PERFORMANCE",),
            ("per_minion_cs",),
            "Human agrees on lane outcome. Per-minion CS still missing.",
        ),
        _case(
            "RP0-VLAD-2400-ROAM",
            "24:00",
            "roam without priority",
            "Player pushing top while dragon/team context existed.",
            _rl(
                "Roam-without-priority / roam-cost heuristic.",
                reason_code="macro.roaming_cost",
                t_ms=_ms("24:00"),
            ),
            _adj(
                AdjudicationVerdict.DISAGREE,
                "Laning phase effectively over, dragon active; joining team "
                "immediately likely more valuable than first pushing top.",
                reason_code="join_team_over_push",
            ),
            ("RP-CAP-ROAM", "RP-CAP-OBJECTIVE-DECISION"),
            ("game_phase", "objective_urgency", "teamfight_risk", "wave_cost"),
            "Parity gap: roam-cost needs phase, urgency, objective timing.",
        ),
        _case(
            "RP0-VLAD-2406-FIGHT",
            "24:06",
            "fight selection",
            "Committed to a fight; fed jungler arrived; death followed.",
            _rl(
                "Problematic fight / threat-awareness signal.",
                reason_code="combat.fight_selection",
                t_ms=_ms("24:06"),
            ),
            _adj(
                AdjudicationVerdict.AGREE,
                "Committed without adequately accounting for enemy positions; "
                "fed jungler arrived and death followed.",
                reason_code="unaccounted_then_death",
            ),
            ("RP-CAP-FIGHT-SELECTION", "RP-CAP-FIGHT-CONTEXT", "RP-CAP-JUNGLE-INFORMATION"),
            ("local_numbers_at_commit", "reinforcement_etas"),
            "Human agrees the commitment was the mistake.",
        ),
        _case(
            "RP0-VLAD-2428-FOG",
            "24:28",
            "unseen jungler",
            "Jungler not visible at initial commitment; appeared from fog after.",
            _rl(
                "Unseen / unaccounted threat framing.",
                reason_code="unaccounted_enemy",
                t_ms=_ms("24:28"),
            ),
            _adj(
                AdjudicationVerdict.AGREE,
                "Jungler was not visible at initial commitment and appeared "
                "from fog afterward.",
                reason_code="fog_jungler",
            ),
            ("RP-CAP-PLAYER-KNOWLEDGE", "RP-CAP-JUNGLE-INFORMATION"),
            ("true_player_vision",),
            "Agrees fog jungler was actually unknown at commit.",
        ),
        _case(
            "RP0-VLAD-3124-FIGHT-REASON",
            "31:24",
            "fight selection",
            "Three enemies visible; other two recently known nearby.",
            _rl(
                "Problematic fight attributed to unaccounted enemies.",
                reason_code="unaccounted_enemies",
                t_ms=_ms("31:24"),
            ),
            _adj(
                AdjudicationVerdict.PARTLY,
                "Information awareness was largely sufficient. Actual mistake "
                "was knowingly entering a 1v3 / overestimating impact.",
                reason_code="knowingly_entered_1v3",
            ),
            (
                "RP-CAP-FIGHT-SELECTION",
                "RP-CAP-PLAYER-KNOWLEDGE",
                "RP-CAP-FIGHT-CONTEXT",
            ),
            (
                "knowingly_outnumbered_vs_unaccounted",
                "local_numbers_at_commit",
            ),
            "CRITICAL: detector notices a problematic fight but assigns the "
            "wrong reason. Detector reason != human-adjudicated reason.",
            scores=(fight_reason_gap,),
        ),
        _case(
            "RP0-VLAD-2556-CONVERSION",
            "25:56",
            "post-fight conversion",
            "Fight won; player survived.",
            _rl("Post-fight conversion / tempo.no_conversion style signal.", t_ms=_ms("25:56")),
            _adj(
                AdjudicationVerdict.AGREE,
                "Fight was won and player survived.",
                reason_code="won_and_survived",
            ),
            ("RP-CAP-TEMPO-CONVERSION", "RP-CAP-WAVE-STATE"),
            ("wave_state",),
            "Moment-level AGREE. Overall conversion still PARTLY (see overall case).",
            scores=(wave_block,),
        ),
        _case(
            "RP0-VLAD-2807-CONVERSION",
            "28:07",
            "post-fight conversion",
            "Fight won; player survived.",
            _rl("Post-fight conversion / tempo.no_conversion style signal.", t_ms=_ms("28:07")),
            _adj(
                AdjudicationVerdict.AGREE,
                "Fight was won and player survived.",
                reason_code="won_and_survived",
            ),
            ("RP-CAP-TEMPO-CONVERSION", "RP-CAP-WAVE-STATE"),
            ("wave_state",),
            "Moment-level AGREE. Wave-state blocker still applies.",
            scores=(wave_block,),
        ),
        _case(
            "RP0-VLAD-3521-CONVERSION",
            "35:21",
            "post-fight conversion",
            "Fight won; player survived.",
            _rl("Post-fight conversion / tempo.no_conversion style signal.", t_ms=_ms("35:21")),
            _adj(
                AdjudicationVerdict.AGREE,
                "Fight was won and player survived.",
                reason_code="won_and_survived",
            ),
            ("RP-CAP-TEMPO-CONVERSION", "RP-CAP-WAVE-STATE"),
            ("wave_state",),
            "Moment-level AGREE. Wave-state blocker still applies.",
            scores=(wave_block,),
        ),
        _case(
            "RP0-VLAD-CONVERSION-OVERALL",
            "25:56",
            "post-fight conversion overall",
            "Multiple won fights; many enemy waves pushed into allied side.",
            _rl(
                "Conversion omission likely if player 'does nothing' after a won fight.",
                reason_code="tempo.post_fight_conversion",
            ),
            _adj(
                AdjudicationVerdict.PARTLY,
                "Many enemy waves were pushed into allied side. Pushing those "
                "waves out was itself meaningful conversion. By the time waves "
                "were corrected, enemies were respawning.",
                reason_code="wave_push_was_conversion",
            ),
            ("RP-CAP-TEMPO-CONVERSION", "RP-CAP-WAVE-STATE"),
            ("wave_state", "whether_pushing_waves_is_conversion"),
            "CRITICAL: RiftLens cannot judge conversion correctly without wave state.",
            scores=(wave_block,),
            t_end="35:21",
        ),
        _case(
            "RP0-VLAD-PRIMARY-LESSON",
            "24:06",
            "overall primary human lesson",
            "Multiple fight-commitment mistakes in the match.",
            _rl(
                "Experimental C.x teaching may surface tempo.post_fight_conversion "
                "or related concepts; not treated as the human primary lesson.",
                reason_code="cx_experimental",
            ),
            _adj(
                AdjudicationVerdict.PARTLY,
                "Overall likely primary human lesson: FIGHT SELECTION / "
                "COMMITMENT DISCIPLINE. Before committing, validate numbers, "
                "known/unknown threats, reinforcements, and whether the fight "
                "is realistically favorable.",
                reason_code="fight_selection_commitment",
            ),
            ("RP-CAP-FIGHT-SELECTION", "RP-CAP-HUMAN-DECISION-REASONING"),
            ("player_visible_information", "local_numbers_at_commit"),
            "Not formal independent expert validation. Label PILOT_SELF_REVIEW.",
        ),
    )


def fight_reason_mismatch_case() -> ParityCase:
    """The 31:24 detector-reason vs human-reason case."""
    for case in build_vladimir_baseline_cases():
        if case.case_id == "RP0-VLAD-3124-FIGHT-REASON":
            return case
    raise RuntimeError("missing 31:24 baseline case")


def conversion_wave_blocker_case() -> ParityCase:
    """Overall conversion case that records the wave-state blocker."""
    for case in build_vladimir_baseline_cases():
        if case.case_id == "RP0-VLAD-CONVERSION-OVERALL":
            return case
    raise RuntimeError("missing conversion overall case")
