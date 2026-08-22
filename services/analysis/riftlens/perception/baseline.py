"""Anonymized Vladimir baseline inspection timestamps (no media)."""

from __future__ import annotations

from typing import Any

VLADIMIR_BASELINE_MANIFEST: dict[str, Any] = {
    "match_id": "NA1_5620410094",
    "participant_id": 6,
    "champion": "Vladimir",
    "role": "TOP",
    "label": "PILOT_SELF_REVIEW",
    "privacy": "no_puuid_no_summoner_no_screenshots_committed",
    "timestamps": (
        {"clock": "7:07", "t_ms": 427_000, "subject": "objective.presence"},
        {"clock": "14:00", "t_ms": 840_000, "subject": "clean_lane"},
        {"clock": "24:00", "t_ms": 1_440_000, "subject": "roam_without_priority"},
        {"clock": "24:06", "t_ms": 1_446_000, "subject": "fight_selection"},
        {"clock": "24:28", "t_ms": 1_468_000, "subject": "unseen_jungler"},
        {"clock": "25:56", "t_ms": 1_556_000, "subject": "post_fight_conversion"},
        {"clock": "28:07", "t_ms": 1_687_000, "subject": "post_fight_conversion"},
        {"clock": "31:24", "t_ms": 1_884_000, "subject": "fight_selection_reason"},
        {"clock": "35:21", "t_ms": 2_121_000, "subject": "post_fight_conversion"},
    ),
}
