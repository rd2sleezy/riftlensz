"""External coaching-product registry. Claims are not treated as proven."""

from __future__ import annotations

from riftlens.coaching.parity.models import (
    MatrixCell,
    ReferenceCapabilityNote,
    ReferenceCoverage,
    ReferenceEvidenceLevel,
    ReferenceSystem,
)

# Evidence class: VENDOR_CLAIM unless independently demonstrated in this repo.
_VC = ReferenceEvidenceLevel.VENDOR_CLAIM
_HR = ReferenceEvidenceLevel.HUMAN_REFERENCE
_UN = ReferenceEvidenceLevel.UNKNOWN

_FULL = ReferenceCoverage.FULL
_PART = ReferenceCoverage.PARTIAL
_NONE = ReferenceCoverage.NONE
_UNK = ReferenceCoverage.UNKNOWN
_NA = ReferenceCoverage.NA

REFERENCE_SYSTEMS: dict[str, ReferenceSystem] = {
    "middiff": ReferenceSystem(
        "middiff",
        "middiff",
        "replay_coaching_product",
        "Publicly marketed as timestamped replay coaching with fine-grained "
        "laning/mechanics claims. Not independently verified in this repo.",
        "Capability list below is project knowledge of public claims, not internals.",
    ),
    "questie": ReferenceSystem(
        "questie",
        "Questie",
        "screen_understanding_product",
        "Publicly associated with live/screen understanding of wave, recall, "
        "positions, map, resources, vision, and combat.",
        "No independent Questie output captured in-repo. Treat as vendor claims.",
    ),
    "hakko": ReferenceSystem(
        "hakko",
        "Hakko",
        "live_overlay_product",
        "Publicly associated with minion/wave-state, minimap/jungle tracking, "
        "scoreboard, recall coaching, and persistent memory.",
        "No independent Hakko output captured in-repo. Treat as vendor claims.",
    ),
    "replays_lol": ReferenceSystem(
        "replays_lol",
        "Replays.lol",
        "replay_recording_product",
        "Publicly associated with automatic replay recording, key moments, "
        "instant review navigation, and broad event labels.",
        "Event-label coaching depth is unknown without captured outputs.",
    ),
    "trenix": ReferenceSystem(
        "trenix",
        "Trenix",
        "longitudinal_review_product",
        "Publicly associated with cross-game patterns, key moments, "
        "post-game structured review, and next-game priorities. "
        "C.6 documents Trenix-like behavior as a generic reference style.",
        "C.6 is a generic analog, not a verified Trenix teardown.",
    ),
    "mobalytics": ReferenceSystem(
        "mobalytics",
        "Mobalytics",
        "skill_profile_product",
        "Publicly associated with role-aware skill profiling and persistent "
        "strengths/weaknesses. C.6 documents Mobalytics-like focus style.",
        "C.6 is a generic analog, not a verified Mobalytics teardown.",
    ),
    "itero": ReferenceSystem(
        "itero",
        "iTero",
        "macro_trend_product",
        "Publicly associated with recurring macro patterns and historical "
        "behavioral focus. C.6 documents iTero-like process tracking.",
        "C.6 is a generic analog, not a verified iTero teardown.",
    ),
    "skill_capped": ReferenceSystem(
        "skill_capped",
        "Skill Capped",
        "curriculum_product",
        "Publicly associated with high-quality concept/reference curriculum "
        "and role/champion-specific principles.",
        "Teaching-content reference, not a replay-perception engine we can audit.",
    ),
    "human_coach": ReferenceSystem(
        "human_coach",
        "Metafy / human VOD coaching",
        "human_reference",
        "Human coaches demonstrably analyze intent, alternatives, decision "
        "quality, cues, and improvement plans. This is a human-reference class, "
        "not a single product teardown.",
        "Quality varies by coach. Used as the upper-bound teaching reference.",
    ),
}

MATRIX_SYSTEM_ORDER: tuple[str, ...] = (
    "middiff",
    "questie",
    "hakko",
    "replays_lol",
    "trenix",
    "mobalytics",
    "itero",
    "skill_capped",
    "human_coach",
)


