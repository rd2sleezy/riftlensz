from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from riftlens.adapters.db.models import CaptureIntervalRow, MediaArtifactRow
from riftlens.adapters.db.repositories.base import SessionRepository
from riftlens.domain.capture import RetentionClass
from riftlens.domain.ports import CaptureIntervalRecord, MediaArtifactRecord


class SqlCaptureRepository(SessionRepository):
    """R.10 capture persistence. Rows only — file deletion belongs to the retention policy."""

    async def upsert_interval(self, row: CaptureIntervalRecord) -> None:
        """Insert or replace a capture row. Assumes the gameplay source exists."""

        def work(session: Session) -> None:
            found = session.get(CaptureIntervalRow, row.id)
            if found is None:
                session.add(_to_row(row))
                return
            _apply(found, row)

        await self.call(work)

    async def get_interval(self, capture_id: str) -> CaptureIntervalRecord | None:
        """Return one capture row or None. Assumes ``capture_id`` is a ULID."""

        def work(session: Session) -> CaptureIntervalRecord | None:
            found = session.get(CaptureIntervalRow, capture_id)
            return None if found is None else _interval_record(found)

        return await self.call(work)

    async def list_for_source(self, source_id: str) -> Sequence[CaptureIntervalRecord]:
        """Return captures for a source, newest first. Missing sources yield []."""

        def work(session: Session) -> list[CaptureIntervalRecord]:
            rows = session.scalars(
                select(CaptureIntervalRow)
                .where(CaptureIntervalRow.gameplay_source_id == source_id)
                .order_by(CaptureIntervalRow.created_at.desc(), CaptureIntervalRow.id.desc())
            ).all()
            return [_interval_record(item) for item in rows]

        return await self.call(work)

    async def list_for_review(self, review_id: str) -> Sequence[CaptureIntervalRecord]:
        """Return captures charged to a review, newest first. Missing reviews yield []."""

        def work(session: Session) -> list[CaptureIntervalRecord]:
            rows = session.scalars(
                select(CaptureIntervalRow)
                .where(CaptureIntervalRow.review_id == review_id)
                .order_by(CaptureIntervalRow.created_at.desc(), CaptureIntervalRow.id.desc())
            ).all()
            return [_interval_record(item) for item in rows]

        return await self.call(work)

    async def list_by_retention(self, retention_class: str) -> Sequence[CaptureIntervalRecord]:
        """Return captures in one retention class, oldest first (LRU order)."""

        def work(session: Session) -> list[CaptureIntervalRecord]:
            rows = session.scalars(
                select(CaptureIntervalRow)
                .where(CaptureIntervalRow.retention_class == retention_class)
                .order_by(CaptureIntervalRow.created_at.asc(), CaptureIntervalRow.id.asc())
            ).all()
            return [_interval_record(item) for item in rows]

        return await self.call(work)

    async def list_ephemeral(self) -> Sequence[CaptureIntervalRecord]:
        """Return EPHEMERAL captures, oldest first. Deleted at session teardown."""
        return await self.list_by_retention(RetentionClass.EPHEMERAL.value)

    async def list_by_status(self, statuses: Sequence[str]) -> Sequence[CaptureIntervalRecord]:
        """Return captures in any of ``statuses``, oldest first."""
        wanted = list(statuses)

        def work(session: Session) -> list[CaptureIntervalRecord]:
            if not wanted:
                return []
            rows = session.scalars(
                select(CaptureIntervalRow)
                .where(CaptureIntervalRow.status.in_(wanted))
                .order_by(CaptureIntervalRow.created_at.asc(), CaptureIntervalRow.id.asc())
            ).all()
            return [_interval_record(item) for item in rows]

        return await self.call(work)

    async def list_all(self) -> Sequence[CaptureIntervalRecord]:
        """Return every capture row, oldest first. Used by startup GC."""

        def work(session: Session) -> list[CaptureIntervalRecord]:
            rows = session.scalars(
                select(CaptureIntervalRow).order_by(
                    CaptureIntervalRow.created_at.asc(), CaptureIntervalRow.id.asc()
                )
            ).all()
            return [_interval_record(item) for item in rows]

        return await self.call(work)

    async def update_status(
        self,
        capture_id: str,
        status: str,
        *,
        progress: float | None = None,
        error_code: str | None = None,
        completed_at: int | None = None,
        artifact_count: int | None = None,
        total_bytes: int | None = None,
        manifest_json: str | None = None,
    ) -> None:
        """Patch lifecycle fields. Omitted arguments leave the stored value unchanged."""

        def work(session: Session) -> None:
            found = session.get(CaptureIntervalRow, capture_id)
            if found is None:
                raise ValueError(f"unknown capture interval {capture_id}")
            found.status = status
            if progress is not None:
                found.progress = float(progress)
            if error_code is not None:
                found.error_code = error_code
            if completed_at is not None:
                found.completed_at = int(completed_at)
            if artifact_count is not None:
                found.artifact_count = int(artifact_count)
            if total_bytes is not None:
                found.total_bytes = int(total_bytes)
            if manifest_json is not None:
                found.manifest_json = manifest_json

        await self.call(work)

    async def replace_artifacts(
        self, capture_id: str, rows: Sequence[MediaArtifactRecord]
    ) -> None:
        """Delete then insert artifact rows so re-runs stay idempotent."""
        records = list(rows)

        def work(session: Session) -> None:
            session.execute(
                delete(MediaArtifactRow).where(
                    MediaArtifactRow.capture_interval_id == capture_id
                )
            )
            session.flush()
            for record in records:
                session.add(_to_artifact_row(record))

        await self.call(work)

    async def list_artifacts(self, capture_id: str) -> Sequence[MediaArtifactRecord]:
        """Return artifacts ordered by frame index then id. Missing captures yield []."""

        def work(session: Session) -> list[MediaArtifactRecord]:
            rows = session.scalars(
                select(MediaArtifactRow)
                .where(MediaArtifactRow.capture_interval_id == capture_id)
                .order_by(MediaArtifactRow.frame_index.asc(), MediaArtifactRow.id.asc())
            ).all()
            return [_artifact_record(item) for item in rows]

        return await self.call(work)

    async def sum_usage_for_review(self, review_id: str) -> tuple[float, int, int]:
        """Return ``(seconds, artifacts, bytes)`` already charged to ``review_id``."""

        def work(session: Session) -> tuple[float, int, int]:
            rows = session.scalars(
                select(CaptureIntervalRow).where(CaptureIntervalRow.review_id == review_id)
            ).all()
            seconds = 0.0
            artifacts = 0
            total = 0
            for item in rows:
                if item.status == "cancelled":
                    continue
                seconds += max(0, item.t_end_ms - item.t_start_ms) / 1000.0
                artifacts += int(item.artifact_count)
                total += int(item.total_bytes)
            return seconds, artifacts, total

        return await self.call(work)

    async def delete_interval(self, capture_id: str) -> None:
        """Delete a capture row; artifacts cascade. Callers delete the files."""

        def work(session: Session) -> None:
            session.execute(
                delete(MediaArtifactRow).where(
                    MediaArtifactRow.capture_interval_id == capture_id
                )
            )
            session.execute(
                delete(CaptureIntervalRow).where(CaptureIntervalRow.id == capture_id)
            )

        await self.call(work)


