from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from riftlens.analysis.features._query import (
    allies_of,
    cs_total,
    facts_for,
    point_from_kill,
    subject,
    team_of,
)
from riftlens.analysis.features.fights import segment_fights
from riftlens.analysis.features.jungle_info import info_age
from riftlens.domain.enums import FactKind, Team
from riftlens.domain.estimate import Estimate, combine
from riftlens.domain.fact import Fact
from riftlens.domain.geometry import Point, Zone, distance, is_enemy_half, near_turret, zone_of
from riftlens.domain.ports import PatchData
from riftlens.domain.timeline import GameStateTimeline

_GANK_INFO_MS = 40_000
_ALLY_RANGE = 2500.0
_FIGHT_WINDOW_MS = 10_000
_FIGHT_CHAMP_THRESHOLD = 4
_CHASE_LOOKBACK_MS = 15_000
_LANE_ZONES = frozenset({Zone.TOP_LANE, Zone.MID_LANE, Zone.BOT_LANE})
_SIDE_ZONES = frozenset(
    {
        Zone.TOP_LANE,
        Zone.BOT_LANE,
        Zone.BLUE_TOP_JUNGLE,
        Zone.BLUE_BOT_JUNGLE,
        Zone.RED_TOP_JUNGLE,
        Zone.RED_BOT_JUNGLE,
    }
)


class DeathCause(StrEnum):
    UNSEEN_GANK = "UNSEEN_GANK"
    KNOWN_GANK = "KNOWN_GANK"
    LOST_TRADE = "LOST_TRADE"
    COLLAPSE = "COLLAPSE"
    TEAMFIGHT = "TEAMFIGHT"
    DIVE = "DIVE"
    CHASE = "CHASE"
    EXECUTE = "EXECUTE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class _DeathFeatures:
    dealers: frozenset[int]
    jungler_in: bool
    jungler_age: Estimate[int] | None
    zone: Zone
    enemy_half: bool
    turret_damage: bool
    fight: bool
    allies_near: int
    chasing: bool
    in_lane: bool
    confidences: tuple[float, ...]


def classify(gst: GameStateTimeline, kill_fact: Fact, patch: PatchData) -> Estimate[DeathCause]:
    """Return M-05 death-cause class for ``kill_fact``.

    Tree inputs: distinct enemy dealers, jungler participation, info ages, death
    zone, turret damage, fight-in-progress, allies within 2500. Missing data
    yields UNKNOWN at low confidence. ``patch`` is reserved for future thresholds.
    """
    del patch
    victim = kill_fact.payload.get("victimId")
    if not isinstance(victim, int) or victim not in gst.participants:
        return Estimate(value=DeathCause.UNKNOWN, confidence=0.2, basis="kill missing victim")
    features = _death_features(gst, kill_fact, victim)
    cause, reason = _tree(features)
    confidence = combine(features.confidences) if features.confidences else 0.35
    if cause is DeathCause.UNKNOWN:
        confidence = min(confidence, 0.35)
    return Estimate(value=cause, confidence=max(0.15, min(1.0, confidence)), basis=reason)


