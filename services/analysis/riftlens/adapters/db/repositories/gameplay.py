from __future__ import annotations

import json
from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from riftlens.adapters.db.models import (
    ClockMapRow,
    GameplaySourceRow,
    MediaAssetRow,
    ReplaySessionRow,
    RoflSourceDetailRow,
)
from riftlens.adapters.db.repositories.base import SessionRepository
from riftlens.domain.clock_map import ClockMap
from riftlens.domain.clock_store import (
    SOURCE_STATUS_LINKED,
    SOURCE_STATUS_UNAVAILABLE,
    amendment_clock_confidence,
    amendment_clock_kind,
    decode_clock_payload,
    encode_clock_payload,
    local_display_name,
    source_file_present,
)
from riftlens.domain.ids import new_ulid
from riftlens.domain.ports import (
    ClockCalibrationRecord,
    GameplaySourceRecord,
    GameplaySourceSnapshot,
    ReplaySessionAuditRecord,
    RoflSourceDetailRecord,
    SyncMapRecord,
)
from riftlens.domain.sync_map import SyncMap


class SqlGameplayRepository(SessionRepository):
    async def upsert_source(
        self,
        row: GameplaySourceRecord,
        *,
        rofl: RoflSourceDetailRecord | None = None,
    ) -> str:
        """Insert or update a gameplay source. Assumes the match row exists."""

        def work(session: Session) -> str:
            return _upsert_source_row(session, row, rofl=rofl)

        return await self.call(work)

    async def get_source(self, source_id: str) -> GameplaySourceSnapshot | None:
        """Return a source snapshot or None. Revalidates path existence at read time."""

        def work(session: Session) -> GameplaySourceSnapshot | None:
            found = session.get(GameplaySourceRow, source_id)
            if found is None:
                return None
            return _snapshot(session, found)

        return await self.call(work)

    async def list_sources_for_match(self, match_id: str) -> Sequence[GameplaySourceSnapshot]:
        """Return sources for a match, newest first. Missing matches yield an empty list."""

        def work(session: Session) -> list[GameplaySourceSnapshot]:
            rows = session.scalars(
                select(GameplaySourceRow)
                .where(GameplaySourceRow.match_id == match_id)
                .order_by(GameplaySourceRow.updated_at.desc(), GameplaySourceRow.id.desc())
            ).all()
            return [_snapshot(session, row) for row in rows]

        return await self.call(work)

    async def replace_clock(
        self,
        source_id: str,
        clock: ClockMap,
        *,
        method: str,
        created_at: int,
        anchor_count: int | None = None,
        residual_ms: int | None = None,
        stdev_ms: float | None = None,
        warning: str | None = None,
        calibration_id: str | None = None,
        media_asset_id: str | None = None,
    ) -> ClockCalibrationRecord:
        """Append a clock_map row and mark it active. Assumes the source exists."""

        def work(session: Session) -> ClockCalibrationRecord:
            source = session.get(GameplaySourceRow, source_id)
            if source is None:
                raise ValueError(f"unknown gameplay source {source_id}")
            return _insert_active_clock(
                session,
                source_id=source_id,
                clock=clock,
                method=method,
                created_at=created_at,
                anchor_count=anchor_count,
                residual_ms=residual_ms,
                stdev_ms=stdev_ms,
                warning=warning,
                calibration_id=calibration_id,
                media_asset_id=media_asset_id,
            )

        return await self.call(work)

    async def get_active_clock(self, source_id: str) -> ClockCalibrationRecord | None:
        """Return the active ClockMap calibration, or None when none is stored."""

        def work(session: Session) -> ClockCalibrationRecord | None:
            return _active_clock(session, source_id)

        return await self.call(work)

    async def update_source_status(
        self, source_id: str, status: str, *, updated_at: int
    ) -> None:
        """Update cached source status. Does not imply the file or session is live."""

        def work(session: Session) -> None:
            row = session.get(GameplaySourceRow, source_id)
            if row is None:
                raise ValueError(f"unknown gameplay source {source_id}")
            row.status = status
            row.updated_at = updated_at

        await self.call(work)

    async def revalidate_source(self, source_id: str, *, updated_at: int) -> GameplaySourceSnapshot:
        """Refresh the unavailable/linked hint from disk. Assumes the source exists."""

        def work(session: Session) -> GameplaySourceSnapshot:
            row = session.get(GameplaySourceRow, source_id)
            if row is None:
                raise ValueError(f"unknown gameplay source {source_id}")
            present = source_file_present(row.source_uri)
            if present and row.status == SOURCE_STATUS_UNAVAILABLE:
                row.status = SOURCE_STATUS_LINKED
                row.updated_at = updated_at
            elif not present and row.status != SOURCE_STATUS_UNAVAILABLE:
                row.status = SOURCE_STATUS_UNAVAILABLE
                row.updated_at = updated_at
            return _snapshot(session, row)

        return await self.call(work)

    async def record_session(self, row: ReplaySessionAuditRecord) -> None:
        """Append a historical replay-session audit row. Does not restore liveness."""

        def work(session: Session) -> None:
            session.add(
                ReplaySessionRow(
                    id=row.id,
                    gameplay_source_id=row.gameplay_source_id,
                    replay_api_base=row.replay_api_base,
                    replay_api_port=row.replay_api_port,
                    state=row.state,
                    last_error=row.last_error,
                    started_at=row.started_at,
                    ended_at=row.ended_at,
                )
            )

        await self.call(work)

    async def list_sessions(self, source_id: str) -> Sequence[ReplaySessionAuditRecord]:
        """Return audit rows for a source, newest first. Missing sources yield []."""

        def work(session: Session) -> list[ReplaySessionAuditRecord]:
            rows = session.scalars(
                select(ReplaySessionRow)
                .where(ReplaySessionRow.gameplay_source_id == source_id)
                .order_by(ReplaySessionRow.started_at.desc(), ReplaySessionRow.id.desc())
            ).all()
            return [_session_record(item) for item in rows]

        return await self.call(work)