def _note(
    system_id: str,
    capability_id: str,
    coverage: ReferenceCoverage,
    evidence: ReferenceEvidenceLevel,
    notes: str = "",
) -> ReferenceCapabilityNote:
    return ReferenceCapabilityNote(
        system_id=system_id,
        capability_id=capability_id,
        coverage=coverage,
        evidence_level=evidence,
        notes=notes,
    )


def _row(
    capability_id: str,
    cells: dict[str, tuple[ReferenceCoverage, ReferenceEvidenceLevel]],
) -> tuple[ReferenceCapabilityNote, ...]:
    notes: list[ReferenceCapabilityNote] = []
    for system_id in MATRIX_SYSTEM_ORDER:
        coverage, evidence = cells.get(system_id, (_UNK, _UN))
        notes.append(_note(system_id, capability_id, coverage, evidence))
    return tuple(notes)


# Per-capability competitor coverage. Default UNKNOWN. Never mark VENDOR_CLAIM
# as DEMONSTRATED. Human-coach FULL + HUMAN_REFERENCE → matrix DEMONSTRATED.
REFERENCE_MATRIX: dict[str, tuple[ReferenceCapabilityNote, ...]] = {
    "RP-CAP-WAVE-STATE": _row(
        "RP-CAP-WAVE-STATE",
        {
            "middiff": (_FULL, _VC),
            "questie": (_FULL, _VC),
            "hakko": (_FULL, _VC),
            "replays_lol": (_NONE, _VC),
            "trenix": (_UNK, _UN),
            "mobalytics": (_UNK, _UN),
            "itero": (_UNK, _UN),
            "skill_capped": (_PART, _VC),
            "human_coach": (_FULL, _HR),
        },
    ),
    "RP-CAP-WAVE-ACTION": _row(
        "RP-CAP-WAVE-ACTION",
        {
            "middiff": (_PART, _VC),
            "questie": (_FULL, _VC),
            "hakko": (_FULL, _VC),
            "replays_lol": (_NONE, _VC),
            "trenix": (_UNK, _UN),
            "mobalytics": (_UNK, _UN),
            "itero": (_UNK, _UN),
            "skill_capped": (_FULL, _VC),
            "human_coach": (_FULL, _HR),
        },
    ),
    "RP-CAP-RECALL": _row(
        "RP-CAP-RECALL",
        {
            "middiff": (_PART, _VC),
            "questie": (_FULL, _VC),
            "hakko": (_FULL, _VC),
            "replays_lol": (_NONE, _VC),
            "trenix": (_UNK, _UN),
            "mobalytics": (_UNK, _UN),
            "itero": (_UNK, _UN),
            "skill_capped": (_PART, _VC),
            "human_coach": (_FULL, _HR),
        },
    ),
    "RP-CAP-FIGHT-CONTEXT": _row(
        "RP-CAP-FIGHT-CONTEXT",
        {
            "middiff": (_PART, _VC),
            "questie": (_FULL, _VC),
            "hakko": (_PART, _VC),
            "replays_lol": (_PART, _VC),
            "trenix": (_PART, _VC),
            "mobalytics": (_UNK, _UN),
            "itero": (_PART, _VC),
            "skill_capped": (_PART, _VC),
            "human_coach": (_FULL, _HR),
        },
    ),
    "RP-CAP-FIGHT-SELECTION": _row(
        "RP-CAP-FIGHT-SELECTION",
        {
            "middiff": (_PART, _VC),
            "questie": (_FULL, _VC),
            "hakko": (_UNK, _UN),
            "replays_lol": (_NONE, _VC),
            "trenix": (_PART, _VC),
            "mobalytics": (_UNK, _UN),
            "itero": (_PART, _VC),
            "skill_capped": (_PART, _VC),
            "human_coach": (_FULL, _HR),
        },
    ),
    "RP-CAP-PLAYER-KNOWLEDGE": _row(
        "RP-CAP-PLAYER-KNOWLEDGE",
        {
            "middiff": (_FULL, _VC),
            "questie": (_FULL, _VC),
            "hakko": (_PART, _VC),
            "replays_lol": (_NONE, _VC),
            "trenix": (_UNK, _UN),
            "mobalytics": (_UNK, _UN),
            "itero": (_UNK, _UN),
            "skill_capped": (_PART, _VC),
            "human_coach": (_FULL, _HR),
        },
    ),
    "RP-CAP-JUNGLE-INFORMATION": _row(
        "RP-CAP-JUNGLE-INFORMATION",
        {
            "middiff": (_PART, _VC),
            "questie": (_PART, _VC),
            "hakko": (_FULL, _VC),
            "replays_lol": (_NONE, _VC),
            "trenix": (_UNK, _UN),
            "mobalytics": (_UNK, _UN),
            "itero": (_PART, _VC),
            "skill_capped": (_PART, _VC),
            "human_coach": (_FULL, _HR),
        },
    ),
    "RP-CAP-VISION": _row(
        "RP-CAP-VISION",
        {
            "middiff": (_FULL, _VC),
            "questie": (_FULL, _VC),
            "hakko": (_PART, _VC),
            "replays_lol": (_NONE, _VC),
            "trenix": (_UNK, _UN),
            "mobalytics": (_UNK, _UN),
            "itero": (_UNK, _UN),
            "skill_capped": (_PART, _VC),
            "human_coach": (_FULL, _HR),
        },
    ),
    "RP-CAP-RESOURCE-STATE": _row(
        "RP-CAP-RESOURCE-STATE",
        {
            "middiff": (_FULL, _VC),
            "questie": (_FULL, _VC),
            "hakko": (_FULL, _VC),
            "replays_lol": (_NONE, _VC),
            "trenix": (_UNK, _UN),
            "mobalytics": (_UNK, _UN),
            "itero": (_UNK, _UN),
            "skill_capped": (_NA, _VC),
            "human_coach": (_FULL, _HR),
        },
    ),
    "RP-CAP-COOLDOWNS": _row(
        "RP-CAP-COOLDOWNS",
        {
            "middiff": (_FULL, _VC),
            "questie": (_PART, _VC),
            "hakko": (_PART, _VC),
            "replays_lol": (_NONE, _VC),
            "trenix": (_UNK, _UN),
            "mobalytics": (_UNK, _UN),
            "itero": (_UNK, _UN),
            "skill_capped": (_NA, _VC),
            "human_coach": (_FULL, _HR),
        },
    ),
    "RP-CAP-MECHANICS": _row(
        "RP-CAP-MECHANICS",
        {
            "middiff": (_FULL, _VC),
            "questie": (_PART, _VC),
            "hakko": (_UNK, _UN),
            "replays_lol": (_NONE, _VC),
            "trenix": (_UNK, _UN),
            "mobalytics": (_UNK, _UN),
            "itero": (_UNK, _UN),
            "skill_capped": (_FULL, _VC),
            "human_coach": (_FULL, _HR),
        },
    ),
    "RP-CAP-TEMPO-CONVERSION": _row(
        "RP-CAP-TEMPO-CONVERSION",
        {
            "middiff": (_PART, _VC),
            "questie": (_PART, _VC),
            "hakko": (_UNK, _UN),
            "replays_lol": (_PART, _VC),
            "trenix": (_PART, _VC),
            "mobalytics": (_UNK, _UN),
            "itero": (_PART, _VC),
            "skill_capped": (_FULL, _VC),
            "human_coach": (_FULL, _HR),
        },
    ),
    "RP-CAP-OBJECTIVE-DECISION": _row(
        "RP-CAP-OBJECTIVE-DECISION",
        {
            "middiff": (_UNK, _UN),
            "questie": (_PART, _VC),
            "hakko": (_UNK, _UN),
            "replays_lol": (_PART, _VC),
            "trenix": (_PART, _VC),
            "mobalytics": (_PART, _VC),
            "itero": (_FULL, _VC),
            "skill_capped": (_FULL, _VC),
            "human_coach": (_FULL, _HR),
        },
    ),
    "RP-CAP-ROAM": _row(
        "RP-CAP-ROAM",
        {
            "middiff": (_UNK, _UN),
            "questie": (_PART, _VC),
            "hakko": (_UNK, _UN),
            "replays_lol": (_NONE, _VC),
            "trenix": (_PART, _VC),
            "mobalytics": (_UNK, _UN),
            "itero": (_PART, _VC),
            "skill_capped": (_FULL, _VC),
            "human_coach": (_FULL, _HR),
        },
    ),
    "RP-CAP-LANE-PERFORMANCE": _row(
        "RP-CAP-LANE-PERFORMANCE",
        {
            "middiff": (_FULL, _VC),
            "questie": (_PART, _VC),
            "hakko": (_PART, _VC),
            "replays_lol": (_PART, _VC),
            "trenix": (_PART, _VC),
            "mobalytics": (_FULL, _VC),
            "itero": (_PART, _VC),
            "skill_capped": (_PART, _VC),
            "human_coach": (_FULL, _HR),
        },
    ),
    "RP-CAP-ITEMIZATION": _row(
        "RP-CAP-ITEMIZATION",
        {
            "middiff": (_PART, _VC),
            "questie": (_PART, _VC),
            "hakko": (_PART, _VC),
            "replays_lol": (_NONE, _VC),
            "trenix": (_UNK, _UN),
            "mobalytics": (_FULL, _VC),
            "itero": (_UNK, _UN),
            "skill_capped": (_FULL, _VC),
            "human_coach": (_FULL, _HR),
        },
    ),
    "RP-CAP-LONGITUDINAL": _row(
        "RP-CAP-LONGITUDINAL",
        {
            "middiff": (_PART, _VC),
            "questie": (_UNK, _UN),
            "hakko": (_PART, _VC),
            "replays_lol": (_NONE, _VC),
            "trenix": (_FULL, _VC),
            "mobalytics": (_FULL, _VC),
            "itero": (_FULL, _VC),
            "skill_capped": (_NA, _VC),
            "human_coach": (_FULL, _HR),
        },
    ),
    "RP-CAP-HUMAN-DECISION-REASONING": _row(
        "RP-CAP-HUMAN-DECISION-REASONING",
        {
            "middiff": (_PART, _VC),
            "questie": (_PART, _VC),
            "hakko": (_UNK, _UN),
            "replays_lol": (_NONE, _VC),
            "trenix": (_PART, _VC),
            "mobalytics": (_PART, _VC),
            "itero": (_PART, _VC),
            "skill_capped": (_FULL, _VC),
            "human_coach": (_FULL, _HR),
        },
    ),
    "RP-CAP-REPLAY-NAVIGATION": _row(
        "RP-CAP-REPLAY-NAVIGATION",
        {
            "middiff": (_FULL, _VC),
            "questie": (_NA, _VC),
            "hakko": (_NA, _VC),
            "replays_lol": (_FULL, _VC),
            "trenix": (_PART, _VC),
            "mobalytics": (_UNK, _UN),
            "itero": (_UNK, _UN),
            "skill_capped": (_NA, _VC),
            "human_coach": (_PART, _HR),
        },
    ),
}


def all_reference_systems() -> tuple[ReferenceSystem, ...]:
    """Return systems in matrix display order."""
    return tuple(REFERENCE_SYSTEMS[key] for key in MATRIX_SYSTEM_ORDER)


def notes_for_capability(capability_id: str) -> tuple[ReferenceCapabilityNote, ...]:
    """Return per-system notes for one capability, or empty."""
    return REFERENCE_MATRIX.get(capability_id, ())


def assert_vendor_claims_not_demonstrated(
    notes: tuple[ReferenceCapabilityNote, ...] | None = None,
) -> None:
    """Fail fast if a vendor claim would serialize as DEMONSTRATED."""
    rows = notes if notes is not None else tuple(
        note for group in REFERENCE_MATRIX.values() for note in group
    )
    for note in rows:
        cell = note.matrix_cell()
        if (
            note.evidence_level is ReferenceEvidenceLevel.VENDOR_CLAIM
            and cell is MatrixCell.DEMONSTRATED
        ):
            raise ValueError(
                f"{note.system_id}/{note.capability_id} vendor claim marked DEMONSTRATED"
            )
        note.to_dict()
