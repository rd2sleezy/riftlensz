from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from riftlens.domain.capture import (
    DEFAULT_MAX_ARTIFACTS,
    TERMINAL_STATUSES,
    CaptureMode,
    CaptureRequest,
    CaptureResult,
    RetentionClass,
)
from riftlens.gameplay.service import GameplaySourceService
from riftlens.gameplay.status import serialize_replay_error

router = APIRouter()


class CreateCaptureRequest(BaseModel):
    """Explicit capture ask from the desktop app. Never issued by click-to-replay."""

    source_id: str = Field(min_length=1)
    start_game_ms: int
    end_game_ms: int
    mode: CaptureMode = CaptureMode.CLIP
    fps: float | None = Field(default=None, gt=0)
    max_artifacts: int = Field(default=DEFAULT_MAX_ARTIFACTS, gt=0)
    retention: RetentionClass = RetentionClass.REVIEW
    review_id: str | None = None


def _service(request: Request) -> GameplaySourceService:
    service = getattr(request.app.state, "gameplay_service", None)
    if not isinstance(service, GameplaySourceService):
        raise HTTPException(status_code=503, detail="Gameplay source service is not ready")
    return service


def serialize_capture(result: CaptureResult) -> dict[str, Any]:
    """Return the JSON view of a capture. Artifacts come from the stored manifest."""
    manifest = result.manifest
    return {
        "ok": result.ok,
        "capture_id": result.capture_id,
        "status": result.status.value,
        "progress": 0.0 if result.progress is None else result.progress.fraction,
        "message": None if result.progress is None else result.progress.message,
        "artifacts": [
            {
                "id": item.id,
                "kind": item.kind,
                "relative_path": item.relative_path,
                "game_t_ms": item.game_t_ms,
                "source_t_ms": item.source_t_ms,
                "sha256": item.sha256,
                "bytes": item.bytes,
                "frame_index": item.frame_index,
            }
            for item in result.artifacts
        ],
        "manifest": None if manifest is None else manifest.to_dict(),
        "error": serialize_replay_error(result.error),
    }


@router.post("/gameplay/captures")
async def create_capture(body: CreateCaptureRequest, request: Request) -> dict[str, Any]:
    """Start an async capture. Returns immediately with a capture id and REQUESTED status."""
    service = _service(request)
    outcome = await service.request_capture(
        CaptureRequest(
            source_id=body.source_id,
            start_game_ms=body.start_game_ms,
            end_game_ms=body.end_game_ms,
            mode=body.mode,
            fps=body.fps,
            max_artifacts=body.max_artifacts,
            retention=body.retention,
            review_id=body.review_id,
        ),
        now_ms=service.now_ms(),
    )
    return serialize_capture(outcome)


@router.get("/gameplay/captures/{capture_id}")
async def get_capture(capture_id: str, request: Request) -> dict[str, Any]:
    """Return capture status, progress, and artifacts. Polling is cheap and side-effect free.

    Live progress only refines a running capture: a terminal status is reported once the row
    carries its manifest, so clients never see COMPLETE with an empty artifact list.
    """
    service = _service(request)
    result = await service.get_capture(capture_id)
    payload = serialize_capture(result)
    progress = await service.capture_progress(capture_id)
    if progress is not None and progress.status not in TERMINAL_STATUSES:
        payload["progress"] = progress.fraction
        payload["status"] = progress.status.value
        payload["message"] = progress.message
    return payload


@router.post("/gameplay/captures/{capture_id}/cancel")
async def cancel_capture(capture_id: str, request: Request) -> dict[str, Any]:
    """Cancel a running capture. Partials are deleted before this returns."""
    service = _service(request)
    return serialize_capture(await service.cancel_capture(capture_id))
