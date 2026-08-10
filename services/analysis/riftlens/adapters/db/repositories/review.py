from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from riftlens.adapters.db.models import ReviewRow
from riftlens.adapters.db.repositories.base import SessionRepository
from riftlens.domain.ports import ReviewRecord


class SqlReviewRepository(SessionRepository):
    async def upsert(self, row: ReviewRecord) -> None:
        """Insert or replace a review. Assumes player and match rows exist."""
        await self.call(lambda session: session.merge(_review_row(row)))

    async def get(self, review_id: str) -> ReviewRecord | None:
        """Return a review or None. Assumes ``review_id`` is a ULID."""

        def work(session: Session) -> ReviewRecord | None:
            found = session.get(ReviewRow, review_id)
            return None if found is None else _review_record(found)

        return await self.call(work)

    async def list_for_player(self, player_id: str) -> Sequence[ReviewRecord]:
        """Return reviews for a player, newest first. Assumes ``player_id`` is a ULID."""

        def work(session: Session) -> list[ReviewRecord]:
            rows = session.scalars(
                select(ReviewRow)
                .where(ReviewRow.player_id == player_id)
                .order_by(ReviewRow.created_at.desc())
            ).all()
            return [_review_record(row) for row in rows]

        return await self.call(work)


def _review_row(row: ReviewRecord) -> ReviewRow:
    return ReviewRow(
        id=row.id,
        player_id=row.player_id,
        match_id=row.match_id,
        participant_id=row.participant_id,
        media_asset_id=row.media_asset_id,
        sync_map_id=row.sync_map_id,
        rule_pack_version=row.rule_pack_version,
        engine_version=row.engine_version,
        analysis_tiers=row.analysis_tiers,
        status=row.status,
        summary_text=row.summary_text,
        overall_scores=row.overall_scores,
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        llm_prompt_version=row.llm_prompt_version,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _review_record(row: ReviewRow) -> ReviewRecord:
    return ReviewRecord(
        id=row.id,
        player_id=row.player_id,
        match_id=row.match_id,
        participant_id=row.participant_id,
        media_asset_id=row.media_asset_id,
        sync_map_id=row.sync_map_id,
        rule_pack_version=row.rule_pack_version,
        engine_version=row.engine_version,
        analysis_tiers=row.analysis_tiers,
        status=row.status,
        summary_text=row.summary_text,
        overall_scores=row.overall_scores,
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        llm_prompt_version=row.llm_prompt_version,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )
