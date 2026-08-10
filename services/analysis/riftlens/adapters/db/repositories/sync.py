from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from riftlens.adapters.db.models import SyncMapRow
from riftlens.adapters.db.repositories.base import SessionRepository
from riftlens.adapters.db.repositories.gameplay import mirror_h9_sync_map
from riftlens.domain.ports import SyncMapRecord


class SqlSyncRepository(SessionRepository):
    async def upsert(self, row: SyncMapRecord) -> None:
        """Insert or replace a sync map and mirror it onto gameplay_source/clock_map."""

        def work(session: Session) -> None:
            session.merge(_sync_row(row))
            mirror_h9_sync_map(session, row)

        await self.call(work)

    async def get(self, sync_id: str) -> SyncMapRecord | None:
        """Return a sync map or None. Assumes ``sync_id`` is a ULID."""

        def work(session: Session) -> SyncMapRecord | None:
            found = session.get(SyncMapRow, sync_id)
            return None if found is None else _sync_record(found)

        return await self.call(work)

    async def get_by_media_and_match(self, media_id: str, match_id: str) -> SyncMapRecord | None:
        """Return the unique sync map for a VOD+match pair, or None. Assumes FKs are valid."""

        def work(session: Session) -> SyncMapRecord | None:
            found = session.scalar(
                select(SyncMapRow).where(
                    SyncMapRow.media_asset_id == media_id,
                    SyncMapRow.match_id == match_id,
                )
            )
            return None if found is None else _sync_record(found)

        return await self.call(work)


def _sync_row(row: SyncMapRecord) -> SyncMapRow:
    return SyncMapRow(
        id=row.id,
        media_asset_id=row.media_asset_id,
        match_id=row.match_id,
        method=row.method,
        segments=row.segments,
        pauses=row.pauses,
        quality=row.quality,
        verified=row.verified,
        created_at=row.created_at,
    )


def _sync_record(row: SyncMapRow) -> SyncMapRecord:
    return SyncMapRecord(
        id=row.id,
        media_asset_id=row.media_asset_id,
        match_id=row.match_id,
        method=row.method,
        segments=row.segments,
        pauses=row.pauses,
        quality=row.quality,
        verified=row.verified,
        created_at=row.created_at,
    )
