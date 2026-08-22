"""Internal RP.1 perception capability readiness (not RP-CAP-* coaching)."""

from __future__ import annotations

from collections.abc import Sequence

from riftlens.perception.models import (
    ObservationStatus,
    PerceptionCapability,
    PerceptionCapabilityStatus,
    RichFrameObservation,
    VisualTrack,
)


def evaluate_perception_capabilities(
    frames: Sequence[RichFrameObservation],
    tracks: Sequence[VisualTrack],
) -> tuple[PerceptionCapability, ...]:
    """Status for low-level RP.1 sensors based on this run's evidence."""
    has_frame = bool(frames)
    has_champ = any(item.champion_candidates for item in frames)
    has_minion = any(item.minion_candidates for item in frames)
    has_hp = any(
        item.player_hud.hp_fraction.status is ObservationStatus.OBSERVED for item in frames
    )
    has_resource = any(
        item.player_hud.resource_fraction.status is ObservationStatus.OBSERVED
        for item in frames
    )
    has_minimap = any(item.minimap.extracted for item in frames)
    has_tracks = any(item.observation_count >= 2 for item in tracks)

    return (
        PerceptionCapability(
            "FRAME-CAPTURE",
            PerceptionCapabilityStatus.READY if has_frame else PerceptionCapabilityStatus.BLOCKED,
            "CapturedFrame + timing_error_ms present" if has_frame else "no frames",
        ),
        PerceptionCapability(
            "HUD-REGION",
            (
                PerceptionCapabilityStatus.PARTIAL
                if has_frame
                else PerceptionCapabilityStatus.BLOCKED
            ),
            "resolution-relative player_hud / ability / item ROIs",
        ),
        PerceptionCapability(
            "HP-FRACTION",
            (
                PerceptionCapabilityStatus.PARTIAL
                if has_hp
                else PerceptionCapabilityStatus.BLOCKED
            ),
            "green HUD bar column-fill observed"
            if has_hp
            else "HP color not observed on this frame set",
        ),
        PerceptionCapability(
            "RESOURCE-FRACTION",
            (
                PerceptionCapabilityStatus.PARTIAL
                if has_resource
                else PerceptionCapabilityStatus.BLOCKED
            ),
            "blue resource bar observed"
            if has_resource
            else "resource UNKNOWN (never fabricated as 0)",
        ),
        PerceptionCapability(
            "CHAMPION-CANDIDATE",
            (
                PerceptionCapabilityStatus.PARTIAL
                if has_champ
                else PerceptionCapabilityStatus.BLOCKED
            ),
            "V.2 hybrid champion-like bars; identity unset",
        ),
        PerceptionCapability(
            "MINION-CANDIDATE",
            (
                PerceptionCapabilityStatus.PARTIAL
                if has_minion
                else PerceptionCapabilityStatus.BLOCKED
            ),
            "short-bar minion candidates; not wave state",
        ),
        PerceptionCapability(
            "MINIMAP-ROI",
            (
                PerceptionCapabilityStatus.PARTIAL
                if has_minimap
                else PerceptionCapabilityStatus.BLOCKED
            ),
            "minimap ROI extracted; no fog/identity",
        ),
        PerceptionCapability(
            "TEMPORAL-TRACKING",
            (
                PerceptionCapabilityStatus.PARTIAL
                if has_tracks
                else PerceptionCapabilityStatus.BLOCKED
            ),
            "stable local track across >=2 observations"
            if has_tracks
            else "need multi-frame window with matchable candidates",
        ),
    )
