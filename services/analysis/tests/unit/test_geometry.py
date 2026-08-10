from __future__ import annotations

import json
from pathlib import Path

from riftlens.domain.enums import Team
from riftlens.domain.estimate import Estimate, combine
from riftlens.domain.geometry import (
    MAP_X_MAX,
    MAP_X_MIN,
    MAP_Y_MAX,
    MAP_Y_MIN,
    Point,
    distance,
    is_enemy_half,
    zone_of,
)
from riftlens.domain.ids import is_ulid, new_ulid

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "riot"


def _all_positions() -> list[Point]:
    points: list[Point] = []
    for name in ("NA1_fixture_a", "NA1_fixture_b", "NA1_fixture_c"):
        timeline = json.loads((FIXTURE_ROOT / name / "timeline.json").read_text(encoding="utf-8"))
        for frame in timeline["info"]["frames"]:
            for pframe in frame["participantFrames"].values():
                pos = pframe.get("position")
                if pos:
                    points.append(Point(float(pos["x"]), float(pos["y"])))
            for event in frame.get("events", []):
                pos = event.get("position")
                if pos:
                    points.append(Point(float(pos["x"]), float(pos["y"])))
    return points


def test_map_constants_bound_fixture_positions() -> None:
    points = _all_positions()
    assert points
    xs = [point.x for point in points]
    ys = [point.y for point in points]
    assert MAP_X_MIN <= min(xs)
    assert max(xs) <= MAP_X_MAX
    assert MAP_Y_MIN <= min(ys)
    assert max(ys) <= MAP_Y_MAX


def test_champion_kill_positions_are_never_unknown() -> None:
    for name in ("NA1_fixture_a", "NA1_fixture_b", "NA1_fixture_c"):
        timeline = json.loads((FIXTURE_ROOT / name / "timeline.json").read_text(encoding="utf-8"))
        kills = 0
        for frame in timeline["info"]["frames"]:
            for event in frame.get("events", []):
                if event.get("type") != "CHAMPION_KILL":
                    continue
                pos = event["position"]
                zone = zone_of(Point(float(pos["x"]), float(pos["y"])))
                assert zone.value != "UNKNOWN", (name, event.get("timestamp"), pos)
                kills += 1
        assert kills > 0


def test_enemy_half_and_distance() -> None:
    blue_fountain = Point(400, 400)
    red_fountain = Point(14300, 14300)
    assert distance(blue_fountain, red_fountain) > 10_000
    assert not is_enemy_half(blue_fountain, Team.BLUE)
    assert is_enemy_half(red_fountain, Team.BLUE)
    assert is_enemy_half(blue_fountain, Team.RED)


def test_combine_is_product_not_average() -> None:
    assert combine([1.0, 0.5, 0.5]) == 0.25
    assert combine([]) == 1.0
    assert combine([-1.0, 0.5]) == 0.0
    estimate = Estimate(value=10, confidence=0.2)
    assert not estimate.is_confident(0.5)
    assert estimate.is_confident(0.2)


def test_new_ulid_shape() -> None:
    value = new_ulid()
    assert is_ulid(value)
    assert not is_ulid("nope")
