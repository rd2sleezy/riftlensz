from __future__ import annotations

from dataclasses import dataclass

from riftlens.analysis.features._query import facts_for, subject, team_of
from riftlens.analysis.features.fights import Fight, segment_fights
from riftlens.analysis.metrics.base import MetricContext, MetricValue, RequiredInputs, emit
from riftlens.domain.enums import DataTier, FactKind, GamePhase, Team
from riftlens.domain.fact import Fact
from riftlens.domain.geometry import Point, distance
from riftlens.domain.ports import PatchData
from riftlens.domain.timeline import GameStateTimeline

_OBJECTIVE_RANGE = 4500.0
_PIT_POINTS = {
    "DRAGON": Point(9866.0, 4414.0),
    "BARON_NASHOR": Point(5007.0, 10471.0),
    "RIFTHERALD": Point(4950.0, 10420.0),
}


@dataclass
class ObjectiveParticipation:
    id: str = "M-15"
    concept_id: str = "MACRO.OBJECTIVES"
    requires: RequiredInputs = RequiredInputs(
        fact_kinds=(FactKind.ELITE_MONSTER_KILL, FactKind.CHAMPION_KILL, FactKind.POSITION),
        data_tiers=(DataTier.RIOT_DERIVED,),
    )
    phases: tuple[GamePhase, ...] = (GamePhase.EARLY, GamePhase.MID, GamePhase.LATE)
    context: MetricContext | None = None

    def compute(self, gst: GameStateTimeline, pid: int) -> list[MetricValue]:
        """Return contest-weighted elite-monster participation. Assumes ELITE_MONSTER_KILL facts."""
        ctx = _require(self.context)
        objectives = list(gst.facts(kind=FactKind.ELITE_MONSTER_KILL))
        contestable = 0
        present = 0
        rows: list[dict[str, object]] = []
        for fact in objectives:
            if not _is_contestable(gst, pid, fact.t_ms, ctx.patch):
                rows.append({"t_ms": fact.t_ms, "contestable": False, "present": False})
                continue
            contestable += 1
            showed = _was_present(gst, pid, fact)
            if showed:
                present += 1
            rows.append(
                {
                    "t_ms": fact.t_ms,
                    "monster": fact.payload.get("monsterType"),
                    "contestable": True,
                    "present": showed,
                }
            )
        rate = float(present / contestable) if contestable else 0.0
        confidence = 0.7 if contestable else 0.3
        return [
            emit(
                self.id,
                rate,
                "ratio",
                phase="ALL",
                confidence=confidence,
                context=ctx,
                role=gst.role_of(pid),
                band_key="ALL",
                sample_context=f"{present}/{contestable} contestable objectives",
                detail={"objectives": rows},
            )
        ]


@dataclass
class FightParticipation:
    id: str = "M-19"
    concept_id: str = "COMBAT.FIGHT_PARTICIPATION"
    requires: RequiredInputs = RequiredInputs(
        fact_kinds=(FactKind.CHAMPION_KILL, FactKind.DAMAGE_ACCUM),
        features=("fights.segment_fights",),
        data_tiers=(DataTier.RIOT_DERIVED,),
    )
    phases: tuple[GamePhase, ...] = (GamePhase.EARLY, GamePhase.MID, GamePhase.LATE)
    context: MetricContext | None = None

    def compute(self, gst: GameStateTimeline, pid: int) -> list[MetricValue]:
        """Return fight participation, damage share, and died-first rate."""
        ctx = _require(self.context)
        fights = segment_fights(gst)
        if not fights:
            return []
        team = team_of(gst, pid)
        attended = 0
        died_first = 0
        shares: list[float] = []
        rows: list[dict[str, object]] = []
        for fight in fights:
            in_fight = pid in fight.participants_by_team.get(team, frozenset())
            if in_fight:
                attended += 1
            first_death = fight.deaths_in_order[0] if fight.deaths_in_order else None
            first_victim = None if first_death is None else first_death.payload.get("victimId")
            if first_victim == pid:
                died_first += 1
            share = _fight_damage_share(gst, pid, team, fight)
            if share is not None:
                shares.append(share)
            rows.append(
                {
                    "t_start_ms": fight.t_start,
                    "t_end_ms": fight.t_end,
                    "present": in_fight,
                    "died_first": first_victim == pid,
                    "damage_share": share,
                    "winner": None if fight.winner is None else fight.winner.value,
                }
            )
        participation = attended / len(fights)
        died_first_rate = died_first / len(fights)
        avg_share = sum(shares) / len(shares) if shares else 0.0
        role = gst.role_of(pid)
        return [
            emit(
                self.id,
                participation,
                "ratio",
                phase="participation",
                confidence=0.7,
                context=ctx,
                role=role,
                band_key="participation",
                sample_context=f"{attended}/{len(fights)} fights",
                detail={"fights": rows, "avg_damage_share": avg_share},
            ),
            emit(
                self.id,
                died_first_rate,
                "ratio",
                phase="died_first",
                confidence=0.75,
                context=ctx,
                role=role,
                band_key="died_first",
                sample_context=f"died first in {died_first}/{len(fights)} fights",
                detail={"avg_damage_share": avg_share},
            ),
        ]


