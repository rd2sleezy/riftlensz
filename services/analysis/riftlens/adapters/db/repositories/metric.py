from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from riftlens.adapters.db.models import BaselineStatRow, ChampionProfileRow, MetricValueRow
from riftlens.adapters.db.repositories.base import SessionRepository
from riftlens.domain.ports import BaselineStatRecord, ChampionProfileRecord, MetricValueRecord


class SqlMetricRepository(SessionRepository):
    async def replace_for_review(self, review_id: str, rows: Sequence[MetricValueRecord]) -> None:
        """Replace metric values for a review. Assumes the review exists."""

        def work(session: Session) -> None:
            session.execute(delete(MetricValueRow).where(MetricValueRow.review_id == review_id))
            for row in rows:
                session.add(_metric_row(row))

        await self.call(work)

    async def list_for_review(self, review_id: str) -> Sequence[MetricValueRecord]:
        """Return metric values for a review. Assumes the review may be missing."""

        def work(session: Session) -> list[MetricValueRecord]:
            found = session.scalars(
                select(MetricValueRow)
                .where(MetricValueRow.review_id == review_id)
                .order_by(MetricValueRow.metric_id, MetricValueRow.id)
            ).all()
            return [_metric_record(row) for row in found]

        return await self.call(work)

    async def upsert_baseline(self, row: BaselineStatRecord) -> None:
        """Insert or replace a corpus baseline cell. Assumes keys match the PK."""
        await self.call(lambda session: session.merge(_baseline_row(row)))

    async def get_baseline(
        self,
        metric_id: str,
        tier: str,
        role: str,
        champion_class: str,
        patch: str,
        phase: str,
    ) -> BaselineStatRecord | None:
        """Return one baseline cell or None. Assumes the six-part PK is complete."""

        def work(session: Session) -> BaselineStatRecord | None:
            found = session.get(
                BaselineStatRow, (metric_id, tier, role, champion_class, patch, phase)
            )
            return None if found is None else _baseline_record(found)

        return await self.call(work)

    async def upsert_champion_profile(self, row: ChampionProfileRecord) -> None:
        """Insert or replace patch-scoped champion reference data. Assumes PK is set."""
        await self.call(lambda session: session.merge(_champ_row(row)))

    async def get_champion_profile(
        self, champion_id: int, patch: str
    ) -> ChampionProfileRecord | None:
        """Return champion reference data or None. Assumes ``patch`` is normalized."""

        def work(session: Session) -> ChampionProfileRecord | None:
            found = session.get(ChampionProfileRow, (champion_id, patch))
            return None if found is None else _champ_record(found)

        return await self.call(work)


def _metric_row(row: MetricValueRecord) -> MetricValueRow:
    return MetricValueRow(
        review_id=row.review_id,
        metric_id=row.metric_id,
        phase=row.phase,
        value=row.value,
        unit=row.unit,
        confidence=row.confidence,
        baseline_key=row.baseline_key,
        baseline_p50=row.baseline_p50,
        baseline_percentile=row.baseline_percentile,
        detail_json=row.detail_json,
    )


def _metric_record(row: MetricValueRow) -> MetricValueRecord:
    return MetricValueRecord(
        id=row.id,
        review_id=row.review_id,
        metric_id=row.metric_id,
        phase=row.phase,
        value=row.value,
        unit=row.unit,
        confidence=row.confidence,
        baseline_key=row.baseline_key,
        baseline_p50=row.baseline_p50,
        baseline_percentile=row.baseline_percentile,
        detail_json=row.detail_json,
    )


def _baseline_row(row: BaselineStatRecord) -> BaselineStatRow:
    return BaselineStatRow(
        metric_id=row.metric_id,
        tier=row.tier,
        role=row.role,
        champion_class=row.champion_class,
        patch=row.patch,
        phase=row.phase,
        n=row.n,
        p10=row.p10,
        p25=row.p25,
        p50=row.p50,
        p75=row.p75,
        p90=row.p90,
        mean=row.mean,
        stddev=row.stddev,
        updated_at=row.updated_at,
    )


def _baseline_record(row: BaselineStatRow) -> BaselineStatRecord:
    return BaselineStatRecord(
        metric_id=row.metric_id,
        tier=row.tier,
        role=row.role,
        champion_class=row.champion_class,
        patch=row.patch,
        phase=row.phase,
        n=row.n,
        p10=row.p10,
        p25=row.p25,
        p50=row.p50,
        p75=row.p75,
        p90=row.p90,
        mean=row.mean,
        stddev=row.stddev,
        updated_at=row.updated_at,
    )


def _champ_row(row: ChampionProfileRecord) -> ChampionProfileRow:
    return ChampionProfileRow(
        champion_id=row.champion_id,
        patch=row.patch,
        name=row.name,
        class_tags=row.class_tags,
        behavior_tags=row.behavior_tags,
        power_spikes=row.power_spikes,
        win_condition=row.win_condition,
        typical_build=row.typical_build,
        abilities=row.abilities,
    )


def _champ_record(row: ChampionProfileRow) -> ChampionProfileRecord:
    return ChampionProfileRecord(
        champion_id=row.champion_id,
        patch=row.patch,
        name=row.name,
        class_tags=row.class_tags,
        behavior_tags=row.behavior_tags,
        power_spikes=row.power_spikes,
        win_condition=row.win_condition,
        typical_build=row.typical_build,
        abilities=row.abilities,
    )
