from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from riftlens.adapters.db.models import CoachingItemFindingRow, CoachingItemRow, FocusCommitmentRow
from riftlens.adapters.db.repositories.base import SessionRepository
from riftlens.domain.ports import CoachingItemRecord, FocusCommitmentRecord


class SqlCoachingRepository(SessionRepository):
    async def replace_for_review(self, review_id: str, rows: Sequence[CoachingItemRecord]) -> None:
        """Replace coaching items and their finding links. Assumes review/findings exist."""

        def work(session: Session) -> None:
            existing_ids = list(
                session.scalars(
                    select(CoachingItemRow.id).where(CoachingItemRow.review_id == review_id)
                ).all()
            )
            if existing_ids:
                session.execute(
                    delete(CoachingItemFindingRow).where(
                        CoachingItemFindingRow.coaching_item_id.in_(existing_ids)
                    )
                )
                session.execute(delete(CoachingItemRow).where(CoachingItemRow.id.in_(existing_ids)))
            for row in rows:
                session.add(_item_row(row))
                session.flush()
                for finding_id in row.finding_ids:
                    session.add(
                        CoachingItemFindingRow(coaching_item_id=row.id, finding_id=finding_id)
                    )

        await self.call(work)

    async def list_for_review(self, review_id: str) -> Sequence[CoachingItemRecord]:
        """Return coaching items ordered by rank. Assumes the review may be missing."""

        def work(session: Session) -> list[CoachingItemRecord]:
            items = session.scalars(
                select(CoachingItemRow)
                .where(CoachingItemRow.review_id == review_id)
                .order_by(CoachingItemRow.rank, CoachingItemRow.id)
            ).all()
            result: list[CoachingItemRecord] = []
            for item in items:
                finding_ids = tuple(
                    session.scalars(
                        select(CoachingItemFindingRow.finding_id)
                        .where(CoachingItemFindingRow.coaching_item_id == item.id)
                        .order_by(CoachingItemFindingRow.finding_id)
                    ).all()
                )
                result.append(_item_record(item, finding_ids))
            return result

        return await self.call(work)

    async def upsert_focus_commitment(self, row: FocusCommitmentRecord) -> None:
        """Insert or replace a focus commitment. Assumes player, review, and concept exist."""
        await self.call(lambda session: session.merge(_commitment_row(row)))

    async def get_focus_commitment(self, commitment_id: str) -> FocusCommitmentRecord | None:
        """Return a focus commitment or None. Assumes ``commitment_id`` is a ULID."""

        def work(session: Session) -> FocusCommitmentRecord | None:
            found = session.get(FocusCommitmentRow, commitment_id)
            return None if found is None else _commitment_record(found)

        return await self.call(work)


def _item_row(row: CoachingItemRecord) -> CoachingItemRow:
    return CoachingItemRow(
        id=row.id,
        review_id=row.review_id,
        root_concept_id=row.root_concept_id,
        rank=row.rank,
        is_focus=row.is_focus,
        is_strength=row.is_strength,
        issue_type=row.issue_type,
        impact_score=row.impact_score,
        gold_equivalent=row.gold_equivalent,
        occurrences=row.occurrences,
        confidence=row.confidence,
        title=row.title,
        body=row.body,
        the_fix=row.the_fix,
        next_game_check=row.next_game_check,
        exemplar_finding_id=row.exemplar_finding_id,
    )


def _item_record(row: CoachingItemRow, finding_ids: tuple[str, ...]) -> CoachingItemRecord:
    return CoachingItemRecord(
        id=row.id,
        review_id=row.review_id,
        root_concept_id=row.root_concept_id,
        rank=row.rank,
        is_focus=row.is_focus,
        is_strength=row.is_strength,
        issue_type=row.issue_type,
        impact_score=row.impact_score,
        gold_equivalent=row.gold_equivalent,
        occurrences=row.occurrences,
        confidence=row.confidence,
        title=row.title,
        body=row.body,
        the_fix=row.the_fix,
        next_game_check=row.next_game_check,
        exemplar_finding_id=row.exemplar_finding_id,
        finding_ids=finding_ids,
    )


def _commitment_row(row: FocusCommitmentRecord) -> FocusCommitmentRow:
    return FocusCommitmentRow(
        id=row.id,
        player_id=row.player_id,
        review_id=row.review_id,
        concept_id=row.concept_id,
        metric_id=row.metric_id,
        target_value=row.target_value,
        comparison=row.comparison,
        created_at=row.created_at,
        resolved_review_id=row.resolved_review_id,
        outcome=row.outcome,
    )


def _commitment_record(row: FocusCommitmentRow) -> FocusCommitmentRecord:
    return FocusCommitmentRecord(
        id=row.id,
        player_id=row.player_id,
        review_id=row.review_id,
        concept_id=row.concept_id,
        metric_id=row.metric_id,
        target_value=row.target_value,
        comparison=row.comparison,
        created_at=row.created_at,
        resolved_review_id=row.resolved_review_id,
        outcome=row.outcome,
    )
