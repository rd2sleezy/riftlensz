from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
