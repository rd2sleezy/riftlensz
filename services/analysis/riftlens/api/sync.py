from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from riftlens.domain.sync_map import SyncAnchorInconsistent, build_manual_sync, seek_target

router = APIRouter()


class SyncAnchorIn(BaseModel):
    t_video_ms: int
    t_game_ms: int


class ManualSyncRequest(BaseModel):
    match_id: str = Field(min_length=1)
    media_asset_id: str = ""
    video_duration_ms: int = Field(gt=0)
    match_duration_ms: int | None = Field(default=None, gt=0)
    anchors: list[SyncAnchorIn] = Field(min_length=1)


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
