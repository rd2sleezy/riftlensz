from __future__ import annotations

from collections.abc import Sequence

from riftlens.analysis.metrics.base import (
    BaselineTable,
    MetricComputer,
    MetricContext,
    MetricValue,
    load_provisional_baselines,
)
from riftlens.analysis.metrics.combat import FightParticipation, ObjectiveParticipation
from riftlens.analysis.metrics.economy import DamageGoldEfficiency, DeathCostTotal
from riftlens.analysis.metrics.laning import (
    CsDifferential,
    CsPerMinute,
    GoldDiffCurve,
    XpDifferential,
)
from riftlens.analysis.metrics.risk import DeathLocationClusters, DeathsByPhase
from riftlens.domain.ports import MetricRepository, PatchData
from riftlens.domain.timeline import GameStateTimeline


class MetricEngine:
    """Constructs the H.5 MetricComputer set with shared patch + baseline context."""

    def __init__(self, patch: PatchData, baselines: BaselineTable | None = None) -> None:
        context = MetricContext(patch=patch, baselines=baselines or load_provisional_baselines())
        self._computers: list[MetricComputer] = [
            CsPerMinute(context=context),
            CsDifferential(context=context),
            GoldDiffCurve(context=context),
            XpDifferential(context=context),
            DeathsByPhase(context=context),
            DeathCostTotal(context=context),
            ObjectiveParticipation(context=context),
            FightParticipation(context=context),
            DamageGoldEfficiency(context=context),
            DeathLocationClusters(context=context),
        ]

    @property
    def computers(self) -> Sequence[MetricComputer]:
        return tuple(self._computers)

    def compute(self, gst: GameStateTimeline, pid: int) -> list[MetricValue]:
        """Return all H.5 metric values for ``pid``. Assumes GST is fully built."""
        values: list[MetricValue] = []
        for computer in self._computers:
            values.extend(computer.compute(gst, pid))
        return values


def compute_metrics(
    gst: GameStateTimeline,
    pid: int,
    patch: PatchData,
    baselines: BaselineTable | None = None,
) -> list[MetricValue]:
    """Return H.5 metrics. Assumes analysis reads only ``gst`` plus patch constants."""
    return MetricEngine(patch, baselines).compute(gst, pid)


async def persist_metrics(
    repo: MetricRepository,
    review_id: str,
    values: Sequence[MetricValue],
) -> None:
    """Replace stored metric rows via the H.4 repository. Assumes the review exists."""
    await repo.replace_for_review(review_id, [value.to_record(review_id) for value in values])
