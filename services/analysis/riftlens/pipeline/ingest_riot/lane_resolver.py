from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

import structlog

from riftlens.adapters.riot.models import MatchDto, ParticipantDto, TimelineDto
from riftlens.domain.enums import Lane, Role, Team
from riftlens.domain.geometry import Point, distance, lane_axis_endpoints, lane_axis_projection

log = structlog.get_logger("riftlens.pipeline.ingest_riot.lane_resolver")

_VALID_POSITIONS = {role.value for role in Role if role is not Role.UNKNOWN}
_JUNGLE_AXIS_DISTANCE = 2200.0
_CLUSTER_FRAMES = (1, 8)


@dataclass(frozen=True)
class LaneAssignment:
    method: str
    roles: Mapping[int, Role]
    opponents: Mapping[int, int | None]


def resolve_lanes(
    match: MatchDto,
    timeline: TimelineDto,
    *,
    trust_match_positions: bool = True,
) -> LaneAssignment:
    """Return per-pid roles and lane opponents.

    Prefers matching ``teamPosition`` across teams when every participant has a
    valid position and ``trust_match_positions`` is true. Otherwise clusters mean
    position over timeline frames 1–8 onto three lane axes plus jungle.
    Assumes participant ids are consistent between match and timeline.
    """
    if trust_match_positions and _all_positions_valid(match.info.participants):
        assignment = _from_team_positions(match.info.participants)
        log.info("lane_resolver_method", method=assignment.method)
        return assignment
    assignment = _from_position_cluster(match, timeline)
    log.info("lane_resolver_method", method=assignment.method)
    return assignment


def _all_positions_valid(participants: list[ParticipantDto]) -> bool:
    if len(participants) < 2:
        return False
    for participant in participants:
        position = (participant.team_position or "").strip()
        if position not in _VALID_POSITIONS or position == Role.UNKNOWN:
            return False
    return True


def _from_team_positions(participants: list[ParticipantDto]) -> LaneAssignment:
    roles = {p.participant_id: Role(p.team_position.strip()) for p in participants}
    teams = {p.participant_id: Team(p.team_id) for p in participants}
    opponents = _opponents_by_role(roles, teams)
    return LaneAssignment(method="team_position", roles=roles, opponents=opponents)


def _from_position_cluster(match: MatchDto, timeline: TimelineDto) -> LaneAssignment:
    means = _mean_positions(timeline, start=_CLUSTER_FRAMES[0], end=_CLUSTER_FRAMES[1])
    jungle_cs, lane_cs = _early_cs(timeline, start=_CLUSTER_FRAMES[0], end=_CLUSTER_FRAMES[1])
    teams = _teams_from_spawns(match, timeline)
    roles: dict[int, Role] = {}
    for pid, point in means.items():
        if jungle_cs.get(pid, 0) > lane_cs.get(pid, 0) and jungle_cs.get(pid, 0) >= 8:
            roles[pid] = Role.JUNGLE
            continue
        nearest_lane, dist = _nearest_lane_axis(point)
        if dist > _JUNGLE_AXIS_DISTANCE:
            roles[pid] = Role.JUNGLE
        else:
            roles[pid] = _lane_to_role(nearest_lane)
    _split_bot_pairs(roles, teams, lane_cs)
    _ensure_one_jungler(roles, teams, jungle_cs, means)
    for pid in teams:
        roles.setdefault(pid, Role.UNKNOWN)
    opponents = _opponents_by_role(roles, teams)
    return LaneAssignment(method="position_cluster", roles=roles, opponents=opponents)


def _mean_positions(timeline: TimelineDto, *, start: int, end: int) -> dict[int, Point]:
    sums: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    frames = timeline.info.frames[start : end + 1]
    for frame in frames:
        for raw_pid, pframe in frame.participant_frames.items():
            if pframe.position is None:
                continue
            pid = pframe.participant_id if pframe.participant_id is not None else int(raw_pid)
            sums[pid][0] += float(pframe.position.x)
            sums[pid][1] += float(pframe.position.y)
            sums[pid][2] += 1.0
    return {
        pid: Point(vals[0] / vals[2], vals[1] / vals[2]) for pid, vals in sums.items() if vals[2]
    }