def _to_row(record: CaptureIntervalRecord) -> CaptureIntervalRow:
    row = CaptureIntervalRow(id=record.id, gameplay_source_id=record.gameplay_source_id)
    _apply(row, record)
    return row


def _apply(row: CaptureIntervalRow, record: CaptureIntervalRecord) -> None:
    row.gameplay_source_id = record.gameplay_source_id
    row.match_id = record.match_id
    row.clock_map_id = record.clock_map_id
    row.t_start_ms = record.t_start_ms
    row.t_end_ms = record.t_end_ms
    row.reason = record.reason
    row.mode = record.mode
    row.fps = record.fps
    row.status = record.status
    row.progress = record.progress
    row.t_start_source_ms = record.t_start_source_ms
    row.t_end_source_ms = record.t_end_source_ms
    row.retention_class = record.retention_class
    row.review_id = record.review_id
    row.error_code = record.error_code
    row.artifact_count = record.artifact_count
    row.total_bytes = record.total_bytes
    row.created_at = record.created_at
    row.completed_at = record.completed_at
    row.manifest_json = record.manifest_json


def _to_artifact_row(record: MediaArtifactRecord) -> MediaArtifactRow:
    return MediaArtifactRow(
        id=record.id,
        capture_interval_id=record.capture_interval_id,
        kind=record.kind,
        path=record.path,
        content_hash=record.content_hash,
        width=record.width,
        height=record.height,
        created_at=record.created_at,
        game_t_ms=record.game_t_ms,
        source_t_ms=record.source_t_ms,
        frame_index=record.frame_index,
        retention_class=record.retention_class,
        bytes=record.bytes,
        expires_at=record.expires_at,
    )


def _interval_record(row: CaptureIntervalRow) -> CaptureIntervalRecord:
    return CaptureIntervalRecord(
        id=row.id,
        gameplay_source_id=row.gameplay_source_id,
        match_id=row.match_id,
        clock_map_id=row.clock_map_id,
        t_start_ms=row.t_start_ms,
        t_end_ms=row.t_end_ms,
        reason=row.reason,
        mode=row.mode,
        fps=row.fps,
        status=row.status,
        progress=row.progress,
        retention_class=row.retention_class,
        created_at=row.created_at,
        t_start_source_ms=row.t_start_source_ms,
        t_end_source_ms=row.t_end_source_ms,
        review_id=row.review_id,
        error_code=row.error_code,
        artifact_count=row.artifact_count,
        total_bytes=row.total_bytes,
        completed_at=row.completed_at,
        manifest_json=row.manifest_json,
    )


def _artifact_record(row: MediaArtifactRow) -> MediaArtifactRecord:
    return MediaArtifactRecord(
        id=row.id,
        capture_interval_id=row.capture_interval_id,
        kind=row.kind,
        path=row.path,
        content_hash=row.content_hash,
        created_at=row.created_at,
        game_t_ms=row.game_t_ms,
        source_t_ms=row.source_t_ms,
        frame_index=row.frame_index,
        retention_class=row.retention_class,
        bytes=row.bytes,
        width=row.width,
        height=row.height,
        expires_at=row.expires_at,
    )