def mirror_h9_sync_map(session: Session, record: SyncMapRecord) -> None:
    """Dual-write an H.9 SyncMap into gameplay_source + clock_map. Leaves sync_map intact."""
    media = session.get(MediaAssetRow, record.media_asset_id)
    if media is None:
        return
    source_id = _upsert_source_row(
        session,
        GameplaySourceRecord(
            id=record.id,
            match_id=record.match_id,
            source_type="video",
            source_uri=media.original_path,
            content_hash=media.content_hash,
            display_name=local_display_name(media.original_path),
            duration_ms=media.duration_ms,
            status=SOURCE_STATUS_LINKED,
            platform_scope="any",
            created_at=record.created_at,
            updated_at=record.created_at,
            media_asset_id=media.id,
        ),
        rofl=None,
    )
    clock = _clock_from_sync_record(record, duration_ms=media.duration_ms)
    _insert_active_clock(
        session,
        source_id=source_id,
        clock=clock,
        method=_h9_method(record.method),
        created_at=record.created_at,
        media_asset_id=media.id,
        calibration_id=f"cm_{record.id}",
    )


def _upsert_source_row(
    session: Session,
    row: GameplaySourceRecord,
    *,
    rofl: RoflSourceDetailRecord | None,
) -> str:
    display_name = local_display_name(row.source_uri)
    existing = session.scalar(
        select(GameplaySourceRow).where(
            GameplaySourceRow.match_id == row.match_id,
            GameplaySourceRow.source_uri == row.source_uri,
        )
    )
    if existing is None and row.id:
        existing = session.get(GameplaySourceRow, row.id)
    if existing is None:
        stored = GameplaySourceRow(
            id=row.id or new_ulid(),
            match_id=row.match_id,
            source_type=row.source_type,
            source_uri=row.source_uri,
            content_hash=row.content_hash,
            display_name=display_name,
            duration_ms=row.duration_ms,
            status=row.status,
            platform_scope=row.platform_scope,
            media_asset_id=row.media_asset_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        session.add(stored)
        source_id = stored.id
    else:
        existing.source_type = row.source_type
        existing.content_hash = row.content_hash
        existing.display_name = display_name
        existing.duration_ms = row.duration_ms
        existing.status = row.status
        existing.platform_scope = row.platform_scope
        if row.media_asset_id is not None:
            existing.media_asset_id = row.media_asset_id
        existing.updated_at = row.updated_at
        source_id = existing.id
    if rofl is not None:
        _upsert_rofl_detail(session, source_id, rofl)
    return source_id


def _upsert_rofl_detail(session: Session, source_id: str, rofl: RoflSourceDetailRecord) -> None:
    found = session.get(RoflSourceDetailRow, source_id)
    if found is None:
        session.add(
            RoflSourceDetailRow(
                gameplay_source_id=source_id,
                platform_id=rofl.platform_id,
                game_id=rofl.game_id,
                declared_patch=rofl.declared_patch,
                declared_length_ms=rofl.declared_length_ms,
                identify_method=rofl.identify_method,
                header_parse_status=rofl.header_parse_status,
                file_size_bytes=rofl.file_size_bytes,
                magic=rofl.magic,
                raw_metadata_json=rofl.raw_metadata_json,
            )
        )
        return
    found.platform_id = rofl.platform_id
    found.game_id = rofl.game_id
    found.declared_patch = rofl.declared_patch
    found.declared_length_ms = rofl.declared_length_ms
    found.identify_method = rofl.identify_method
    found.header_parse_status = rofl.header_parse_status
    found.file_size_bytes = rofl.file_size_bytes
    found.magic = rofl.magic
    found.raw_metadata_json = rofl.raw_metadata_json


def _insert_active_clock(
    session: Session,
    *,
    source_id: str,
    clock: ClockMap,
    method: str,
    created_at: int,
    anchor_count: int | None = None,
    residual_ms: int | None = None,
    stdev_ms: float | None = None,
    warning: str | None = None,
    calibration_id: str | None = None,
    media_asset_id: str | None = None,
) -> ClockCalibrationRecord:
    session.execute(
        update(ClockMapRow)
        .where(ClockMapRow.gameplay_source_id == source_id, ClockMapRow.is_active == 1)
        .values(is_active=0)
    )
    session.flush()
    payload = encode_clock_payload(
        clock,
        stdev_ms=stdev_ms,
        warning=warning,
        media_asset_id=media_asset_id,
    )
    kind = amendment_clock_kind(clock)
    confidence = amendment_clock_confidence(clock, method)
    existing = session.get(ClockMapRow, calibration_id) if calibration_id else None
    if existing is not None:
        existing.kind = kind
        existing.offset_ms = clock.offset_ms
        existing.rate = 1.0
        existing.confidence = confidence
        existing.method = method
        existing.anchor_count = anchor_count
        existing.residual_ms = residual_ms
        existing.is_active = 1
        existing.payload_json = payload
        session.flush()
        return _clock_record(existing)
    row = ClockMapRow(
        id=calibration_id or new_ulid(),
        gameplay_source_id=source_id,
        kind=kind,
        offset_ms=clock.offset_ms,
        rate=1.0,
        confidence=confidence,
        method=method,
        anchor_count=anchor_count,
        residual_ms=residual_ms,
        is_active=1,
        created_at=created_at,
        payload_json=payload,
    )
    session.add(row)
    session.flush()
    return _clock_record(row)


def _active_clock(session: Session, source_id: str) -> ClockCalibrationRecord | None:
    found = session.scalar(
        select(ClockMapRow)
        .where(ClockMapRow.gameplay_source_id == source_id, ClockMapRow.is_active == 1)
        .order_by(ClockMapRow.created_at.desc())
    )
    return None if found is None else _clock_record(found)


def _snapshot(session: Session, row: GameplaySourceRow) -> GameplaySourceSnapshot:
    detail = session.get(RoflSourceDetailRow, row.id)
    return GameplaySourceSnapshot(
        source=_source_record(row),
        rofl=None if detail is None else _rofl_record(detail),
        clock=_active_clock(session, row.id),
        file_present=source_file_present(row.source_uri),
    )


def _source_record(row: GameplaySourceRow) -> GameplaySourceRecord:
    return GameplaySourceRecord(
        id=row.id,
        match_id=row.match_id,
        source_type=row.source_type,
        source_uri=row.source_uri,
        content_hash=row.content_hash,
        display_name=row.display_name,
        duration_ms=row.duration_ms,
        status=row.status,
        platform_scope=row.platform_scope,
        created_at=row.created_at,
        updated_at=row.updated_at,
        media_asset_id=row.media_asset_id,
    )


def _rofl_record(row: RoflSourceDetailRow) -> RoflSourceDetailRecord:
    return RoflSourceDetailRecord(
        gameplay_source_id=row.gameplay_source_id,
        platform_id=row.platform_id,
        game_id=row.game_id,
        declared_patch=row.declared_patch,
        declared_length_ms=row.declared_length_ms,
        identify_method=row.identify_method,
        header_parse_status=row.header_parse_status,
        file_size_bytes=row.file_size_bytes,
        magic=row.magic,
        raw_metadata_json=row.raw_metadata_json,
    )


def _clock_record(row: ClockMapRow) -> ClockCalibrationRecord:
    clock, stdev_ms, warning, media_asset_id = decode_clock_payload(row.payload_json)
    return ClockCalibrationRecord(
        id=row.id,
        gameplay_source_id=row.gameplay_source_id,
        kind=row.kind,
        offset_ms=row.offset_ms,
        rate=row.rate,
        confidence=row.confidence,
        method=row.method,
        anchor_count=row.anchor_count,
        residual_ms=row.residual_ms,
        is_active=row.is_active,
        created_at=row.created_at,
        clock=clock,
        stdev_ms=stdev_ms,
        warning=warning,
        media_asset_id=media_asset_id,
    )


def _session_record(row: ReplaySessionRow) -> ReplaySessionAuditRecord:
    return ReplaySessionAuditRecord(
        id=row.id,
        gameplay_source_id=row.gameplay_source_id,
        replay_api_base=row.replay_api_base,
        replay_api_port=row.replay_api_port,
        state=row.state,
        last_error=row.last_error,
        started_at=row.started_at,
        ended_at=row.ended_at,
    )


def _clock_from_sync_record(record: SyncMapRecord, *, duration_ms: int) -> ClockMap:
    try:
        payload = {
            "segments": json.loads(record.segments),
            "pauses": json.loads(record.pauses),
            "quality": json.loads(record.quality),
            "media_asset_id": record.media_asset_id,
            "match_id": record.match_id,
            "version": 1,
            "verified": bool(record.verified),
        }
        return ClockMap.from_sync_map(SyncMap.from_dict(payload))
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return ClockMap.unmapped(duration_ms=duration_ms)


def _h9_method(method: str) -> str:
    lowered = method.strip().lower()
    if lowered in {"manual", "clock_ocr", "event_correlation", "hybrid", "auto"}:
        return "manual" if lowered in {"manual", "auto"} else lowered
    return "manual"
