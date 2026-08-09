from __future__ import annotations

from dataclasses import dataclass

from riftlens.analysis.features._query import last_numeric, team_of
from riftlens.analysis.features.deaths import death_cost
from riftlens.analysis.metrics.base import MetricContext, MetricValue, RequiredInputs, emit
from riftlens.domain.enums import DataTier, FactKind, GamePhase
from riftlens.domain.timeline import GameStateTimeline


@dataclass
class DeathCostTotal:
    id: str = "M-07"
    concept_id: str = "RISK.DEATH_COST"
    requires: RequiredInputs = RequiredInputs(
        fact_kinds=(FactKind.CHAMPION_KILL, FactKind.CS, FactKind.LEVEL),
        features=("deaths.death_cost",),
        data_tiers=(DataTier.RIOT_DERIVED,),
    )
    phases: tuple[GamePhase, ...] = (GamePhase.EARLY, GamePhase.MID, GamePhase.LATE)
    context: MetricContext | None = None

    def compute(self, gst: GameStateTimeline, pid: int) -> list[MetricValue]:
        """Return total death cost (bounty + dead time + CS lost). Assumes kills are in GST."""
        ctx = _require(self.context)
        kills = [
            fact
            for fact in gst.facts(kind=FactKind.CHAMPION_KILL)
            if fact.payload.get("victimId") == pid
        ]
        if not kills:
            return [
                emit(
                    self.id,
                    0.0,
                    "gold",
                    phase="ALL",
                    confidence=1.0,
                    context=ctx,
                    role=gst.role_of(pid),
                    band_key="ALL",
                    sample_context="no deaths",
                    detail={"deaths": []},
                )
            ]
        total = 0.0
        confidences: list[float] = []
        details: list[dict[str, object]] = []
        for fact in kills:
            estimate = death_cost(gst, fact, ctx.patch)
            total += float(estimate.value)
            confidences.append(estimate.confidence)
            details.append({"t_ms": fact.t_ms, "cost": estimate.value, "basis": estimate.basis})
        confidence = min(confidences) if confidences else 0.4
        return [
            emit(
                self.id,
                total,
                "gold",
                phase="ALL",
                confidence=confidence,
                context=ctx,
                role=gst.role_of(pid),
                band_key="ALL",
                sample_context=f"{len(kills)} deaths",
                detail={"deaths": details},
            )
        ]


@dataclass
class DamageGoldEfficiency:
    id: str = "M-20"
    concept_id: str = "COMBAT.DAMAGE_EFFICIENCY"
    requires: RequiredInputs = RequiredInputs(
        fact_kinds=(FactKind.DAMAGE_ACCUM, FactKind.GOLD),
        data_tiers=(DataTier.RIOT_ONLY,),
    )
    phases: tuple[GamePhase, ...] = (GamePhase.LATE,)
    context: MetricContext | None = None

    def compute(self, gst: GameStateTimeline, pid: int) -> list[MetricValue]:
        """Return damage share ÷ gold share from GST end-state totals (not match.json)."""
        ctx = _require(self.context)
        team = team_of(gst, pid)
        team_pids = [other for other, info in gst.participants.items() if info.team is team]
        damages: dict[int, float] = {}
        golds: dict[int, float] = {}
        for member in team_pids:
            dmg = last_numeric(gst, FactKind.DAMAGE_ACCUM, member, "totalDamageDoneToChampions")
            gold = last_numeric(gst, FactKind.GOLD, member, "totalGold")
            if dmg is not None:
                damages[member] = dmg.value
            if gold is not None:
                golds[member] = gold.value
        team_dmg = sum(damages.values())
        team_gold = sum(golds.values())
        player_dmg = damages.get(pid, 0.0)
        player_gold = golds.get(pid, 0.0)
        if team_dmg <= 0 or team_gold <= 0 or player_gold <= 0:
            return [
                emit(
                    self.id,
                    0.0,
                    "ratio",
                    phase="ALL",
                    confidence=0.2,
                    context=ctx,
                    role=gst.role_of(pid),
                    band_key="ALL",
                    sample_context="insufficient GST gold/damage totals",
                    detail={"reason": "missing_totals"},
                )
            ]
        dmg_share = player_dmg / team_dmg
        gold_share = player_gold / team_gold
        value = dmg_share / gold_share
        return [
            emit(
                self.id,
                value,
                "ratio",
                phase="ALL",
                confidence=0.85,
                context=ctx,
                role=gst.role_of(pid),
                band_key="ALL",
                sample_context="GST end-frame damage and totalGold shares",
                detail={
                    "damage_share": dmg_share,
                    "gold_share": gold_share,
                    "player_damage": player_dmg,
                    "player_gold": player_gold,
                    "team_damage": team_dmg,
                    "team_gold": team_gold,
                },
            )
        ]


def _require(context: MetricContext | None) -> MetricContext:
    if context is None:
        raise RuntimeError("metric computer is missing MetricContext")
    return context
