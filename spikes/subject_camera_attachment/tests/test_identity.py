"""Deterministic tests for subject-camera identity mapping."""

from __future__ import annotations

import sys
from pathlib import Path

SPIKE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SPIKE))

from identity import (
    MappingStatus,
    RosterEntry,
    SelectionIdentifierKind,
    classify_readback,
    plan_subject_selection,
    reverse_lookup,
    token_is_unique,
)

VLAD = RosterEntry(
    participant_id=6,
    champion_name="Vladimir",
    riot_id_game_name="immynator",
    riot_id_tagline="loler",
    summoner_name="",
)
FIZZ = RosterEntry(
    participant_id=3,
    champion_name="Fizz",
    riot_id_game_name="Hittheclub09",
    riot_id_tagline="4056",
)
EZ = RosterEntry(
    participant_id=1,
    champion_name="Ezreal",
    riot_id_game_name="Slaydslayer7",
    riot_id_tagline="NA1",
)
UNIQUE_ROSTER = (EZ, FIZZ, VLAD)


def test_unique_champion_and_riot_id_plan_pid_6() -> None:
    plan = plan_subject_selection(UNIQUE_ROSTER, 6)
    assert plan.attach_allowed
    assert plan.status is MappingStatus.UNIQUE
    kinds = [item.kind for item in plan.preferred]
    assert SelectionIdentifierKind.RIOT_DISPLAY in kinds
    assert SelectionIdentifierKind.CHAMPION_DISPLAY in kinds
    assert all(item.unique for item in plan.preferred)
    assert "immynator" in {item.value for item in plan.preferred}
    assert "Vladimir" in {item.value for item in plan.preferred}


def test_vladimir_readback_to_immynator_maps_pid_6() -> None:
    status = classify_readback(
        roster=UNIQUE_ROSTER,
        intended_pid=6,
        requested="Vladimir",
        resolved="immynator",
        camera_attached=True,
    )
    assert status is MappingStatus.UNIQUE
    assert reverse_lookup(UNIQUE_ROSTER, "immynator") == (VLAD,)
    assert reverse_lookup(UNIQUE_ROSTER, "vladimir") == (VLAD,)


def test_attached_without_resolved_name_is_unresolved() -> None:
    assert (
        classify_readback(
            roster=UNIQUE_ROSTER,
            intended_pid=6,
            requested="Vladimir",
            resolved="",
            camera_attached=True,
        )
        is MappingStatus.UNRESOLVED
    )


def test_invalid_or_detached_selection_is_unresolved() -> None:
    assert (
        classify_readback(
            roster=UNIQUE_ROSTER,
            intended_pid=6,
            requested="NotAChampion",
            resolved="",
            camera_attached=False,
        )
        is MappingStatus.UNRESOLVED
    )
    assert reverse_lookup(UNIQUE_ROSTER, "NotAChampion") == ()


def test_duplicate_champion_fail_closed_without_unique_player_token() -> None:
    left = RosterEntry(participant_id=6, champion_name="Vladimir")
    clone = RosterEntry(participant_id=10, champion_name="Vladimir")
    roster = (left, clone)
    plan = plan_subject_selection(roster, 6)
    assert plan.status is MappingStatus.FAIL_CLOSED
    assert plan.attach_allowed is False
    assert token_is_unique(roster, "Vladimir") is False


def test_duplicate_champion_allows_unique_riot_id() -> None:
    clone = RosterEntry(
        participant_id=10,
        champion_name="Vladimir",
        riot_id_game_name="otherVlad",
        riot_id_tagline="NA1",
    )
    roster = (VLAD, clone)
    plan = plan_subject_selection(roster, 6)
    assert plan.status is MappingStatus.UNIQUE
    values = {item.value for item in plan.preferred}
    assert "immynator" in values
    assert "Vladimir" not in values


def test_invalid_sticky_previous_selection_is_unresolved() -> None:
    assert (
        classify_readback(
            roster=UNIQUE_ROSTER,
            intended_pid=6,
            requested="NotAChampion",
            resolved="immynator",
            camera_attached=True,
        )
        is MappingStatus.UNRESOLVED
    )


def test_lcd_display_name_does_not_match_match_v5_token() -> None:
    mundo = RosterEntry(participant_id=2, champion_name="DrMundo", riot_id_game_name="ronamid")
    assert reverse_lookup((mundo,), "Dr. Mundo") == ()
    assert reverse_lookup((mundo,), "DrMundo") == (mundo,)


def test_wrong_pid_readback_fail_closed() -> None:
    status = classify_readback(
        roster=UNIQUE_ROSTER,
        intended_pid=6,
        requested="Fizz",
        resolved="Hittheclub09",
        camera_attached=True,
    )
    assert status is MappingStatus.FAIL_CLOSED


def test_missing_participant_unresolved() -> None:
    plan = plan_subject_selection(UNIQUE_ROSTER, 99)
    assert plan.status is MappingStatus.UNRESOLVED
    assert plan.attach_allowed is False
