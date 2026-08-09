from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from riftlens.analysis.features._query import cs_total, facts_for
from riftlens.analysis.metrics.base import MetricContext, MetricValue, RequiredInputs, emit
from riftlens.domain.enums import DataTier, FactKind, GamePhase
from riftlens.domain.fact import Fact
from riftlens.domain.timeline import GameStateTimeline

_CS_MARKS_MS: tuple[tuple[str, int], ...] = (("5", 300_000), ("10", 600_000), ("14", 840_000))


@dataclass
class CsPerMinute:
    id: str = "M-01"
    concept_id: str = "LANING.FARM"
    requires: RequiredInputs = RequiredInputs(
        fact_kinds=(FactKind.CS,),
        data_tiers=(DataTier.RIOT_ONLY,),
    )
    phases: tuple[GamePhase, ...] = (GamePhase.EARLY, GamePhase.MID, GamePhase.LATE)
    context: MetricContext | None = None

    def compute(self, gst: GameStateTimeline, pid: int) -> list[MetricValue]:
        """Return CS/min by phase using frame-boundary CS facts. Assumes CS frames exist."""
        ctx = _require(self.context)
        series = list(facts_for(gst, FactKind.CS, pid))
        if len(series) < 2:
            return []
        role = gst.role_of(pid)
        out: list[MetricValue] = []
        for phase in self.phases:
            window = [fact for fact in series if gst.phase(fact.t_ms) is phase]
            if len(window) < 2:
                continue
            first, last = window[0], window[-1]
            minutes = (last.t_ms - first.t_ms) / 60_000.0
            if minutes <= 0:
                continue
            rate = (cs_total(last.payload) - cs_total(first.payload)) / minutes
            out.append(
                emit(
                    self.id,
                    rate,
                    "cs_per_min",
                    phase=phase,
                    confidence=1.0,
                    context=ctx,
                    role=role,
                    band_key=phase.value,
                    sample_context=f"frames {first.t_ms}-{last.t_ms}",
                    detail={
                        "cs_start": cs_total(first.payload),
                        "cs_end": cs_total(last.payload),
                        "t_start_ms": first.t_ms,
                        "t_end_ms": last.t_ms,
                    },
                )
            )
        return out


@dataclass
class CsDifferential:
    id: str = "M-02"
    concept_id: str = "LANING.FARM"
    requires: RequiredInputs = RequiredInputs(fact_kinds=(FactKind.CS,))
    phases: tuple[GamePhase, ...] = (GamePhase.EARLY,)
    context: MetricContext | None = None

    def compute(self, gst: GameStateTimeline, pid: int) -> list[MetricValue]:
        """Return CS diff vs lane opponent at 5/10/14. Assumes nearest CS frame to each mark."""
        ctx = _require(self.context)
        opponent = gst.lane_opponent(pid)
        if opponent is None:
            return [
                emit(
                    self.id,
                    0.0,
                    "cs",
                    phase=None,
                    confidence=0.2,
                    context=ctx,
                    role=gst.role_of(pid),
                    band_key="5",
                    sample_context="no lane opponent",
                    detail={"reason": "no_lane_opponent"},
                )
            ]
        mine = list(facts_for(gst, FactKind.CS, pid))
        theirs = list(facts_for(gst, FactKind.CS, opponent))
        out: list[MetricValue] = []
        for label, mark in _CS_MARKS_MS:
            left = _nearest(mine, mark)
            right = _nearest(theirs, mark)
            if left is None or right is None:
                continue
            diff = float(cs_total(left.payload) - cs_total(right.payload))
            out.append(
                emit(
                    self.id,
                    diff,
                    "cs",
                    phase=label,
                    confidence=1.0,
                    context=ctx,
                    role=gst.role_of(pid),
                    band_key=label,
                    sample_context=f"nearest frames {left.t_ms}/{right.t_ms} vs pid {opponent}",
                    detail={
                        "mark_ms": mark,
                        "player_cs": cs_total(left.payload),
                        "opponent_cs": cs_total(right.payload),
                        "opponent_pid": opponent,
                        "player_frame_ms": left.t_ms,
                        "opponent_frame_ms": right.t_ms,
                    },
                )
            )
        return out


