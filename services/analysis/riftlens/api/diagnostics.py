from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from riftlens.orchestration.runner import JobService

router = APIRouter()


@router.get("/diagnostics/last-job")
async def last_job(request: Request) -> dict[str, Any]:
    """Return timings and cache stats for the most recent analysis job."""
    service = getattr(request.app.state, "job_service", None)
    if not isinstance(service, JobService):
        raise HTTPException(status_code=503, detail="Job service is not available")
    job = service.last_job()
    if job is None:
        raise HTTPException(status_code=404, detail="No jobs have been run")
    payload = job.to_dict()
    timings = [int(item.duration_ms) for item in job.stage_timings if not item.skipped]
    payload["stage_timing_sum_ms"] = sum(timings)
    payload["wall_ms"] = payload.get("wall_ms")
    return payload
