"""Assemble RichFrameObservation / RichReplayState from captured frames."""

from __future__ import annotations

from collections.abc import Sequence

from riftlens.perception.capture import CapturedFrame
from riftlens.perception.detect import (
    detect_champion_candidates,
    detect_minion_candidates,
    filter_ambiguous_minions,
)
from riftlens.perception.geometry import LayoutSupport, ScreenGeometry
from riftlens.perception.hud import extract_player_hud
from riftlens.perception.minimap import extract_minimap
from riftlens.perception.models import (
    PERCEPTION_SCHEMA_VERSION,
    AbilitySlotRoi,
    ObservationStatus,
    RichFrameObservation,
    RichReplayState,
    SlotAvailability,
)
from riftlens.perception.readiness import evaluate_perception_capabilities
from riftlens.perception.track import track_candidates_across_frames


def observe_frame(captured: CapturedFrame) -> RichFrameObservation:
    """Run RP.1 detectors on one captured frame."""
    geometry = ScreenGeometry.from_frame(captured.meta.width, captured.meta.height)
    gaps: list[str] = []
    notes: list[str] = [
        "Visual observations are not GST facts.",
        "Participant/champion identity remains unset.",
    ]
    if geometry.layout_support is LayoutSupport.UNSUPPORTED:
        gaps.append(f"unsupported_layout:{geometry.layout_notes}")

    champions = detect_champion_candidates(captured.pixels, geometry)
    minions_raw = detect_minion_candidates(captured.pixels, geometry)
    minions = filter_ambiguous_minions(minions_raw, champions=champions)
    hud = extract_player_hud(captured.pixels, geometry)
    minimap = extract_minimap(captured.pixels, geometry)
    slots = _ability_and_item_slots(geometry)

    if not champions:
        gaps.append("no_champion_candidates")
    if not minions:
        gaps.append("no_minion_candidates")
    if hud.hp_fraction.status is not ObservationStatus.OBSERVED:
        gaps.append("hp_fraction_unknown")
    if hud.resource_fraction.status is not ObservationStatus.OBSERVED:
        gaps.append("resource_fraction_unknown")
    if not minimap.extracted:
        gaps.append("minimap_roi_unavailable")

    return RichFrameObservation(
        schema_version=PERCEPTION_SCHEMA_VERSION,
        frame=captured.meta,
        champion_candidates=champions,
        minion_candidates=minions,
        player_hud=hud,
        ability_slots=slots,
        minimap=minimap,
        gaps=tuple(gaps),
        notes=tuple(notes),
    )


def assemble_rich_state(
    captured_frames: Sequence[CapturedFrame],
    *,
    requested_game_t_ms: int,
) -> RichReplayState:
    """Observe each frame and track candidates across the short window."""
    if not captured_frames:
        raise ValueError("captured_frames must be non-empty")
    observations = tuple(observe_frame(item) for item in captured_frames)
    track_input = tuple(
        (
            int(
                item.frame.actual_game_t_ms
                if item.frame.actual_game_t_ms is not None
                else item.frame.requested_game_t_ms
            ),
            item.champion_candidates + item.minion_candidates,
        )
        for item in observations
    )
    tracks = track_candidates_across_frames(track_input)
    times = [
        int(
            item.frame.actual_game_t_ms
            if item.frame.actual_game_t_ms is not None
            else item.frame.requested_game_t_ms
        )
        for item in observations
    ]
    caps = evaluate_perception_capabilities(observations, tracks)
    summary = {
        "frames": float(len(observations)),
        "champion_candidates": float(
            sum(len(item.champion_candidates) for item in observations)
        ),
        "minion_candidates": float(
            sum(len(item.minion_candidates) for item in observations)
        ),
        "tracks": float(len(tracks)),
    }
    gaps = tuple(sorted({gap for item in observations for gap in item.gaps}))
    return RichReplayState(
        schema_version=PERCEPTION_SCHEMA_VERSION,
        requested_game_t_ms=int(requested_game_t_ms),
        window_start_ms=min(times),
        window_end_ms=max(times),
        frames=observations,
        tracks=tracks,
        capability_status=caps,
        confidence_summary=summary,
        gaps=gaps,
        notes=(
            "RP.1 perception only — no wave/fight/knowledge judgments.",
            "gst_fact=false on all visual outputs.",
        ),
    )


def _ability_and_item_slots(geometry: ScreenGeometry) -> tuple[AbilitySlotRoi, ...]:
    if geometry.layout_support is LayoutSupport.UNSUPPORTED:
        return ()
    rows: list[AbilitySlotRoi] = []
    for slot_id, rect in (*geometry.ability_slot_rects(), *geometry.item_slot_rects()):
        rows.append(
            AbilitySlotRoi(
                slot_id=slot_id,
                region=rect,
                region_norm=geometry.normalize_rect(rect),
                availability=SlotAvailability.UNKNOWN,
                notes="ROI defined for RP.6; availability not classified in RP.1",
            )
        )
    return tuple(rows)
