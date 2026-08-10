from __future__ import annotations

import json
from pathlib import Path

from riftlens.adapters.riot.models import MatchDto, TimelineDto
from riftlens.domain.enums import FactKind, GamePhase
from riftlens.domain.fact import SubjectRef
from riftlens.domain.geometry import Point
from riftlens.pipeline.ingest_riot.fact_builder import build_game_state_timeline

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "riot"


def _gst(name: str = "NA1_fixture_a"):
    folder = FIXTURE_ROOT / name
    match = MatchDto.model_validate(json.loads((folder / "match.json").read_text(encoding="utf-8")))
    raw_timeline = json.loads((folder / "timeline.json").read_text(encoding="utf-8"))
    timeline = TimelineDto.model_validate(raw_timeline)
    return build_game_state_timeline(match, timeline), timeline


def test_interpolate_position_at_exact_frame_is_certain() -> None:
    gst, timeline = _gst()
    frame = timeline.info.frames[5]
    t_ms = frame.timestamp
    pframe = frame.participant_frames["5"]
    assert pframe.position is not None
    estimate = gst.interpolate_position(5, t_ms)
    assert estimate.confidence == 1.0
    assert estimate.value == Point(float(pframe.position.x), float(pframe.position.y))
    assert estimate.lo == estimate.value
    assert estimate.hi == estimate.value


def test_interpolate_position_midpoint_hits_floor() -> None:
    gst, timeline = _gst()
    left = timeline.info.frames[4].timestamp
    right = timeline.info.frames[5].timestamp
    mid = left + (right - left) // 2
    estimate = gst.interpolate_position(5, mid)
    assert abs(estimate.confidence - 0.15) < 0.02
    assert estimate.lo is not None and estimate.hi is not None


def test_snapshot_and_phase_queries() -> None:
    gst, _timeline = _gst()
    early = gst.at(60_000)
    assert early.phase is GamePhase.EARLY
    assert 5 in early.participants
    assert gst.phase(20 * 60 * 1000) is GamePhase.MID
    assert gst.phase(30 * 60 * 1000) is GamePhase.LATE
    gold = gst.nearest(FactKind.GOLD, 60_000, subject=SubjectRef(kind="participant", id=5))
    assert gold is not None
    assert gold.t_ms == 60_000
