from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from riftlens.orchestration.job import JobInputs
from riftlens.orchestration.progress import ProgressEvent
from riftlens.orchestration.runner import JobService

router = APIRouter()


class AnalyzeJobRequest(BaseModel):
    match_id: str = Field(min_length=1)
    participant_id: int = Field(ge=1, le=10)
    media_asset_id: str | None = None
    rank: str = "UNRANKED"
    region: str | None = None
    api_key: str | None = None
    llm_provider: str | None = None


@router.post("/jobs/analyze")
async def analyze_job(body: AnalyzeJobRequest, request: Request) -> dict[str, str]:
    """Queue an H.11 analysis job. VIDEO media is optional. Never persists API keys."""
    service = _jobs(request)
    settings = request.app.state.settings
    provider = (body.llm_provider or settings.llm_provider or "null").strip() or "null"
    job = service.create(
        JobInputs(
            match_id=body.match_id,
            participant_id=body.participant_id,
            media_asset_id=body.media_asset_id,
            rank=body.rank,
            llm_provider=provider,
            llm_model=settings.llm_model,
            region=body.region,
        )
    )
    service.submit(job.id, api_key=body.api_key)
    return {"job_id": job.id}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> dict[str, Any]:
    """Return job status. Assumes ``job_id`` is a ULID."""
    job = _jobs(request).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job.to_dict()


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str, request: Request) -> StreamingResponse:
    """SSE progress stream. Replays history so reconnects see current state."""
    service = _jobs(request)
    if service.get(job_id) is None and not service.bus.snapshot(job_id):
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    def events() -> Iterator[str]:
        for event in service.bus.iter_sse(job_id):
            yield _sse(event)

    return StreamingResponse(events(), media_type="text/event-stream")


@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str, request: Request) -> dict[str, Any]:
    """Request cooperative cancellation."""
    job = _jobs(request).cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job.to_dict()


def _jobs(request: Request) -> JobService:
    service = getattr(request.app.state, "job_service", None)
    if not isinstance(service, JobService):
        raise HTTPException(status_code=503, detail="Job service is not available")
    return service


def _sse(event: ProgressEvent) -> str:
    return f"data: {json.dumps(event.to_dict())}\n\n"