@dataclass
class GoldDiffCurve:
    id: str = "M-03"
    concept_id: str = "ECONOMY.INCOME"
    requires: RequiredInputs = RequiredInputs(fact_kinds=(FactKind.GOLD, FactKind.CHAMPION_KILL))
    phases: tuple[GamePhase, ...] = (GamePhase.EARLY, GamePhase.MID, GamePhase.LATE)
    context: MetricContext | None = None

    def compute(self, gst: GameStateTimeline, pid: int) -> list[MetricValue]:
        """Return gold-diff curve vs lane opponent plus top-3 swing minutes."""
        ctx = _require(self.context)
        opponent = gst.lane_opponent(pid)
        if opponent is None:
            return []
        mine = {
            fact.t_ms: int(fact.payload.get("totalGold") or 0)
            for fact in facts_for(gst, FactKind.GOLD, pid)
        }
        theirs = {
            fact.t_ms: int(fact.payload.get("totalGold") or 0)
            for fact in facts_for(gst, FactKind.GOLD, opponent)
        }
        times = sorted(set(mine) & set(theirs))
        if len(times) < 2:
            return []
        diffs = [(stamp, mine[stamp] - theirs[stamp]) for stamp in times]
        swings: list[dict[str, Any]] = []
        for index in range(1, len(diffs)):
            prev_t, prev_d = diffs[index - 1]
            stamp, current = diffs[index]
            delta = current - prev_d
            swings.append(
                {
                    "t_start_ms": prev_t,
                    "t_end_ms": stamp,
                    "delta": delta,
                    "attribution": _attribute_swing(gst, pid, opponent, prev_t, stamp),
                }
            )
        swings.sort(key=lambda row: abs(float(row["delta"])), reverse=True)
        top = swings[:3]
        final_diff = float(diffs[-1][1])
        return [
            emit(
                self.id,
                final_diff,
                "gold",
                phase="ALL",
                confidence=1.0,
                context=ctx,
                role=gst.role_of(pid),
                band_key="ALL",
                sample_context=f"final gold diff vs pid {opponent}",
                detail={"curve": diffs, "top_swings": top, "opponent_pid": opponent},
            )
        ]


@dataclass
class XpDifferential:
    id: str = "M-04"
    concept_id: str = "LANING.LEVEL_SPIKES"
    requires: RequiredInputs = RequiredInputs(fact_kinds=(FactKind.XP, FactKind.LEVEL))
    phases: tuple[GamePhase, ...] = (GamePhase.EARLY, GamePhase.MID, GamePhase.LATE)
    context: MetricContext | None = None

    def compute(self, gst: GameStateTimeline, pid: int) -> list[MetricValue]:
        """Return XP diff samples and time spent at level deficit ≥1 / ≥2."""
        ctx = _require(self.context)
        opponent = gst.lane_opponent(pid)
        if opponent is None:
            return []
        my_levels = list(facts_for(gst, FactKind.LEVEL, pid))
        their_levels = {
            fact.t_ms: int(fact.payload.get("level") or 0)
            for fact in facts_for(gst, FactKind.LEVEL, opponent)
        }
        deficit1 = 0
        deficit2 = 0
        xp_curve: list[list[int]] = []
        my_xp = {
            fact.t_ms: int(fact.payload.get("xp") or 0) for fact in facts_for(gst, FactKind.XP, pid)
        }
        their_xp = {
            fact.t_ms: int(fact.payload.get("xp") or 0)
            for fact in facts_for(gst, FactKind.XP, opponent)
        }
        for index, fact in enumerate(my_levels):
            theirs = their_levels.get(fact.t_ms)
            if theirs is None:
                continue
            mine = int(fact.payload.get("level") or 0)
            next_t = my_levels[index + 1].t_ms if index + 1 < len(my_levels) else gst.duration_ms
            span = max(0, next_t - fact.t_ms)
            gap = theirs - mine
            if gap >= 1:
                deficit1 += span
            if gap >= 2:
                deficit2 += span
            if fact.t_ms in my_xp and fact.t_ms in their_xp:
                xp_curve.append([fact.t_ms, my_xp[fact.t_ms] - their_xp[fact.t_ms]])
        role = gst.role_of(pid)
        return [
            emit(
                self.id,
                float(deficit1),
                "ms",
                phase="deficit_ge_1",
                confidence=1.0,
                context=ctx,
                role=role,
                band_key="deficit_ge_1",
                sample_context="time at >=1 level deficit vs lane opponent",
                detail={"xp_curve": xp_curve, "opponent_pid": opponent},
            ),
            emit(
                self.id,
                float(deficit2),
                "ms",
                phase="deficit_ge_2",
                confidence=1.0,
                context=ctx,
                role=role,
                band_key="deficit_ge_2",
                sample_context="time at >=2 level deficit vs lane opponent",
                detail={"opponent_pid": opponent},
            ),
        ]


def _nearest(facts: list[Fact], t_ms: int) -> Fact | None:
    if not facts:
        return None
    return min(facts, key=lambda fact: (abs(fact.t_ms - t_ms), fact.t_ms))


def _attribute_swing(
    gst: GameStateTimeline, pid: int, opponent: int, start_ms: int, end_ms: int
) -> list[str]:
    labels: list[str] = []
    window = (start_ms, end_ms)
    for fact in gst.facts(kind=FactKind.CHAMPION_KILL, window=window):
        victim = fact.payload.get("victimId")
        killer = fact.payload.get("killerId")
        if victim == opponent or killer == pid:
            labels.append(f"kill_t{fact.t_ms}")
        elif victim == pid or killer == opponent:
            labels.append(f"death_t{fact.t_ms}")
    for fact in gst.facts(kind=FactKind.ELITE_MONSTER_KILL, window=window):
        labels.append(f"objective_{fact.payload.get('monsterType')}_{fact.t_ms}")
    for fact in gst.facts(kind=FactKind.TURRET_PLATE_DESTROYED, window=window):
        labels.append(f"plate_{fact.t_ms}")
    return labels or ["unattributed"]


def _require(context: MetricContext | None) -> MetricContext:
    if context is None:
        raise RuntimeError("metric computer is missing MetricContext")
    return context
