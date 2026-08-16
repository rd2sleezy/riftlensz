from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from riftlens.adapters.db.repositories import (
    SqlGameplayRepository,
    SqlMatchRepository,
    SqlMediaRepository,
    SqlSyncRepository,
)
from riftlens.domain.clock_reading import ClockReading
from riftlens.domain.sync_map import SyncAnchorInconsistent, build_manual_sync, seek_target
from riftlens.pipeline.sync.errors import AutoSyncError
from riftlens.pipeline.sync.service import AutoSyncService

router = APIRouter()


class SyncAnchorIn(BaseModel):
    t_video_ms: int
    t_game_ms: int


class ClockReadingIn(BaseModel):
    t_video_ms: int
    t_game_ms: int | None = None
    confidence: float = 0.0
    in_game: bool = False
    raw_text: str = ""
    reason: str = ""


class ManualSyncRequest(BaseModel):
    match_id: str = Field(min_length=1)
    media_asset_id: str = ""
    video_duration_ms: int = Field(gt=0)
    match_duration_ms: int | None = Field(default=None, gt=0)
    anchors: list[SyncAnchorIn] = Field(min_length=1)


class AutoSyncRequest(BaseModel):
    match_id: str = Field(min_length=1)
    media_asset_id: str = ""
    video_path: str | None = None
    video_duration_ms: int | None = Field(default=None, gt=0)
    match_duration_ms: int | None = Field(default=None, gt=0)
    content_hash: str | None = None
    gameplay_source_id: str | None = None
    readings: list[ClockReadingIn] | None = None
    pause_end_game_ms: list[int] = Field(default_factory=list)
    hz: float = Field(default=1.0, gt=0)
    force: bool = False


class SeekRequest(BaseModel):
    t_game_ms: int
    lead_in_ms: int = 8_000
    sync_map: dict[str, Any]


@router.post("/sync/manual")
async def manual_sync(body: ManualSyncRequest) -> dict[str, Any]:
    """Fit a slope-1.0 SyncMap from user clock anchors. Does not invent offsets."""
    try:
        sync = build_manual_sync(
            [(item.t_video_ms, item.t_game_ms) for item in body.anchors],
            video_duration_ms=body.video_duration_ms,
            match_id=body.match_id,
            media_asset_id=body.media_asset_id,
            match_duration_ms=body.match_duration_ms,
        )
    except SyncAnchorInconsistent as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return sync.to_dict()


@router.post("/sync/auto")
async def auto_sync(body: AutoSyncRequest, request: Request) -> dict[str, Any]:
    """Fit a VIDEO SyncMap from H.9.1 readings. Does not OCR-calibrate ROFL sources."""
    service = _auto_service(request)
    readings = None
    if body.readings is not None:
        readings = [
            ClockReading(
                t_video_ms=item.t_video_ms,
                t_game_ms=item.t_game_ms,
                confidence=item.confidence,
                in_game=item.in_game,
                raw_text=item.raw_text,
                reason=item.reason,
            )
            for item in body.readings
        ]
    pause_ends = list(body.pause_end_game_ms)
    if not pause_ends:
        pause_ends = await _pause_ends_from_match(request, body.match_id)
    try:
        outcome = await service.run(
            match_id=body.match_id,
            readings=readings,
            video_path=body.video_path,
            video_duration_ms=body.video_duration_ms,
            match_duration_ms=body.match_duration_ms,
            media_asset_id=body.media_asset_id,
            content_hash=body.content_hash,
            gameplay_source_id=body.gameplay_source_id,
            pause_end_game_ms=pause_ends,
            hz=body.hz,
            force=body.force,
        )
    except AutoSyncError as exc:
        return exc.to_dict()
    return outcome.to_dict()


@router.get("/sync/{sync_id}")
async def get_sync(sync_id: str, request: Request) -> dict[str, Any]:
    """Return a persisted SyncMap. Uncovered seek stays a client-side SyncMap concern."""
    service = _auto_service(request)
    try:
        outcome = await service.get(sync_id)
    except AutoSyncError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return outcome.to_dict()


@router.post("/sync/seek")
async def map_seek(body: SeekRequest) -> dict[str, Any]:
    """Map a finding ``t_ms`` through a SyncMap. Uncovered times stay null."""
    from riftlens.domain.sync_map import SyncMap

    try:
        sync = SyncMap.from_dict(body.sync_map)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid sync_map: {exc}") from exc
    target = seek_target(sync, body.t_game_ms, lead_in_ms=body.lead_in_ms)
    return {
        "t_game_ms": target.t_game_ms,
        "t_video_ms": target.t_video_ms,
        "seek_video_ms": target.seek_video_ms,
        "covered": target.covered,
        "uncertain": target.uncertain,
        "reason": target.reason,
    }


def _auto_service(request: Request) -> AutoSyncService:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        return AutoSyncService()
    return AutoSyncService(
        syncs=SqlSyncRepository(factory),
        media=SqlMediaRepository(factory),
        matches=SqlMatchRepository(factory),
        gameplay=SqlGameplayRepository(factory),
    )


async def _pause_ends_from_match(request: Request, match_id: str) -> list[int]:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        return []
    events = await SqlMatchRepository(factory).list_timeline_events(match_id)
    return [int(item.t_ms) for item in events if item.type == "PAUSE_END"]
