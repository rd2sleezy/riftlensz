from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from riftlens.domain.enums import Lane, Team

# Summoner's Rift world bounds. Riot docs quote ~x∈[0,14870], y∈[0,14980];
# do not treat those as exact — tests/unit/test_geometry.py calibrates against
# fixture min/max and will fail if a real event falls outside.
MAP_X_MIN = 0
MAP_X_MAX = 14870
MAP_Y_MIN = 0
MAP_Y_MAX = 14980

# Unmounted champion movement without boots is typically ~325–330 units/s.
# Uncertainty radii treat 330 u/s as a conservative reachable-set speed.
CHAMPION_SPEED_UNITS_PER_MS = 330.0 / 1000.0

_NEAR_TURRET_RANGE = 1100.0
_ZONES_PATH = Path(__file__).resolve().parent.parent / "resources" / "map" / "zones.json"

_ZONE_PRIORITY: tuple[str, ...] = (
    "BARON_PIT",
    "DRAGON_PIT",
    "BLUE_BASE",
    "RED_BASE",
    "TOP_RIVER",
    "BOT_RIVER",
    "TOP_LANE",
    "MID_LANE",
    "BOT_LANE",
    "BLUE_TOP_JUNGLE",
    "BLUE_BOT_JUNGLE",
    "RED_TOP_JUNGLE",
    "RED_BOT_JUNGLE",
)


class Zone(StrEnum):
    BLUE_BASE = "BLUE_BASE"
    RED_BASE = "RED_BASE"
    TOP_LANE = "TOP_LANE"
    MID_LANE = "MID_LANE"
    BOT_LANE = "BOT_LANE"
    TOP_RIVER = "TOP_RIVER"
    BOT_RIVER = "BOT_RIVER"
    BLUE_TOP_JUNGLE = "BLUE_TOP_JUNGLE"
    BLUE_BOT_JUNGLE = "BLUE_BOT_JUNGLE"
    RED_TOP_JUNGLE = "RED_TOP_JUNGLE"
    RED_BOT_JUNGLE = "RED_BOT_JUNGLE"
    BARON_PIT = "BARON_PIT"
    DRAGON_PIT = "DRAGON_PIT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class TurretRef:
    team: Team
    lane: Lane
    tier: str


BLUE_BASE = Point(394.0, 461.0)
RED_BASE = Point(14340.0, 14390.0)

_TURRETS: tuple[tuple[TurretRef, Point], ...] = (
    (TurretRef(Team.BLUE, Lane.TOP, "OUTER"), Point(981.0, 10441.0)),
    (TurretRef(Team.BLUE, Lane.TOP, "INNER"), Point(1512.0, 6699.0)),
    (TurretRef(Team.BLUE, Lane.TOP, "INHIB"), Point(1169.0, 4287.0)),
    (TurretRef(Team.BLUE, Lane.MIDDLE, "OUTER"), Point(5846.0, 6396.0)),
    (TurretRef(Team.BLUE, Lane.MIDDLE, "INNER"), Point(5048.0, 4812.0)),
    (TurretRef(Team.BLUE, Lane.MIDDLE, "INHIB"), Point(3651.0, 3696.0)),
    (TurretRef(Team.BLUE, Lane.BOTTOM, "OUTER"), Point(10504.0, 1029.0)),
    (TurretRef(Team.BLUE, Lane.BOTTOM, "INNER"), Point(6919.0, 1483.0)),
    (TurretRef(Team.BLUE, Lane.BOTTOM, "INHIB"), Point(4281.0, 1253.0)),
    (TurretRef(Team.BLUE, Lane.MIDDLE, "NEXUS"), Point(1748.0, 2270.0)),
    (TurretRef(Team.BLUE, Lane.MIDDLE, "NEXUS"), Point(2177.0, 1807.0)),
    (TurretRef(Team.RED, Lane.TOP, "OUTER"), Point(4318.0, 13875.0)),
    (TurretRef(Team.RED, Lane.TOP, "INNER"), Point(7943.0, 13411.0)),
    (TurretRef(Team.RED, Lane.TOP, "INHIB"), Point(10481.0, 13650.0)),
    (TurretRef(Team.RED, Lane.MIDDLE, "OUTER"), Point(8955.0, 8510.0)),
    (TurretRef(Team.RED, Lane.MIDDLE, "INNER"), Point(9767.0, 10113.0)),
    (TurretRef(Team.RED, Lane.MIDDLE, "INHIB"), Point(11134.0, 11207.0)),
    (TurretRef(Team.RED, Lane.BOTTOM, "OUTER"), Point(13866.0, 4505.0)),
    (TurretRef(Team.RED, Lane.BOTTOM, "INNER"), Point(13327.0, 8226.0)),
    (TurretRef(Team.RED, Lane.BOTTOM, "INHIB"), Point(13624.0, 10572.0)),
    (TurretRef(Team.RED, Lane.MIDDLE, "NEXUS"), Point(12650.0, 13084.0)),
    (TurretRef(Team.RED, Lane.MIDDLE, "NEXUS"), Point(13052.0, 12612.0)),
)