def death_cost(gst: GameStateTimeline, kill_fact: Fact, patch: PatchData) -> Estimate[float]:
    """Return bounty + income lost while dead + CS lost at the player's phase CS rate.

    Respawn duration comes from PatchDataProvider. Assumes ``kill_fact`` is a kill.
    """
    victim = kill_fact.payload.get("victimId")
    if not isinstance(victim, int) or victim not in gst.participants:
        return Estimate(value=0.0, confidence=0.1, basis="kill missing victim")
    bounty = float(kill_fact.payload.get("bounty") or 0)
    shutdown = kill_fact.payload.get("shutdownBounty")
    if isinstance(shutdown, int | float):
        bounty += float(shutdown)
    level_fact = gst.nearest(
        FactKind.LEVEL, kill_fact.t_ms, direction="before", subject=subject(victim)
    )
    level = int(level_fact.payload.get("level") or 1) if level_fact else 1
    respawn = patch.respawn_ms(level, kill_fact.t_ms)
    if respawn is None:
        return Estimate(
            value=bounty,
            confidence=0.25,
            lo=bounty,
            hi=bounty + 800,
            basis="respawn timer unavailable; bounty only",
        )
    income = patch.passive_gold(kill_fact.t_ms, kill_fact.t_ms + respawn)
    cs_rate = _phase_cs_per_ms(gst, victim, kill_fact.t_ms)
    lane_gold = patch.average_cs_gold(jungle=False)
    if lane_gold is None or cs_rate is None:
        return Estimate(
            value=bounty + income,
            confidence=0.45,
            lo=bounty,
            hi=bounty + income + 400,
            basis="death cost without CS-rate term",
        )
    cs_gold = cs_rate * respawn * lane_gold
    total = bounty + income + cs_gold
    return Estimate(
        value=total,
        confidence=0.75,
        lo=bounty + income,
        hi=total * 1.15 + 50.0,
        basis=f"bounty={bounty:.0f} income={income:.0f} cs_gold={cs_gold:.0f} respawn_ms={respawn}",
    )


def _death_features(gst: GameStateTimeline, kill_fact: Fact, victim: int) -> _DeathFeatures:
    dealers = _enemy_dealers(gst, kill_fact, victim)
    team = team_of(gst, victim)
    enemy_jgl = gst.jungler_of(Team.RED if team is Team.BLUE else Team.BLUE)
    jungler_in = enemy_jgl is not None and (
        enemy_jgl in dealers
        or kill_fact.payload.get("killerId") == enemy_jgl
        or enemy_jgl in _assists(kill_fact)
    )
    jungler_age = (
        info_age(gst, team, enemy_jgl, kill_fact.t_ms) if enemy_jgl is not None else None
    )
    point = point_from_kill(kill_fact)
    zone = zone_of(point) if point is not None else Zone.UNKNOWN
    enemy_half = bool(point is not None and is_enemy_half(point, team))
    turret_damage = _has_turret_damage(kill_fact)
    fight = _fight_in_progress(gst, kill_fact)
    allies_near = _allies_within(gst, victim, kill_fact.t_ms, point)
    chasing = _was_chasing(gst, victim, kill_fact.t_ms, point, team)
    confidences = [kill_fact.confidence, 0.85 if point is not None else 0.4]
    if jungler_age is not None:
        confidences.append(jungler_age.confidence)
    return _DeathFeatures(
        dealers=dealers,
        jungler_in=jungler_in,
        jungler_age=jungler_age,
        zone=zone,
        enemy_half=enemy_half,
        turret_damage=turret_damage,
        fight=fight,
        allies_near=allies_near,
        chasing=chasing,
        in_lane=zone in _LANE_ZONES,
        confidences=tuple(confidences),
    )


def _tree(features: _DeathFeatures) -> tuple[DeathCause, str]:
    n_dealers = len(features.dealers)
    if n_dealers == 0:
        return DeathCause.EXECUTE, "no champion damage dealers"
    if features.turret_damage and features.enemy_half and features.allies_near <= 1:
        return DeathCause.DIVE, "turret damage in enemy half with few allies"
    if features.fight and n_dealers >= 2:
        return DeathCause.TEAMFIGHT, "fight in progress with multiple dealers"
    if n_dealers >= 3 and (features.zone in _SIDE_ZONES or features.enemy_half):
        return DeathCause.COLLAPSE, "3+ dealers collapsing a side/exposed position"
    if features.jungler_in:
        age = features.jungler_age.value if features.jungler_age is not None else 10**9
        if age > _GANK_INFO_MS:
            return DeathCause.UNSEEN_GANK, f"jungler in damage; info age {age} ms"
        return DeathCause.KNOWN_GANK, f"jungler in damage; info age {age} ms"
    if features.chasing and n_dealers <= 2:
        return DeathCause.CHASE, "recent aggression then death while exposed"
    if features.in_lane and n_dealers <= 2:
        return DeathCause.LOST_TRADE, "1-2 dealers in lane"
    return DeathCause.UNKNOWN, "no tree branch matched"


