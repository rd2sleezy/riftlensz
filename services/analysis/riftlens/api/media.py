from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from riftlens.adapters.db.repositories import SqlMatchRepository, SqlMediaRepository
from riftlens.domain.ids import new_ulid
from riftlens.domain.ports import MediaAssetRecord
from riftlens.orchestration.progress import now_ms
from riftlens.pipeline.ingest_video.probe import (
    MediaProbeError,
    chromium_playable,
    decide_handling,
    probe,
    validate_probe,
)

router = APIRouter()


class MediaProbeRequest(BaseModel):
    path: str = Field(min_length=1)


class MediaImportRequest(BaseModel):
    path: str = Field(min_length=1)


class MatchCandidatesRequest(BaseModel):
    media_asset_id: str = Field(min_length=1)


@router.post("/media/import")
async def import_media(body: MediaImportRequest, request: Request) -> dict[str, Any]:
    """Probe, hash, and persist a VIDEO MediaAsset. Does not ingest ROFL identity."""
    try:
        media = probe(body.path)
    except MediaProbeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    errors = validate_probe(media)
    if errors:
        raise HTTPException(status_code=400, detail=" ".join(errors))
    factory = request.app.state.session_factory
    repo = SqlMediaRepository(factory)
    existing = await repo.get_by_content_hash(media.content_hash)
    if existing is not None:
        return {"id": existing.id, "content_hash": existing.content_hash, "reused": True}
    record = MediaAssetRecord(
        id=new_ulid(),
        content_hash=media.content_hash,
        original_path=media.path,
        playable_path=media.path if chromium_playable(media) else None,
        proxy_path=None,
        thumbnail_sheet_path=None,
        container=None,
        codec=media.codec_name,
        pix_fmt=media.pix_fmt,
        width=media.width,
        height=media.height,
        fps_num=None,
        fps_den=None,
        duration_ms=media.duration_ms,
        size_bytes=media.size_bytes,
        source_kind="PLAYER_POV",
        layout_profile_id=None,
        quality_score=None,
        imported_at=now_ms(),
        last_accessed_at=now_ms(),
    )
    await repo.upsert_asset(record)
    return {"id": record.id, "content_hash": record.content_hash, "reused": False}


@router.post("/media/match-candidates")
async def match_candidates(body: MatchCandidatesRequest, request: Request) -> dict[str, Any]:
    """Rank ingested matches by duration proximity to VIDEO media. Not for ROFL identity."""
    factory = request.app.state.session_factory
    media = await SqlMediaRepository(factory).get_asset(body.media_asset_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Media asset not found")
    matches = await SqlMatchRepository(factory).list_recent(limit=40)
    ranked = sorted(
        matches,
        key=lambda row: abs(int(row.game_duration_ms) - int(media.duration_ms)),
    )
    return {
        "media_asset_id": media.id,
        "candidates": [
            {
                "match_id": row.match_id,
                "duration_ms": row.game_duration_ms,
                "delta_ms": abs(int(row.game_duration_ms) - int(media.duration_ms)),
                "patch": row.patch,
            }
            for row in ranked[:10]
        ],
    }


@router.post("/media/probe")
async def probe_media(body: MediaProbeRequest) -> dict[str, Any]:
    """Probe a local VOD path. Returns playability plus ingest validation errors."""
    try:
        media = probe(body.path)
    except MediaProbeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    errors = validate_probe(media)
    playable = chromium_playable(media)
    handling = decide_handling(media)
    message = None
    if not playable:
        message = (
            f"Unsupported codec for desktop playback "
            f"(codec={media.codec_name or 'unknown'}, pix_fmt={media.pix_fmt or 'unknown'}). "
            "Chromium needs H.264/yuv420p."
        )
    elif errors:
        message = " ".join(errors) + " Playback may still work; auto ingest would reject this file."
    return {
        "ok": playable,
        "playable": playable,
        "handling": handling.value,
        "ingest_errors": errors,
        "message": message,
        "probe": media.to_dict(),
    }
