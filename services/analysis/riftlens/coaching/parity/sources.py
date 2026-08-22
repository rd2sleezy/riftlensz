"""Conservative input-source dependency table for high-priority gaps."""

from __future__ import annotations

from riftlens.coaching.parity.models import InputSourceRow, SourceAvailability

_NO = SourceAvailability.NO
_PO = SourceAvailability.POSSIBLE
_LK = SourceAvailability.LIKELY
_PR = SourceAvailability.PROVEN
_UN = SourceAvailability.UNKNOWN


def _row(
    input_id: str,
    *,
    riot_match: SourceAvailability = _NO,
    riot_timeline: SourceAvailability = _NO,
    rofl_metadata: SourceAvailability = _NO,
    video_frames: SourceAvailability = _UN,
    hud_cv: SourceAvailability = _UN,
    ocr: SourceAvailability = _UN,
    object_detection: SourceAvailability = _UN,
    tracking: SourceAvailability = _UN,
    minimap: SourceAvailability = _UN,
    vlm: SourceAvailability = _PO,
    derived_temporal: SourceAvailability = _UN,
    live_client: SourceAvailability = _UN,
    manual_annotation: SourceAvailability = _PR,
    notes: str,
) -> InputSourceRow:
    return InputSourceRow(
        input_id=input_id,
        riot_match=riot_match,
        riot_timeline=riot_timeline,
        rofl_metadata=rofl_metadata,
        video_frames=video_frames,
        hud_cv=hud_cv,
        ocr=ocr,
        object_detection=object_detection,
        tracking=tracking,
        minimap=minimap,
        vlm=vlm,
        derived_temporal=derived_temporal,
        live_client=live_client,
        manual_annotation=manual_annotation,
        notes=notes,
    )


INPUT_SOURCE_ROWS: tuple[InputSourceRow, ...] = (
    _row(
        "lane_minion_counts",
        riot_timeline=_NO,
        video_frames=_LK,
        object_detection=_LK,
        tracking=_LK,
        vlm=_PO,
        notes=(
            "PROVEN: MATCH-V5/timeline has no live minion set. "
            "LIKELY: replay/video pixels contain minions; V.0–V.2 rejected "
            "minion-sized bars as noise, so a dedicated detector is required. "
            "VLM: POSSIBLE, not implemented."
        ),
    ),
    _row(
        "minion_hp",
        video_frames=_LK,
        hud_cv=_NO,
        object_detection=_LK,
        notes=(
            "LIKELY via world-space health bars if minions are detected. "
            "HUD CV does not show per-minion HP. Riot API: NO."
        ),
    ),
    _row(
        "wave_position_direction",
        riot_timeline=_NO,
        video_frames=_LK,
        tracking=_LK,
        derived_temporal=_LK,
        notes=(
            "Derived from minion tracks over time. CS delta is not wave position."
        ),
    ),
    _row(
        "player_hp_at_t",
        riot_timeline=_PR,
        video_frames=_LK,
        hud_cv=_LK,
        ocr=_LK,
        live_client=_PO,
        notes=(
            "PROVEN: timeline championStats.health ~60s. "
            "LIKELY: HUD bars (V.0 green/red bars exist as a spike). "
            "POSSIBLE: Live Client playerlist during replay; R.0 proved "
            "activeplayer HTTP 400 in replay, so do not assume activeplayer HP."
        ),
    ),
    _row(
        "mana_or_resource",
        riot_timeline=_NO,
        hud_cv=_LK,
        ocr=_LK,
        live_client=_PO,
        vlm=_PO,
        notes="Not in production GST participantFrames used today.",
    ),
    _row(
        "gold_items_level_xp",
        riot_match=_PR,
        riot_timeline=_PR,
        hud_cv=_LK,
        ocr=_LK,
        live_client=_PO,
        notes=(
            "PROVEN: 60s gold/xp/level/CS and item events. "
            "Inventory at arbitrary t is not proven. Scoreboard OCR: LIKELY."
        ),
    ),
    _row(
        "dense_champion_positions",
        riot_timeline=_PR,
        video_frames=_LK,
        object_detection=_LK,
        tracking=_LK,
        live_client=_NO,
        notes=(
            "PROVEN: ~60s POSITION frames + interpolation (omniscient). "
            "LIKELY: visual champion-like bars (V.0–V.6) without identity. "
            "Production identity-stable tracks: not proven."
        ),
    ),
    _row(
        "true_player_vision",
        riot_match=_NO,
        riot_timeline=_NO,
        video_frames=_PO,
        minimap=_PO,
        tracking=_LK,
        vlm=_PO,
        derived_temporal=_LK,
        notes=(
            "PROVEN gap: Riot API has no true fog. Omniscient positions ≠ "
            "player knowledge. Minimap/fog reconstruction: POSSIBLE, unproven. "
            "Last-seen clocks: LIKELY if visibility can be gated."
        ),
    ),
    _row(
        "ward_positions",
        riot_timeline=_NO,
        video_frames=_PO,
        minimap=_PO,
        ocr=_NO,
        notes=(
            "PROVEN: WARD_PLACED/WARD_KILL have no position field. "
            "Minimap/world ward CV: POSSIBLE, not implemented."
        ),
    ),
    _row(
        "jungler_last_seen",
        riot_timeline=_NO,
        derived_temporal=_LK,
        minimap=_PO,
        video_frames=_PO,
        notes="Requires a visibility gate; omniscient timeline last-position is not last-seen.",
    ),
    _row(
        "cooldown_state",
        riot_timeline=_NO,
        hud_cv=_LK,
        ocr=_LK,
        live_client=_PO,
        vlm=_PO,
        notes=(
            "Match DTO has summoner spell ids, not cooldown clocks. "
            "HUD/scoreboard OCR: LIKELY. LCD: POSSIBLE, unmapped."
        ),
    ),
    _row(
        "skillshot_hit_miss",
        riot_timeline=_NO,
        video_frames=_LK,
        object_detection=_PO,
        tracking=_PO,
        vlm=_PO,
        notes="No GST support. Visual mechanics are BLOCKED (C.2 NOT_OBSERVABLE).",
    ),
    _row(
        "objective_contestability",
        riot_timeline=_PR,
        derived_temporal=_PO,
        notes=(
            "PROVEN: elite monster kill events exist. Contestability needs "
            "priority, numbers, wave cost — those inputs are not proven."
        ),
    ),
    _row(
        "replay_seek_timestamp",
        rofl_metadata=_PR,
        notes=(
            "PROVEN: Replay API playback seek + GST integer t_ms. "
            "This is navigation, not perception."
        ),
    ),
)


def all_input_sources() -> tuple[InputSourceRow, ...]:
    """Stable input-id order."""
    return tuple(sorted(INPUT_SOURCE_ROWS, key=lambda row: row.input_id))