def _early_cs(
    timeline: TimelineDto, *, start: int, end: int
) -> tuple[dict[int, int], dict[int, int]]:
    jungle: dict[int, int] = defaultdict(int)
    lane: dict[int, int] = defaultdict(int)
    last = timeline.info.frames[min(end, len(timeline.info.frames) - 1)]
    for raw_pid, pframe in last.participant_frames.items():
        pid = pframe.participant_id if pframe.participant_id is not None else int(raw_pid)
        jungle[pid] = int(pframe.jungle_minions_killed)
        lane[pid] = int(pframe.minions_killed)
    return dict(jungle), dict(lane)


def _teams_from_spawns(match: MatchDto, timeline: TimelineDto) -> dict[int, Team]:
    if timeline.info.frames:
        first = timeline.info.frames[0]
        teams: dict[int, Team] = {}
        for raw_pid, pframe in first.participant_frames.items():
            pid = pframe.participant_id if pframe.participant_id is not None else int(raw_pid)
            if pframe.position is None:
                continue
            spawn = Point(float(pframe.position.x), float(pframe.position.y))
            teams[pid] = Team.BLUE if spawn.x + spawn.y < 8000 else Team.RED
        if len(teams) >= 2:
            return teams
    return {p.participant_id: Team(p.team_id) for p in match.info.participants}


def _nearest_lane_axis(point: Point) -> tuple[Lane, float]:
    best: tuple[Lane, float] | None = None
    for lane in (Lane.TOP, Lane.MIDDLE, Lane.BOTTOM):
        proj = min(1.0, max(0.0, lane_axis_projection(point, lane)))
        # Reconstruct the clamped axis point from blue/red outers via projection.
        start_end = lane_axis_endpoints(lane)
        axis_pt = Point(
            start_end[0].x + (start_end[1].x - start_end[0].x) * proj,
            start_end[0].y + (start_end[1].y - start_end[0].y) * proj,
        )
        dist = distance(point, axis_pt)
        if best is None or dist < best[1]:
            best = (lane, dist)
    assert best is not None
    return best


def _lane_to_role(lane: Lane) -> Role:
    if lane is Lane.TOP:
        return Role.TOP
    if lane is Lane.MIDDLE:
        return Role.MIDDLE
    return Role.BOTTOM


def _split_bot_pairs(
    roles: dict[int, Role], teams: Mapping[int, Team], lane_cs: Mapping[int, int]
) -> None:
    for team in (Team.BLUE, Team.RED):
        bots = [
            pid
            for pid, role in roles.items()
            if role is Role.BOTTOM and teams.get(pid) is team
        ]
        if len(bots) < 2:
            continue
        bots.sort(key=lambda pid: lane_cs.get(pid, 0), reverse=True)
        roles[bots[0]] = Role.BOTTOM
        for pid in bots[1:]:
            roles[pid] = Role.UTILITY


def _ensure_one_jungler(
    roles: dict[int, Role],
    teams: Mapping[int, Team],
    jungle_cs: Mapping[int, int],
    means: Mapping[int, Point],
) -> None:
    for team in (Team.BLUE, Team.RED):
        junglers = [
            pid for pid, role in roles.items() if role is Role.JUNGLE and teams.get(pid) is team
        ]
        if len(junglers) == 1:
            continue
        if len(junglers) > 1:
            junglers.sort(key=lambda pid: jungle_cs.get(pid, 0), reverse=True)
            roles[junglers[0]] = Role.JUNGLE
            for pid in junglers[1:]:
                roles[pid] = _lane_to_role(_nearest_lane_axis(means[pid])[0])
            continue
        candidates = [pid for pid, team_id in teams.items() if team_id is team]
        if not candidates:
            continue
        best = max(candidates, key=lambda pid: jungle_cs.get(pid, 0))
        if jungle_cs.get(best, 0) > 0:
            roles[best] = Role.JUNGLE


def _opponents_by_role(
    roles: Mapping[int, Role], teams: Mapping[int, Team]
) -> dict[int, int | None]:
    by_role_team: dict[tuple[Role, Team], list[int]] = defaultdict(list)
    for pid, role in roles.items():
        team = teams.get(pid)
        if team is None or role is Role.UNKNOWN:
            continue
        by_role_team[(role, team)].append(pid)
    opponents: dict[int, int | None] = {}
    for pid, role in roles.items():
        team = teams.get(pid)
        opponents[pid] = None
        if team is None or role is Role.UNKNOWN:
            continue
        enemy = Team.RED if team is Team.BLUE else Team.BLUE
        rivals = by_role_team.get((role, enemy), [])
        opponents[pid] = rivals[0] if len(rivals) == 1 else None
    return opponents
