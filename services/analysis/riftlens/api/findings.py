from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from riftlens.adapters.db.repositories import SqlFindingRepository
from riftlens.domain.ports import FindingFeedbackRecord
from riftlens.orchestration.progress import now_ms

router = APIRouter()


class FindingFeedbackRequest(BaseModel):
    verdict: str = Field(min_length=1)
    note: str | None = None


@router.post("/findings/{finding_id}/feedback")
async def add_finding_feedback(
    finding_id: str,
    body: FindingFeedbackRequest,
    request: Request,
) -> dict[str, Any]:
    """Record product feedback. Does not modify finding evidence."""
    factory = request.app.state.session_factory
    findings = SqlFindingRepository(factory)
    existing = await findings.get(finding_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Finding not found: {finding_id}")
    await findings.add_feedback(
        FindingFeedbackRecord(
            finding_id=finding_id,
            verdict=body.verdict,
            note=body.note,
            created_at=now_ms(),
        )
    )
    return {"ok": True, "finding_id": finding_id, "verdict": body.verdict}