def _is_contestable(gst: GameStateTimeline, pid: int, t_ms: int, patch: PatchData) -> bool:
    team = team_of(gst, pid)
    dead_allies = 0
    player_dead = False
    for fact in gst.facts(kind=FactKind.CHAMPION_KILL, window=(0, t_ms)):
        victim = fact.payload.get("victimId")
        if not isinstance(victim, int) or victim not in gst.participants:
            continue
        if gst.participants[victim].team is not team:
            continue
        respawn_end = _respawn_end(gst, fact, patch)
        if respawn_end > t_ms:
            dead_allies += 1
            if victim == pid:
                player_dead = True
    if player_dead:
        return False
    return dead_allies < 2


def _respawn_end(gst: GameStateTimeline, kill: Fact, patch: PatchData) -> int:
    victim = kill.payload.get("victimId")
    level = 1
    if isinstance(victim, int):
        level_fact = gst.nearest(
            FactKind.LEVEL, kill.t_ms, direction="before", subject=subject(victim)
        )
        if level_fact is not None:
            level = int(level_fact.payload.get("level") or 1)
    duration = patch.respawn_ms(level, kill.t_ms)
    return kill.t_ms + (duration if duration is not None else 0)


def _was_present(gst: GameStateTimeline, pid: int, fact: Fact) -> bool:
    if fact.payload.get("killerId") == pid:
        return True
    assists = fact.payload.get("assistingParticipantIds")
    if isinstance(assists, list) and pid in assists:
        return True
    monster = str(fact.payload.get("monsterType") or "")
    pit = _PIT_POINTS.get(monster)
    if pit is None and "DRAGON" in monster:
        pit = _PIT_POINTS["DRAGON"]
    if pit is None:
        pit = _PIT_POINTS["BARON_NASHOR"]
    try:
        estimate = gst.interpolate_position(pid, fact.t_ms)
    except KeyError:
        return False
    return distance(estimate.value, pit) <= _OBJECTIVE_RANGE


def _fight_damage_share(
    gst: GameStateTimeline, pid: int, team: Team, fight: Fight
) -> float | None:
    start = max(0, fight.t_start - 60_000)
    end = fight.t_end + 60_000
    team_delta = 0.0
    player_delta = 0.0
    for member, info in gst.participants.items():
        if info.team is not team:
            continue
        delta = _damage_delta(gst, member, start, end)
        if delta is None:
            continue
        team_delta += delta
        if member == pid:
            player_delta = delta
    if team_delta <= 0:
        return None
    return player_delta / team_delta


def _damage_delta(gst: GameStateTimeline, pid: int, start_ms: int, end_ms: int) -> float | None:
    series = list(facts_for(gst, FactKind.DAMAGE_ACCUM, pid))
    if not series:
        return None
    before = [fact for fact in series if fact.t_ms <= start_ms]
    after = [fact for fact in series if fact.t_ms <= end_ms]
    if not after:
        return None
    left = before[-1] if before else series[0]
    right = after[-1]
    return float(right.payload.get("totalDamageDoneToChampions") or 0) - float(
        left.payload.get("totalDamageDoneToChampions") or 0
    )


def _require(context: MetricContext | None) -> MetricContext:
    if context is None:
        raise RuntimeError("metric computer is missing MetricContext")
    return context