def _enemy_dealers(gst: GameStateTimeline, kill_fact: Fact, victim: int) -> frozenset[int]:
    team = team_of(gst, victim)
    found: set[int] = set()
    received = kill_fact.payload.get("victimDamageReceived")
    if isinstance(received, list):
        for entry in received:
            if not isinstance(entry, dict):
                continue
            pid = entry.get("participantId")
            if isinstance(pid, int) and pid > 0 and pid in gst.participants:
                if team_of(gst, pid) is not team:
                    found.add(pid)
    killer = kill_fact.payload.get("killerId")
    if isinstance(killer, int) and killer > 0 and killer in gst.participants:
        if team_of(gst, killer) is not team:
            found.add(killer)
    return frozenset(found)


def _assists(kill_fact: Fact) -> list[int]:
    raw = kill_fact.payload.get("assistingParticipantIds")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, int) and item > 0]


def _has_turret_damage(kill_fact: Fact) -> bool:
    received = kill_fact.payload.get("victimDamageReceived")
    if not isinstance(received, list):
        return False
    for entry in received:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "")
        kind = str(entry.get("type") or "")
        if name.startswith("Turret") or "TOWER" in kind.upper() or kind == "TOWER":
            return True
    return False


def _fight_in_progress(gst: GameStateTimeline, kill_fact: Fact) -> bool:
    fights = segment_fights(gst)
    for fight in fights:
        if kill_fact in fight.deaths_in_order:
            size = sum(len(pids) for pids in fight.participants_by_team.values())
            return size >= _FIGHT_CHAMP_THRESHOLD or len(fight.deaths_in_order) >= 3
    window = (kill_fact.t_ms - _FIGHT_WINDOW_MS, kill_fact.t_ms + _FIGHT_WINDOW_MS)
    involved: set[int] = set()
    for fact in gst.facts(kind=FactKind.CHAMPION_KILL, window=window):
        for key in ("killerId", "victimId"):
            value = fact.payload.get(key)
            if isinstance(value, int) and value > 0:
                involved.add(value)
        involved.update(_assists(fact))
    return len(involved) >= _FIGHT_CHAMP_THRESHOLD


def _allies_within(gst: GameStateTimeline, victim: int, t_ms: int, point: Point | None) -> int:
    if point is None:
        return 0
    count = 0
    for ally in allies_of(gst, victim):
        try:
            estimate = gst.interpolate_position(ally, t_ms)
        except KeyError:
            continue
        if distance(estimate.value, point) <= _ALLY_RANGE:
            count += 1
    return count


def _was_chasing(
    gst: GameStateTimeline,
    victim: int,
    t_ms: int,
    point: Point | None,
    team: Team,
) -> bool:
    if point is None:
        return False
    recent_kills = gst.facts(
        kind=FactKind.CHAMPION_KILL,
        window=(t_ms - _CHASE_LOOKBACK_MS, t_ms),
    )
    victim_got_kill = any(fact.payload.get("killerId") == victim for fact in recent_kills)
    enemy = Team.RED if team is Team.BLUE else Team.BLUE
    exposed = is_enemy_half(point, team)
    enemy_tower = near_turret(point, enemy) is not None
    return bool(victim_got_kill and (exposed or enemy_tower))


def _phase_cs_per_ms(gst: GameStateTimeline, pid: int, t_ms: int) -> float | None:
    phase = gst.phase(t_ms)
    series = facts_for(gst, FactKind.CS, pid)
    in_phase = [fact for fact in series if gst.phase(fact.t_ms) is phase]
    if len(in_phase) < 2:
        in_phase = list(series)
    if len(in_phase) < 2:
        return None
    first, last = in_phase[0], in_phase[-1]
    span = last.t_ms - first.t_ms
    if span <= 0:
        return None
    return (cs_total(last.payload) - cs_total(first.payload)) / span
