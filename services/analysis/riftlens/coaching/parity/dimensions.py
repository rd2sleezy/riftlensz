"""Parity dimensions and behavioral level anchors."""

from __future__ import annotations

from riftlens.coaching.parity.models import (
    ALL_PARITY_DIMENSIONS,
    LevelAnchor,
    ParityDimension,
    ParityLevel,
)

DIMENSION_DEFINITIONS: dict[ParityDimension, str] = {
    ParityDimension.DETECTION: "Did RiftLens identify the relevant moment?",
    ParityDimension.STATE_RECONSTRUCTION: (
        "Did RiftLens understand the relevant game state?"
    ),
    ParityDimension.DECISION_CLASSIFICATION: (
        "Did RiftLens correctly judge the decision?"
    ),
    ParityDimension.CAUSAL_EXPLANATION: "Did RiftLens explain why?",
    ParityDimension.ALTERNATIVE: "Did RiftLens identify a better option?",
    ParityDimension.SPECIFICITY: "Was advice as specific as evidence permits?",
    ParityDimension.EPISTEMIC_CALIBRATION: (
        "Did RiftLens avoid unsupported claims?"
    ),
    ParityDimension.PRIORITIZATION: (
        "Did it identify whether this actually mattered?"
    ),
    ParityDimension.TEACHING_VALUE: "Was the advice useful to improve?",
    ParityDimension.REPLAY_TRACEABILITY: (
        "Can the player inspect the exact moment?"
    ),
    ParityDimension.LONGITUDINAL_VALUE: (
        "Can the behavior be tracked across future games?"
    ),
    ParityDimension.HUMAN_PREFERENCE: (
        "Would a knowledgeable human prefer the RiftLens output?"
    ),
}

GENERIC_LEVEL_ANCHORS: dict[ParityLevel, str] = {
    ParityLevel.ABSENT: "Cannot identify the relevant event or state.",
    ParityLevel.DETECTS_EVENT_ONLY: (
        "Detects that something happened (kill, objective, recall) without context."
    ),
    ParityLevel.RECONSTRUCTS_PARTIAL_CONTEXT: (
        "Reconstructs some participants/resources/timing but cannot judge correctly."
    ),
    ParityLevel.GENERALLY_CORRECT_COACHING: (
        "Usually produces a correct coaching judgment on typical cases."
    ),
    ParityLevel.REFERENCE_COMPARABLE: (
        "Matches strong reference tools or human review on the same cases, "
        "with calibrated reasons."
    ),
    ParityLevel.REFERENCE_EXCEEDING: (
        "Matches or exceeds strong human review with calibrated alternatives "
        "and no false-confidence."
    ),
}

FIGHT_SELECTION_ANCHORS: tuple[LevelAnchor, ...] = (
    LevelAnchor(
        "RP-CAP-FIGHT-SELECTION",
        ParityLevel.ABSENT,
        "Cannot identify a fight.",
    ),
    LevelAnchor(
        "RP-CAP-FIGHT-SELECTION",
        ParityLevel.DETECTS_EVENT_ONLY,
        "Detects fight/death.",
    ),
    LevelAnchor(
        "RP-CAP-FIGHT-SELECTION",
        ParityLevel.RECONSTRUCTS_PARTIAL_CONTEXT,
        "Identifies participants/numbers but cannot judge entry.",
    ),
    LevelAnchor(
        "RP-CAP-FIGHT-SELECTION",
        ParityLevel.GENERALLY_CORRECT_COACHING,
        "Usually judges favorable/unfavorable entry correctly.",
    ),
    LevelAnchor(
        "RP-CAP-FIGHT-SELECTION",
        ParityLevel.REFERENCE_COMPARABLE,
        "Distinguishes unaccounted enemy, knowingly outnumbered, "
        "reinforcement timing, and resource disadvantage, and explains "
        "the correct reason.",
    ),
    LevelAnchor(
        "RP-CAP-FIGHT-SELECTION",
        ParityLevel.REFERENCE_EXCEEDING,
        "Matches/exceeds strong human review with calibrated alternatives.",
    ),
)

WAVE_STATE_ANCHORS: tuple[LevelAnchor, ...] = (
    LevelAnchor(
        "RP-CAP-WAVE-STATE",
        ParityLevel.ABSENT,
        "No wave representation.",
    ),
    LevelAnchor(
        "RP-CAP-WAVE-STATE",
        ParityLevel.DETECTS_EVENT_ONLY,
        "Sees CS snapshot changes or a crash-like death, not the wave.",
    ),
    LevelAnchor(
        "RP-CAP-WAVE-STATE",
        ParityLevel.RECONSTRUCTS_PARTIAL_CONTEXT,
        "Approximate push direction or relative CS, not minion counts/HP.",
    ),
    LevelAnchor(
        "RP-CAP-WAVE-STATE",
        ParityLevel.GENERALLY_CORRECT_COACHING,
        "Usually classifies freeze/slow-push/fast-push/crash on typical lanes.",
    ),
    LevelAnchor(
        "RP-CAP-WAVE-STATE",
        ParityLevel.REFERENCE_COMPARABLE,
        "Minion counts, position, direction, and crash/bounce match a strong "
        "reference on the same replay timestamp.",
    ),
    LevelAnchor(
        "RP-CAP-WAVE-STATE",
        ParityLevel.REFERENCE_EXCEEDING,
        "Wave reconstruction plus action recommendation exceeds typical tools.",
    ),
)


def all_level_anchors() -> tuple[LevelAnchor, ...]:
    """Generic plus specialized anchors, stable order."""
    generic = tuple(
        LevelAnchor("GENERIC", level, GENERIC_LEVEL_ANCHORS[level])
        for level in ParityLevel
    )
    return generic + FIGHT_SELECTION_ANCHORS + WAVE_STATE_ANCHORS


def anchor_for(capability_id: str, level: ParityLevel) -> str:
    """Return specialized behavior text, else generic."""
    for item in (*FIGHT_SELECTION_ANCHORS, *WAVE_STATE_ANCHORS):
        if item.capability_id == capability_id and item.level is level:
            return item.behavior
    return GENERIC_LEVEL_ANCHORS[level]


def all_dimensions() -> tuple[ParityDimension, ...]:
    """Return the 12 parity dimensions in enum order."""
    return ALL_PARITY_DIMENSIONS