_LANE_AXIS: dict[Lane, tuple[Point, Point]] = {
    Lane.TOP: (Point(981.0, 10441.0), Point(4318.0, 13875.0)),
    Lane.MIDDLE: (Point(5846.0, 6396.0), Point(8955.0, 8510.0)),
    Lane.BOTTOM: (Point(10504.0, 1029.0), Point(13866.0, 4505.0)),
}


def distance(a: Point, b: Point) -> float:
    """Return Euclidean distance in world units. Assumes planar SR coordinates."""
    return math.hypot(a.x - b.x, a.y - b.y)


def is_enemy_half(p: Point, team: Team) -> bool:
    """Return True when ``p`` is on the far side of the mid-map diagonal for ``team``.

    Assumes blue occupies the low-(x+y) half (bottom-left fountain) and red the
    high-(x+y) half. Points exactly on the diagonal are not enemy half.
    """
    midpoint = (MAP_X_MAX + MAP_Y_MAX) / 2.0
    on_red_side = (p.x + p.y) > midpoint
    if team is Team.BLUE:
        return on_red_side
    return not on_red_side and (p.x + p.y) < midpoint


def lane_axis_endpoints(lane: Lane) -> tuple[Point, Point]:
    """Return (blue outer turret, red outer turret) anchors for ``lane``."""
    return _LANE_AXIS[lane]


def lane_axis_projection(p: Point, lane: Lane) -> float:
    """Return progress along ``lane`` from blue outer turret (0.0) to red outer (1.0).

    Assumes outer-turret anchors. Values may fall outside [0, 1] behind a tower.
    This axis is team-agnostic; callers playing red should use ``1 - projection``
    if they need "0 = my tower".
    """
    start, end = _LANE_AXIS[lane]
    vx = end.x - start.x
    vy = end.y - start.y
    denom = vx * vx + vy * vy
    if denom == 0:
        return 0.0
    return ((p.x - start.x) * vx + (p.y - start.y) * vy) / denom


def near_turret(p: Point, team: Team) -> TurretRef | None:
    """Return the closest standing-position turret of ``team`` within range, else None.

    Assumes Phase-1 static turret coordinates (destroyed turrets are not tracked
    here) and a 1100-unit "near" radius, slightly larger than outer turret range.
    """
    best: tuple[float, TurretRef] | None = None
    for ref, loc in _TURRETS:
        if ref.team is not team:
            continue
        dist = distance(p, loc)
        if dist > _NEAR_TURRET_RANGE:
            continue
        if best is None or dist < best[0]:
            best = (dist, ref)
    return None if best is None else best[1]


def zone_of(p: Point) -> Zone:
    """Return the highest-priority named zone containing ``p``, or a nearest fallback.

    Assumes ``zones.json`` polygons are in world coordinates. Points inside the
    calibrated map rectangle that miss every polygon snap to the nearest zone so
    on-map events are never UNKNOWN. Off-map points return UNKNOWN.
    """
    polygons = _zone_polygons()
    hits = [zone for zone in _ZONE_PRIORITY if _point_in_polygon(p, polygons[zone])]
    if hits:
        return Zone(hits[0])
    if _in_map_bounds(p):
        nearest_name = min(polygons, key=lambda name: _distance_to_polygon(p, polygons[name]))
        return Zone(nearest_name)
    return Zone.UNKNOWN


def zone_polygons() -> Mapping[str, tuple[Point, ...]]:
    """Return zone name → polygon vertices. Assumes zones.json is present and valid."""
    return _zone_polygons()


def _in_map_bounds(p: Point) -> bool:
    return MAP_X_MIN <= p.x <= MAP_X_MAX and MAP_Y_MIN <= p.y <= MAP_Y_MAX


@lru_cache(maxsize=1)
def _zone_polygons() -> dict[str, tuple[Point, ...]]:
    raw = json.loads(_ZONES_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("zones.json must be an object of name → polygon")
    polygons: dict[str, tuple[Point, ...]] = {}
    for name in _ZONE_PRIORITY:
        coords = raw.get(name)
        if not isinstance(coords, list) or len(coords) < 3:
            raise ValueError(f"zones.json missing polygon for {name}")
        polygons[name] = tuple(Point(float(x), float(y)) for x, y in coords)
    return polygons


def _point_in_polygon(p: Point, polygon: Sequence[Point]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i, vertex in enumerate(polygon):
        vi = vertex
        vj = polygon[j]
        intersects = (vi.y > p.y) != (vj.y > p.y) and p.x < (vj.x - vi.x) * (p.y - vi.y) / (
            (vj.y - vi.y) or 1e-12
        ) + vi.x
        if intersects:
            inside = not inside
        j = i
    return inside


def _distance_to_polygon(p: Point, polygon: Sequence[Point]) -> float:
    if _point_in_polygon(p, polygon):
        return 0.0
    best = math.inf
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        best = min(best, _distance_to_segment(p, start, end))
    return best


def _distance_to_segment(p: Point, a: Point, b: Point) -> float:
    vx, vy = b.x - a.x, b.y - a.y
    length_sq = vx * vx + vy * vy
    if length_sq == 0:
        return distance(p, a)
    t = max(0.0, min(1.0, ((p.x - a.x) * vx + (p.y - a.y) * vy) / length_sq))
    return distance(p, Point(a.x + t * vx, a.y + t * vy))
