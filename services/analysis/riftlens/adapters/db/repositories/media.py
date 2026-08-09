from __future__ import annotations

from sqlalchemy.orm import Session

from riftlens.adapters.db.models import LayoutProfileRow, MediaAssetRow
from riftlens.adapters.db.repositories.base import SessionRepository
from riftlens.domain.ports import LayoutProfileRecord, MediaAssetRecord


class SqlMediaRepository(SessionRepository):
    async def upsert_asset(self, row: MediaAssetRecord) -> None:
        """Insert or replace a media asset. Assumes ``content_hash`` is unique."""
        await self.call(lambda session: session.merge(_asset_row(row)))

    async def get_asset(self, media_id: str) -> MediaAssetRecord | None:
        """Return a media asset or None. Assumes ``media_id`` is a ULID."""

        def work(session: Session) -> MediaAssetRecord | None:
            found = session.get(MediaAssetRow, media_id)
            return None if found is None else _asset_record(found)

        return await self.call(work)

    async def upsert_layout_profile(self, row: LayoutProfileRecord) -> None:
        """Insert or replace a layout profile. Assumes ``row.id`` is a ULID."""
        await self.call(lambda session: session.merge(_layout_row(row)))

    async def get_layout_profile(self, profile_id: str) -> LayoutProfileRecord | None:
        """Return a layout profile or None. Assumes ``profile_id`` is a ULID."""

        def work(session: Session) -> LayoutProfileRecord | None:
            found = session.get(LayoutProfileRow, profile_id)
            return None if found is None else _layout_record(found)

        return await self.call(work)


def _asset_row(row: MediaAssetRecord) -> MediaAssetRow:
    return MediaAssetRow(
        id=row.id,
        content_hash=row.content_hash,
        original_path=row.original_path,
        playable_path=row.playable_path,
        proxy_path=row.proxy_path,
        thumbnail_sheet_path=row.thumbnail_sheet_path,
        container=row.container,
        codec=row.codec,
        pix_fmt=row.pix_fmt,
        width=row.width,
        height=row.height,
        fps_num=row.fps_num,
        fps_den=row.fps_den,
        duration_ms=row.duration_ms,
        size_bytes=row.size_bytes,
        source_kind=row.source_kind,
        layout_profile_id=row.layout_profile_id,
        quality_score=row.quality_score,
        imported_at=row.imported_at,
        last_accessed_at=row.last_accessed_at,
    )


def _asset_record(row: MediaAssetRow) -> MediaAssetRecord:
    return MediaAssetRecord(
        id=row.id,
        content_hash=row.content_hash,
        original_path=row.original_path,
        playable_path=row.playable_path,
        proxy_path=row.proxy_path,
        thumbnail_sheet_path=row.thumbnail_sheet_path,
        container=row.container,
        codec=row.codec,
        pix_fmt=row.pix_fmt,
        width=row.width,
        height=row.height,
        fps_num=row.fps_num,
        fps_den=row.fps_den,
        duration_ms=row.duration_ms,
        size_bytes=row.size_bytes,
        source_kind=row.source_kind,
        layout_profile_id=row.layout_profile_id,
        quality_score=row.quality_score,
        imported_at=row.imported_at,
        last_accessed_at=row.last_accessed_at,
    )


def _layout_row(row: LayoutProfileRecord) -> LayoutProfileRow:
    return LayoutProfileRow(
        id=row.id,
        width=row.width,
        height=row.height,
        ui_scale_estimate=row.ui_scale_estimate,
        minimap_flipped=row.minimap_flipped,
        minimap_rect=row.minimap_rect,
        clock_rect=row.clock_rect,
        regions=row.regions,
        occluded_regions=row.occluded_regions,
        world_to_minimap_affine=row.world_to_minimap_affine,
        created_at=row.created_at,
    )


def _layout_record(row: LayoutProfileRow) -> LayoutProfileRecord:
    return LayoutProfileRecord(
        id=row.id,
        width=row.width,
        height=row.height,
        ui_scale_estimate=row.ui_scale_estimate,
        minimap_flipped=row.minimap_flipped,
        minimap_rect=row.minimap_rect,
        clock_rect=row.clock_rect,
        regions=row.regions,
        occluded_regions=row.occluded_regions,
        world_to_minimap_affine=row.world_to_minimap_affine,
        created_at=row.created_at,
    )
