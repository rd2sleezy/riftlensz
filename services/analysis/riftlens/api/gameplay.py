from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from riftlens.domain.sync_map import SEEK_LEAD_IN_MS
from riftlens.gameplay.service import GameplaySourceService
from riftlens.gameplay.status import serialize_environment, serialize_replay_error

router = APIRouter()


class ImportReplayRequest(BaseModel):
    path: str = Field(min_length=1)
    match_id: str | None = None


class SourceIdRequest(BaseModel):
    source_id: str = Field(min_length=1)
    match_id: str = Field(min_length=1)


class RevealRequest(BaseModel):
    source_id: str = Field(min_length=1)
    match_id: str = Field(min_length=1)
    game_t_ms: int
    lead_in_ms: int = SEEK_LEAD_IN_MS


class EnableReplayApiRequest(BaseModel):
    consent: bool = False


def _service(request: Request) -> GameplaySourceService:
    service = getattr(request.app.state, "gameplay_service", None)
    if not isinstance(service, GameplaySourceService):
        raise HTTPException(status_code=503, detail="Gameplay source service is not ready")
    return service


@router.get("/gameplay/status")
async def gameplay_status(
    request: Request,
    match_id: str,
    source_id: str | None = None,
) -> dict[str, Any]:
    """Return persisted sources plus live session. READY only when the host confirmed it."""
    service = _service(request)
    return await service.status_for_match(match_id, source_id=source_id, poll=True)


@router.get("/gameplay/environment")
async def gameplay_environment(request: Request) -> dict[str, Any]:
    """Install + Replay API probe. Does not launch a replay."""
    service = _service(request)
    return serialize_environment(service.check_environment())


@router.post("/gameplay/import")
async def import_replay(body: ImportReplayRequest, request: Request) -> dict[str, Any]:
    """Validate, identify, and persist a .rofl. Does not launch League.

    ``match_id`` is the open-review match used only for mismatch validation. Binding
    always uses the ROFL identity hint.
    """
    service = _service(request)
    outcome = await service.import_rofl(
        body.path, now_ms=service.now_ms(), match_id=body.match_id
    )
    status_match = outcome.match_id or body.match_id
    status = None
    if status_match:
        status = await service.status_for_match(
            status_match,
            source_id=outcome.source_id,
            poll=False,
        )
    identity = None
    if outcome.identity is not None:
        identity = {
            "platform_id": outcome.identity.platform_id,
            "game_id": outcome.identity.game_id,
            "declared_patch": outcome.identity.declared_patch,
            "declared_length_ms": outcome.identity.declared_length_ms,
            "match_id_hint": outcome.identity.match_id_hint,
            "identify_method": outcome.identity.identify_method.value,
        }
    return {
        "ok": outcome.ok,
        "source_id": outcome.source_id,
        "match_id": outcome.match_id,
        "identity": identity,
        "error": serialize_replay_error(outcome.error),
        "warnings": [serialize_replay_error(item) for item in outcome.warnings],
        "status": status,
    }


@router.post("/gameplay/open")
async def open_replay(body: SourceIdRequest, request: Request) -> dict[str, Any]:
    """Launch/connect until the host reports READY or a typed failure."""
    service = _service(request)
    session = await service.open_linked_source(body.source_id)
    status = await service.status_for_match(
        body.match_id, source_id=body.source_id, poll=True
    )
    return {
        "ok": session.is_active and session.reached_ready,
        "session_phase": session.phase.value,
        "session_reached_ready": session.reached_ready,
        "error": serialize_replay_error(session.error),
        "status": status,
    }


@router.post("/gameplay/close")
async def close_replay(body: SourceIdRequest, request: Request) -> dict[str, Any]:
    """Close only the live RiftLens-owned session. Persisted source remains linked."""
    service = _service(request)
    await service.close_session(body.source_id, now_ms=service.now_ms())
    status = await service.status_for_match(
        body.match_id, source_id=body.source_id, poll=False
    )
    return {"ok": True, "status": status}


@router.post("/gameplay/enable-replay-api")
async def enable_replay_api(body: EnableReplayApiRequest, request: Request) -> dict[str, Any]:
    """Consent-gated EnableReplayApi write. Never edits game.cfg without consent=true."""
    service = _service(request)
    return service.enable_replay_api(consent=body.consent)


@router.post("/gameplay/reveal")
async def reveal_replay(body: RevealRequest, request: Request) -> dict[str, Any]:
    """Seek the linked native source via R.8. Game→source conversion stays in the sidecar."""
    service = _service(request)
    outcome = await service.reveal(
        body.source_id,
        body.game_t_ms,
        lead_in_ms=body.lead_in_ms,
        now_ms=service.now_ms(),
    )
    status = await service.status_for_match(
        body.match_id, source_id=body.source_id, poll=True
    )
    playback = None
    if outcome.playback is not None:
        playback = {
            "t_source_ms": outcome.playback.t_source_ms,
            "length_ms": outcome.playback.length_ms,
            "paused": outcome.playback.paused,
            "seeking": outcome.playback.seeking,
            "speed_milli": outcome.playback.speed_milli,
            "t_game_ms": outcome.playback.t_game_ms,
        }
    return {
        "ok": outcome.ok,
        "source_id": outcome.source_id,
        "target_game_ms": outcome.target_game_ms,
        "lead_in_ms": outcome.lead_in_ms,
        "landed_source_ms": outcome.landed_source_ms,
        "clock_verified": outcome.clock_verified,
        "clock_confidence": None
        if outcome.clock is None
        else outcome.clock.confidence.value,
        "playback": playback,
        "error": serialize_replay_error(outcome.error),
        "warnings": [serialize_replay_error(item) for item in outcome.warnings],
        "status": status,
    }
