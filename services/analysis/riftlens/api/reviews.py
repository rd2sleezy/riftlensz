from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from riftlens.pipeline.assemble.review_builder import build_review_from_dtos
from riftlens.pipeline.assemble.review_presentation import (
    list_review_presentations,
    load_review_presentation,
    review_to_presentation,
    save_review_presentation,
)

router = APIRouter()

_ALLOWED_FIXTURES = frozenset({"NA1_fixture_a", "NA1_fixture_b", "NA1_fixture_c"})
_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "riot"


class FixtureReviewRequest(BaseModel):
    fixture_id: str = Field(min_length=1)
    participant_id: int = Field(ge=1, le=10)
    rank: str = "UNRANKED"


@router.get("/reviews")
async def list_reviews(request: Request) -> dict[str, Any]:
    """Return saved H.8 review summaries. Assumes presentations live under data_dir."""
    settings = request.app.state.settings
    return {"reviews": list_review_presentations(settings.data_dir)}


@router.get("/reviews/{review_id}")
async def get_review(review_id: str, request: Request) -> dict[str, Any]:
    """Return full presentation JSON. Assumes the review was built by H.8."""
    settings = request.app.state.settings
    payload = load_review_presentation(settings.data_dir, review_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Review not found: {review_id}")
    return payload


@router.post("/reviews/from-fixture")
async def review_from_fixture(body: FixtureReviewRequest, request: Request) -> dict[str, Any]:
    """Build and persist an H.8 review from a committed Riot fixture. No network."""
    if body.fixture_id not in _ALLOWED_FIXTURES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown fixture_id {body.fixture_id!r}. Allowed: {sorted(_ALLOWED_FIXTURES)}",
        )
    match_path = _FIXTURE_ROOT / body.fixture_id / "match.json"
    timeline_path = _FIXTURE_ROOT / body.fixture_id / "timeline.json"
    if not match_path.is_file() or not timeline_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Fixture files missing for {body.fixture_id}",
        )
    settings = request.app.state.settings

    def work() -> dict[str, Any]:
        from riftlens.adapters.riot.models import MatchDto, TimelineDto

        match = MatchDto.model_validate(json.loads(match_path.read_text(encoding="utf-8")))
        timeline = TimelineDto.model_validate(json.loads(timeline_path.read_text(encoding="utf-8")))
        built = build_review_from_dtos(
            match,
            timeline,
            body.participant_id,
            rank=body.rank,
            llm_provider="null",
            persist=True,
            settings=settings,
        )
        payload = review_to_presentation(built.review, fixture_id=body.fixture_id)
        save_review_presentation(settings.data_dir, payload)
        return payload

    return await asyncio.to_thread(work)
