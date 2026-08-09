from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from riftlens.analysis.features._query import point_from_kill
from riftlens.analysis.features.deaths import classify
from riftlens.analysis.metrics.base import MetricContext, MetricValue, RequiredInputs, emit
from riftlens.domain.enums import DataTier, FactKind, GamePhase
from riftlens.domain.geometry import Point, distance, zone_of
from riftlens.domain.timeline import GameStateTimeline

_DEATH_CLUSTER_EPS = 1500.0
_DEATH_CLUSTER_MIN = 2


@dataclass
class DeathsByPhase:
    id: str = "M-05"
    concept_id: str = "RISK.DEATH_CAUSE"
    requires: RequiredInputs = RequiredInputs(
        fact_kinds=(FactKind.CHAMPION_KILL,),
        features=("deaths.classify", "jungle_info.info_age", "fights.segment_fights"),
        data_tiers=(DataTier.RIOT_DERIVED,),
    )
    phases: tuple[GamePhase, ...] = (GamePhase.EARLY, GamePhase.MID, GamePhase.LATE)
    context: MetricContext | None = None

    def compute(self, gst: GameStateTimeline, pid: int) -> list[MetricValue]:
        """Return deaths/10 min by phase with cause tags. Assumes CHAMPION_KILL facts."""
        ctx = _require(self.context)
        kills = [
            fact
            for fact in gst.facts(kind=FactKind.CHAMPION_KILL)
            if fact.payload.get("victimId") == pid
        ]
        grouped: dict[GamePhase, list[dict[str, Any]]] = {phase: [] for phase in self.phases}
        for fact in kills:
            phase = gst.phase(fact.t_ms)
            estimate = classify(gst, fact, ctx.patch)
            grouped.setdefault(phase, []).append(
                {
                    "t_ms": fact.t_ms,
                    "cause": estimate.value.value,
                    "confidence": estimate.confidence,
                    "basis": estimate.basis,
                }
            )
        role = gst.role_of(pid)
        out: list[MetricValue] = []
        for phase in self.phases:
            rows = grouped.get(phase, [])
            duration = _phase_duration_ms(gst, phase)
            per10 = 0.0 if duration <= 0 else len(rows) / (duration / 600_000.0)
            confidence = 1.0 if not rows else min(float(row["confidence"]) for row in rows)
            out.append(
                emit(
                    self.id,
                    per10,
                    "deaths_per_10",
                    phase=phase,
                    confidence=max(0.2, confidence),
                    context=ctx,
                    role=role,
                    band_key=phase.value,
                    sample_context=f"{len(rows)} deaths in {phase.value}",
                    detail={"deaths": rows, "phase_duration_ms": duration},
                )
            )
        return out


@dataclass
class DeathLocationClusters:
    id: str = "M-22"
    concept_id: str = "RISK.DEATH_LOCATION"
    requires: RequiredInputs = RequiredInputs(fact_kinds=(FactKind.CHAMPION_KILL,))
    phases: tuple[GamePhase, ...] = (GamePhase.EARLY, GamePhase.MID, GamePhase.LATE)
    context: MetricContext | None = None

    def compute(self, gst: GameStateTimeline, pid: int) -> list[MetricValue]:
        """Return DBSCAN clusters of this player's death positions (min 2)."""
        ctx = _require(self.context)
        points: list[tuple[int, Point]] = []
        for fact in gst.facts(kind=FactKind.CHAMPION_KILL):
            if fact.payload.get("victimId") != pid:
                continue
            point = point_from_kill(fact)
            if point is None:
                continue
            points.append((fact.t_ms, point))
        clusters = _dbscan([point for _, point in points], _DEATH_CLUSTER_EPS, _DEATH_CLUSTER_MIN)
        payload = []
        for members in clusters:
            xs = [points[index][1] for index in members]
            centroid = Point(sum(p.x for p in xs) / len(xs), sum(p.y for p in xs) / len(xs))
            payload.append(
                {
                    "size": len(members),
                    "centroid": {"x": centroid.x, "y": centroid.y},
                    "zone": zone_of(centroid).value,
                    "t_ms": [points[index][0] for index in members],
                }
            )
        return [
            emit(
                self.id,
                float(len(payload)),
                "count",
                phase="ALL",
                confidence=1.0 if points else 0.3,
                context=ctx,
                role=gst.role_of(pid),
                band_key="ALL",
                sample_context=f"{len(points)} located deaths -> {len(payload)} clusters",
                detail={"clusters": payload, "eps": _DEATH_CLUSTER_EPS},
            )
        ]


def _phase_duration_ms(gst: GameStateTimeline, phase: GamePhase) -> int:
    stamps = [0, gst.duration_ms]
    gold_facts = gst.facts(kind=FactKind.GOLD)
    stamps.extend(fact.t_ms for fact in gold_facts if fact.subject.kind == "participant")
    unique = sorted(set(stamps))
    total = 0
    for index in range(1, len(unique)):
        mid = (unique[index - 1] + unique[index]) // 2
        if gst.phase(mid) is phase:
            total += unique[index] - unique[index - 1]
    return total


def _dbscan(points: list[Point], eps: float, min_samples: int) -> list[list[int]]:
    labels = [-1] * len(points)

    def neighbors(index: int) -> list[int]:
        return [
            other
            for other, point in enumerate(points)
            if distance(points[index], point) <= eps
        ]

    cluster_id = 0
    for index, _point in enumerate(points):
        if labels[index] != -1:
            continue
        neigh = neighbors(index)
        if len(neigh) < min_samples:
            labels[index] = -2
            continue
        labels[index] = cluster_id
        seeds = [other for other in neigh if other != index]
        cursor = 0
        while cursor < len(seeds):
            other = seeds[cursor]
            if labels[other] == -2:
                labels[other] = cluster_id
            if labels[other] != -1:
                cursor += 1
                continue
            labels[other] = cluster_id
            extra = neighbors(other)
            if len(extra) >= min_samples:
                for member in extra:
                    if member not in seeds:
                        seeds.append(member)
            cursor += 1
        cluster_id += 1
    grouped: dict[int, list[int]] = defaultdict(list)
    for index, label in enumerate(labels):
        if label >= 0:
            grouped[label].append(index)
    return [grouped[key] for key in sorted(grouped)]


def _require(context: MetricContext | None) -> MetricContext:
    if context is None:
        raise RuntimeError("metric computer is missing MetricContext")
    return context
