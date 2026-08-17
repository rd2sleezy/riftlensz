from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from riftlens.adapters.db.models import EvidenceRow, FindingFeedbackRow, FindingRow
from riftlens.adapters.db.repositories.base import SessionRepository
from riftlens.domain.ports import EvidenceRecord, FindingFeedbackRecord, FindingRecord


class SqlFindingRepository(SessionRepository):
    async def add(self, finding: FindingRecord, evidence: Sequence[EvidenceRecord]) -> None:
        """Insert a finding and its evidence. Assumes review and concept rows exist."""

        def work(session: Session) -> None:
            session.add(_finding_row(finding))
            session.flush()
            for item in evidence:
                session.add(_evidence_row(item))

        await self.call(work)

    async def replace_for_review(
        self,
        review_id: str,
        rows: Sequence[tuple[FindingRecord, Sequence[EvidenceRecord]]],
    ) -> None:
        """Replace findings and evidence for a review. Assumes coaching links are already gone."""

        def work(session: Session) -> None:
            existing_ids = list(
                session.scalars(
                    select(FindingRow.id).where(FindingRow.review_id == review_id)
                ).all()
            )
            if existing_ids:
                session.execute(
                    delete(FindingFeedbackRow).where(FindingFeedbackRow.finding_id.in_(existing_ids))
                )
                session.execute(delete(EvidenceRow).where(EvidenceRow.finding_id.in_(existing_ids)))
                session.execute(delete(FindingRow).where(FindingRow.id.in_(existing_ids)))
            for finding, evidence in rows:
                session.add(_finding_row(finding))
                session.flush()
                for item in evidence:
                    session.add(_evidence_row(item))

        await self.call(work)

    async def get(self, finding_id: str) -> FindingRecord | None:
        """Return a finding or None. Assumes ``finding_id`` is a ULID."""

        def work(session: Session) -> FindingRecord | None:
            found = session.get(FindingRow, finding_id)
            return None if found is None else _finding_record(found)

        return await self.call(work)

    async def list_for_review(self, review_id: str) -> Sequence[FindingRecord]:
        """Return findings ordered by t_ms. Assumes the review may be missing."""

        def work(session: Session) -> list[FindingRecord]:
            rows = session.scalars(
                select(FindingRow)
                .where(FindingRow.review_id == review_id)
                .order_by(FindingRow.t_ms, FindingRow.id)
            ).all()
            return [_finding_record(row) for row in rows]

        return await self.call(work)

    async def list_evidence(self, finding_id: str) -> Sequence[EvidenceRecord]:
        """Return evidence rows for a finding. Assumes the finding may be missing."""

        def work(session: Session) -> list[EvidenceRecord]:
            rows = session.scalars(
                select(EvidenceRow)
                .where(EvidenceRow.finding_id == finding_id)
                .order_by(EvidenceRow.id)
            ).all()
            return [_evidence_record(row) for row in rows]

        return await self.call(work)

    async def add_feedback(self, row: FindingFeedbackRecord) -> None:
        """Insert user feedback. Assumes the finding exists."""
        await self.call(lambda session: session.add(_feedback_row(row)))

    async def list_feedback(self, finding_id: str) -> Sequence[FindingFeedbackRecord]:
        """Return feedback rows for a finding. Assumes the finding may be missing."""

        def work(session: Session) -> list[FindingFeedbackRecord]:
            rows = session.scalars(
                select(FindingFeedbackRow)
                .where(FindingFeedbackRow.finding_id == finding_id)
                .order_by(FindingFeedbackRow.id)
            ).all()
            return [_feedback_record(row) for row in rows]

        return await self.call(work)


def _finding_row(row: FindingRecord) -> FindingRow:
    return FindingRow(
        id=row.id,
        review_id=row.review_id,
        rule_id=row.rule_id,
        rule_version=row.rule_version,
        concept_id=row.concept_id,
        t_ms=row.t_ms,
        t_end_ms=row.t_end_ms,
        severity=row.severity,
        confidence=row.confidence,
        gold_equivalent=row.gold_equivalent,
        outcome=row.outcome,
        map_x=row.map_x,
        map_y=row.map_y,
        title=row.title,
        explanation=row.explanation,
        alternative=row.alternative,
        explanation_source=row.explanation_source,
        suppressed=row.suppressed,
        suppressed_by=row.suppressed_by,
    )


def _finding_record(row: FindingRow) -> FindingRecord:
    return FindingRecord(
        id=row.id,
        review_id=row.review_id,
        rule_id=row.rule_id,
        rule_version=row.rule_version,
        concept_id=row.concept_id,
        t_ms=row.t_ms,
        t_end_ms=row.t_end_ms,
        severity=row.severity,
        confidence=row.confidence,
        gold_equivalent=row.gold_equivalent,
        outcome=row.outcome,
        map_x=row.map_x,
        map_y=row.map_y,
        title=row.title,
        explanation=row.explanation,
        alternative=row.alternative,
        explanation_source=row.explanation_source,
        suppressed=row.suppressed,
        suppressed_by=row.suppressed_by,
    )


def _evidence_row(row: EvidenceRecord) -> EvidenceRow:
    return EvidenceRow(
        finding_id=row.finding_id,
        kind=row.kind,
        label=row.label,
        value_json=row.value_json,
        t_ms=row.t_ms,
        source=row.source,
        confidence=row.confidence,
        provenance_json=row.provenance_json,
    )


def _evidence_record(row: EvidenceRow) -> EvidenceRecord:
    return EvidenceRecord(
        id=row.id,
        finding_id=row.finding_id,
        kind=row.kind,
        label=row.label,
        value_json=row.value_json,
        t_ms=row.t_ms,
        source=row.source,
        confidence=row.confidence,
        provenance_json=row.provenance_json,
    )


def _feedback_row(row: FindingFeedbackRecord) -> FindingFeedbackRow:
    return FindingFeedbackRow(
        finding_id=row.finding_id,
        verdict=row.verdict,
        note=row.note,
        created_at=row.created_at,
    )


def _feedback_record(row: FindingFeedbackRow) -> FindingFeedbackRecord:
    return FindingFeedbackRecord(
        id=row.id,
        finding_id=row.finding_id,
        verdict=row.verdict,
        note=row.note,
        created_at=row.created_at,
    )
