"""RP track order, dependencies, and deterministic gap ranking."""

from __future__ import annotations

from riftlens.coaching.parity.capabilities import all_capabilities
from riftlens.coaching.parity.models import (
    ParityCapability,
    PriorityBand,
    RoadmapTrack,
)

ROADMAP_TRACKS: tuple[RoadmapTrack, ...] = (
    RoadmapTrack(
        "RP.1",
        "Rich Replay Perception Foundation",
        (),
        (
            "lane_minion_counts",
            "dense_champion_positions",
            "player_hp_at_t",
            "hud_resources",
        ),
        "Wave, fight, resource, and vision intelligence all lack GST facts. "
        "MATCH-V5 cannot supply minions, true fog, or fight-time HP. "
        "Replay frames + optional Live Client snapshots are the shared "
        "upstream. Do not skip this for cosmetic coaching copy.",
        next=True,
    ),
    RoadmapTrack(
        "RP.2",
        "Wave + Recall Intelligence",
        ("RP.1",),
        ("RP-CAP-WAVE-STATE", "RP-CAP-WAVE-ACTION", "RP-CAP-RECALL"),
        "Baseline conversion PARTLY because pushing waves *was* conversion. "
        "Wave state also unlocks recall-after-crash and roam cost. "
        "Depends on minion perception → tracking → lane geometry → wave state "
        "→ wave-action reasoning.",
    ),
    RoadmapTrack(
        "RP.3",
        "Fight Context + Fight Selection",
        ("RP.1",),
        ("RP-CAP-FIGHT-CONTEXT", "RP-CAP-FIGHT-SELECTION"),
        "Primary human lesson from the Vladimir pilot is commitment discipline. "
        "Needs champion positions, resources, team identity, temporal tracking, "
        "local numbers, then decision reasoning. Player-knowledge (RP.4) is "
        "required to stop the 31:24 wrong-reason failure mode.",
    ),
    RoadmapTrack(
        "RP.4",
        "Player Knowledge + Vision + Jungle Information",
        ("RP.1", "RP.3"),
        (
            "RP-CAP-PLAYER-KNOWLEDGE",
            "RP-CAP-VISION",
            "RP-CAP-JUNGLE-INFORMATION",
        ),
        "31:24: information was largely sufficient; mistake was knowingly 1v3. "
        "24:28: fog jungler really was unknown. These are different epistemic "
        "states. Ordered after RP.3 starts so fight cases exist to label, but "
        "a minimal last-seen model should land with fight selection — not after "
        "tempo work.",
    ),
    RoadmapTrack(
        "RP.5",
        "Tempo + Objective Decision Intelligence",
        ("RP.2", "RP.3"),
        ("RP-CAP-TEMPO-CONVERSION", "RP-CAP-OBJECTIVE-DECISION", "RP-CAP-ROAM"),
        "7:07 and 24:00 showed presence/roam heuristics without contestability, "
        "priority, phase, or wave cost. Depends on wave + fight context.",
    ),
    RoadmapTrack(
        "RP.6",
        "Mechanics + Cooldowns + Resource Intelligence",
        ("RP.1",),
        ("RP-CAP-RESOURCE-STATE", "RP-CAP-COOLDOWNS", "RP-CAP-MECHANICS"),
        "High reference value (middiff-style) but not the Vladimir primary "
        "lesson. HUD/OCR/LCD can raise resource density before full mechanics.",
    ),
    RoadmapTrack(
        "RP.7",
        "Longitudinal / Reference Parity Evaluation Expansion",
        ("RP.2", "RP.3", "RP.4"),
        ("RP-CAP-LONGITUDINAL", "RP-CAP-HUMAN-DECISION-REASONING"),
        "Expand same-case competitor/human references. Keep C.7 for quality/"
        "safety. Do not replace C.7.",
    ),
)


def ranked_capabilities() -> tuple[ParityCapability, ...]:
    """Sort by descending priority score, then capability_id."""
    return tuple(
        sorted(
            all_capabilities(),
            key=lambda cap: (-cap.priority_score(), cap.capability_id),
        )
    )


def top_gaps(*, limit: int = 8) -> tuple[ParityCapability, ...]:
    """Highest-score BLOCKED/PARTIAL capabilities that improve coaching."""
    rows = [
        cap
        for cap in ranked_capabilities()
        if cap.materially_improves_coaching
        and cap.priority() in (PriorityBand.CRITICAL, PriorityBand.HIGH)
    ]
    return tuple(rows[:limit])


def next_track() -> RoadmapTrack:
    """The single recommended next track (RP.1)."""
    for track in ROADMAP_TRACKS:
        if track.next:
            return track
    return ROADMAP_TRACKS[0]
