"""Persist/load automatic SyncMaps keyed by (media content hash, match_id, algo version)."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

from riftlens.domain.clock_map import ClockMap
from riftlens.domain.ids import new_ulid
from riftlens.domain.ports import (
    MediaAssetRecord,
    MediaRepository,
    SyncMapRecord,
    SyncRepository,
)
from riftlens.domain.sync_map import SyncMap
from riftlens.pipeline.sync.fitter import ALGO_VERSION, AutoFitResult

METHOD_CLOCK_OCR = "clock_ocr"


def cache_key_matches(record: SyncMapRecord, *, algo_version: str = ALGO_VERSION) -> bool:
    """Return True when a stored row is a reusable auto-sync result."""
    if record.method != METHOD_CLOCK_OCR:
        return False
    try:
        quality = json.loads(record.quality)
    except json.JSONDecodeError:
        return False
    if not isinstance(quality, Mapping):
        return False
    return str(quality.get("algo_version") or "") == algo_version


async def lookup_cached(
    *,
    syncs: SyncRepository,
    media: MediaRepository,
    content_hash: str,
    match_id: str,
) -> tuple[SyncMap, ClockMap, str] | None:
    """Return cached SyncMap+ClockMap+id, or None on miss / version mismatch."""
    asset = await media.get_by_content_hash(content_hash)
    if asset is None:
        return None
    record = await syncs.get_by_media_and_match(asset.id, match_id)
    if record is None or not cache_key_matches(record):
        return None
    sync = sync_from_record(record)
    return sync, ClockMap.from_sync_map(sync), record.id


async def persist_auto(
    result: AutoFitResult,
    *,
    syncs: SyncRepository,
    existing: SyncMapRecord | None,
) -> str:
    """Store an auto SyncMap. Will not overwrite a valid manual map on the caller’s behalf.

    Callers must skip this when auto-sync failed. Success may replace a previous
    ``clock_ocr`` row for the same media+match.
    """
    sync = result.sync_map
    record_id = existing.id if existing is not None else new_ulid()
    row = _record_from_sync(
        sync,
        record_id=record_id,
        extra={
            "algo_version": ALGO_VERSION,
            "filter": result.filter_report.reason_counts,
            "verify_reasons": list(result.verify.reasons),
            "fit_ms": result.fit_ms,
            "verify_ms": result.verify_ms,
        },
    )
    await syncs.upsert(row)
    return record_id


def sync_from_record(record: SyncMapRecord) -> SyncMap:
    """Rehydrate a SyncMap from persistence. Extra quality keys are ignored by domain parse."""
    quality = json.loads(record.quality)
    payload: dict[str, Any] = {
        "segments": json.loads(record.segments),
        "pauses": json.loads(record.pauses),
        "quality": quality,
        "media_asset_id": record.media_asset_id,
        "match_id": record.match_id,
        "version": 1,
        "verified": bool(record.verified),
    }
    return SyncMap.from_dict(payload)


def _record_from_sync(
    sync: SyncMap, *, record_id: str, extra: Mapping[str, Any]
) -> SyncMapRecord:
    raw = sync.to_dict()
    quality = dict(raw["quality"])
    quality.update(extra)
    now_ms = int(time.time() * 1000)
    return SyncMapRecord(
        id=record_id,
        media_asset_id=sync.media_asset_id,
        match_id=sync.match_id,
        method=METHOD_CLOCK_OCR,
        segments=json.dumps(raw["segments"], separators=(",", ":")),
        pauses=json.dumps(raw["pauses"], separators=(",", ":")),
        quality=json.dumps(quality, separators=(",", ":")),
        verified=1 if sync.verified else 0,
        created_at=now_ms,
    )


def media_stub(
    *,
    asset_id: str,
    content_hash: str,
    path: str,
    duration_ms: int,
    size_bytes: int = 1,
    width: int | None = None,
    height: int | None = None,
    codec: str | None = None,
    pix_fmt: str | None = None,
) -> MediaAssetRecord:
    """Minimal media_asset row so sync_map FK + content-hash cache can work."""
    now_ms = int(time.time() * 1000)
    return MediaAssetRecord(
        id=asset_id,
        content_hash=content_hash,
        original_path=path,
        playable_path=None,
        proxy_path=None,
        thumbnail_sheet_path=None,
        container=None,
        codec=codec,
        pix_fmt=pix_fmt,
        width=width,
        height=height,
        fps_num=None,
        fps_den=None,
        duration_ms=duration_ms,
        size_bytes=size_bytes,
        source_kind="PLAYER_POV",
        layout_profile_id=None,
        quality_score=None,
        imported_at=now_ms,
        last_accessed_at=now_ms,
    )
