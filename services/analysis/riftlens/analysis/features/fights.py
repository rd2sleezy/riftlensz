from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from riftlens.analysis.features._query import point_from_kill, team_of
from riftlens.domain.enums import FactKind, Team
from riftlens.domain.fact import Fact
from riftlens.domain.geometry import Point, distance
from riftlens.domain.timeline import GameStateTimeline

FIGHT_GAP_MS = 20_000
FIGHT_RADIUS_UNITS = 3000.0


@dataclass(frozen=True)
class Fight:
    t_start: int
    t_end: int
    centroid: Point
    participants_by_team: dict[Team, frozenset[int]]
    deaths_in_order: tuple[Fact, ...]
    winner: Team | None


def segment_fights(gst: GameStateTimeline) -> list[Fight]:
    """Cluster CHAMPION_KILL facts into fights (20 s and 3000 units).

    Single-linkage: kills join a cluster when they are within both thresholds of
    any member. Winner is the team that scored more kills; ties are ``None``.
    Assumes kill payloads include ``position``, ``killerId``, ``victimId``.
    """
    kills = [fact for fact in gst.facts(kind=FactKind.CHAMPION_KILL) if point_from_kill(fact)]
    if not kills:
        return []
    clusters = _cluster_kills(kills)
    return [_to_fight(gst, cluster) for cluster in clusters]


def _cluster_kills(kills: list[Fact]) -> list[list[Fact]]:
    assigned = [-1] * len(kills)
    cluster_id = 0
    for index, _kill in enumerate(kills):
        if assigned[index] != -1:
            continue
        assigned[index] = cluster_id
        frontier = [index]
        while frontier:
            current = frontier.pop()
            for other, candidate in enumerate(kills):
                if assigned[other] != -1:
                    continue
                if _near(kills[current], candidate):
                    assigned[other] = cluster_id
                    frontier.append(other)
        cluster_id += 1
    grouped: dict[int, list[Fact]] = defaultdict(list)
    for fact, label in zip(kills, assigned, strict=True):
        grouped[label].append(fact)
    return [grouped[key] for key in sorted(grouped)]


def _near(left: Fact, right: Fact) -> bool:
    if abs(left.t_ms - right.t_ms) > FIGHT_GAP_MS:
        return False
    a = point_from_kill(left)
    b = point_from_kill(right)
    if a is None or b is None:
        return False
    return distance(a, b) <= FIGHT_RADIUS_UNITS


def _to_fight(gst: GameStateTimeline, deaths: list[Fact]) -> Fight:
    ordered = tuple(sorted(deaths, key=lambda fact: (fact.t_ms, fact.payload.get("victimId") or 0)))
    points = [point for fact in ordered if (point := point_from_kill(fact)) is not None]
    centroid = Point(
        sum(point.x for point in points) / len(points),
        sum(point.y for point in points) / len(points),
    )
    by_team: dict[Team, set[int]] = {Team.BLUE: set(), Team.RED: set()}
    kill_counts: dict[Team, int] = {Team.BLUE: 0, Team.RED: 0}
    for fact in ordered:
        for pid in _involved(fact):
            if pid not in gst.participants:
                continue
            by_team[team_of(gst, pid)].add(pid)
        victim = fact.payload.get("victimId")
        if isinstance(victim, int) and victim in gst.participants:
            killer_team = opposing_team(team_of(gst, victim))
            kill_counts[killer_team] += 1
    winner: Team | None
    if kill_counts[Team.BLUE] > kill_counts[Team.RED]:
        winner = Team.BLUE
    elif kill_counts[Team.RED] > kill_counts[Team.BLUE]:
        winner = Team.RED
    else:
        winner = None
    return Fight(
        t_start=ordered[0].t_ms,
        t_end=ordered[-1].t_ms,
        centroid=centroid,
        participants_by_team={team: frozenset(pids) for team, pids in by_team.items()},
        deaths_in_order=ordered,
        winner=winner,
    )


def _involved(fact: Fact) -> list[int]:
    pids: list[int] = []
    for key in ("killerId", "victimId"):
        value = fact.payload.get(key)
        if isinstance(value, int) and value > 0:
            pids.append(value)
    assists = fact.payload.get("assistingParticipantIds")
    if isinstance(assists, list):
        pids.extend(item for item in assists if isinstance(item, int) and item > 0)
    return pids


def opposing_team(team: Team) -> Team:
    """Return the other team. Assumes BLUE/RED."""
    return Team.RED if team is Team.BLUE else Team.BLUE
