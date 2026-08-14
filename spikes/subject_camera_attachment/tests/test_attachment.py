"""Tests for render parsing and attach/seek state transitions."""

from __future__ import annotations

import sys
from pathlib import Path

SPIKE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SPIKE))

from attachment import (
    AttachRequestStatus,
    ReattachSequence,
    attach_patch,
    classify_request,
    evaluate_attempt,
    nearest_participant,
    rank_reattach_sequences,
)
from identity import MappingStatus, RosterEntry
from render_state import parse_render

VLAD = RosterEntry(
    participant_id=6,
    champion_name="Vladimir",
    riot_id_game_name="immynator",
    riot_id_tagline="loler",
)


def _render(
    *,
    selection: str = "",
    attached: bool = False,
    mode: str = "top",
    x: float = 0.0,
    z: float = 0.0,
) -> dict[str, object]:
    return {
        "cameraMode": mode,
        "cameraAttached": attached,
        "selectionName": selection,
        "cameraPosition": {"x": x, "y": 1910.0, "z": z},
        "selectionOffset": {"x": 0.0, "y": 0.0, "z": 0.0},
        "champions": True,
        "characters": True,
    }


def test_parse_render_records_selection_and_lacks_participant_id() -> None:
    parsed = parse_render(_render(selection="immynator", attached=True))
    assert parsed.selection_name == "immynator"
    assert parsed.camera_attached is True
    assert parsed.has_participant_id is False
    assert "champions" in parsed.extra_keys
    assert parsed.identity_fields["selectionName"] == "immynator"


def test_vladimir_request_resolves_to_summoner_accepted() -> None:
    before = _render()
    after = _render(selection="immynator", attached=True)
    attempt = evaluate_attempt(
        label="selection_Vladimir",
        patch=attach_patch("Vladimir"),
        before=before,
        after=after,
        roster=(VLAD,),
        intended_pid=6,
    )
    assert attempt.request_status is AttachRequestStatus.ACCEPTED
    assert attempt.mapping_status is MappingStatus.UNIQUE
    assert attempt.resolved.selection_name == "immynator"


def test_invalid_selection_rejected() -> None:
    before = _render()
    after = _render()
    attempt = evaluate_attempt(
        label="invalid",
        patch=attach_patch("NotAChampion"),
        before=before,
        after=after,
        roster=(VLAD,),
        intended_pid=6,
    )
    assert attempt.request_status is AttachRequestStatus.REJECTED
    assert attempt.mapping_status is MappingStatus.UNRESOLVED


def test_clear_selection_sticky_when_name_remains_attached() -> None:
    before = parse_render(_render(selection="immynator", attached=True))
    after = parse_render(_render(selection="immynator", attached=True))
    status = classify_request(
        requested_name="",
        requested_attached=False,
        before=before,
        after=after,
    )
    assert status is AttachRequestStatus.STICKY_UNCHANGED


def test_attach_then_seek_ranked_first_when_attachment_survives() -> None:
    ranked = rank_reattach_sequences(
        attach_survives_seek=True,
        seek_clears_attach=False,
        seek_then_attach_works=True,
        seek_wait_attach_works=True,
    )
    assert ranked[0] is ReattachSequence.ATTACH_THEN_SEEK
    assert ReattachSequence.SEEK_THEN_ATTACH in ranked


def test_seek_then_attach_when_seek_clears() -> None:
    ranked = rank_reattach_sequences(
        attach_survives_seek=False,
        seek_clears_attach=True,
        seek_then_attach_works=True,
        seek_wait_attach_works=True,
    )
    assert ranked[0] is ReattachSequence.SEEK_THEN_ATTACH


def test_nearest_gst_participant_is_subject() -> None:
    camera = (1600.0, 9700.0)
    positions = {
        1: (14000.0, 13000.0),
        6: (1591.0, 9726.0),
        3: (8000.0, 8000.0),
    }
    nearest = nearest_participant(camera, positions)
    assert nearest is not None
    assert nearest[0] == 6
    assert nearest[1] < 200.0
