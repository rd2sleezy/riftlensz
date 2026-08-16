from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from riftlens.domain.replay_errors import ReplayError
from riftlens.domain.timeline import GameStateTimeline
from riftlens.gameplay.status import serialize_replay_error
from riftlens.pipeline.assemble.real_match import (
    build_real_match_review,
    ensure_match_ingested,
    list_match_participants,
)
from riftlens.pipeline.assemble.review_builder import build_review_from_dtos
from riftlens.pipeline.assemble.review_presentation import (
    list_review_presentations,
    load_review_presentation,
    purge_fixture_trial_presentations,
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


class RealMatchReviewRequest(BaseModel):
    match_id: str = Field(min_length=1)
    participant_id: int = Field(ge=1, le=10)
    rank: str = "UNRANKED"
    api_key: str | None = None
    region: str | None = None


class IngestMatchRequest(BaseModel):
    match_id: str = Field(min_length=1)
    api_key: str | None = None
    region: str | None = None


class MatchParticipantsRequest(BaseModel):
    match_id: str = Field(min_length=1)
    api_key: str | None = None
    region: str | None = None


@router.get("/reviews")
async def list_reviews(
    request: Request,
    include_fixtures: bool = False,
    player_id: str | None = None,
) -> dict[str, Any]:
    """Return saved H.8 review summaries.

    Fixture/demo reviews are excluded unless ``include_fixtures=true`` (developer/E2E).
    """
    settings = request.app.state.settings
    reviews = list_review_presentations(
        settings.data_dir, include_fixtures=include_fixtures
    )
    if player_id:
        reviews = [item for item in reviews if item.get("player_id") == player_id]
    return {"reviews": reviews}


@router.post("/reviews/purge-fixtures")
async def purge_fixture_reviews(request: Request) -> dict[str, Any]:
    """Optional developer cleanup: delete on-disk fixture trial presentations only.

    Production list filtering does not require this. Does not touch real match reviews.
    """
    settings = request.app.state.settings
    removed = purge_fixture_trial_presentations(settings.data_dir)
    return {"ok": True, "removed": removed}


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


@router.post("/matches/ingest")
async def ingest_match(body: IngestMatchRequest, request: Request) -> dict[str, Any]:
    """Fetch MATCH-V5 + timeline when missing, persist via existing H.2 repositories."""
    settings = request.app.state.settings
    try:
        result = await ensure_match_ingested(
            body.match_id,
            api_key=body.api_key,
            region=body.region,
            settings=settings,
        )
    except ReplayError as exc:
        return {"ok": False, "error": serialize_replay_error(exc)}
    return {
        "ok": True,
        "match_id": result.match_id,
        "fetched": result.fetched,
        "error": None,
    }


@router.post("/matches/participants")
async def match_participants(body: MatchParticipantsRequest, request: Request) -> dict[str, Any]:
    """Return the ten participants for a match (ingesting first when needed)."""
    settings = request.app.state.settings
    try:
        rows = await list_match_participants(
            body.match_id,
            api_key=body.api_key,
            region=body.region,
            settings=settings,
        )
    except ReplayError as exc:
        return {"ok": False, "participants": [], "error": serialize_replay_error(exc)}
    return {"ok": True, "match_id": body.match_id, "participants": rows, "error": None}


@router.post("/reviews/from-match")
async def review_from_match(body: RealMatchReviewRequest, request: Request) -> dict[str, Any]:
    """Ingest real MATCH-V5 if needed, then build/persist an H.8 review for one participant."""
    settings = request.app.state.settings
    try:
        result = await build_real_match_review(
            body.match_id,
            body.participant_id,
            api_key=body.api_key,
            region=body.region,
            rank=body.rank,
            settings=settings,
        )
    except ReplayError as exc:
        raise HTTPException(
            status_code=400,
            detail=serialize_replay_error(exc) or {"message": str(exc)},
        ) from exc
    return result.presentation


class ReviewSyncRequest(BaseModel):
    anchors: list[dict[str, int]] = Field(min_length=1)
    media_asset_id: str = ""
    video_duration_ms: int = Field(gt=0)
    match_duration_ms: int | None = Field(default=None, gt=0)


@router.get("/reviews/{review_id}/series")
async def get_review_series(
    review_id: str,
    request: Request,
    kinds: str = "gold,cs,level",
    stride: int = 60_000,
) -> dict[str, Any]:
    """Return GST-derived series for the timeline. Does not invent coaching."""
    settings = request.app.state.settings
    payload = load_review_presentation(settings.data_dir, review_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Review not found: {review_id}")
    gst = await _gst_for_review(payload, request)
    from riftlens.pipeline.assemble.series import review_series

    kind_list = [item.strip() for item in kinds.split(",") if item.strip()]
    return review_series(
        gst,
        int(payload["participant_id"]),
        kinds=kind_list,
        stride_ms=stride,
    )


@router.post("/reviews/{review_id}/sync")
async def resync_review(
    review_id: str,
    body: ReviewSyncRequest,
    request: Request,
) -> dict[str, Any]:
    """Re-run H.10 manual sync and invalidate downstream stage cache."""
    settings = request.app.state.settings
    payload = load_review_presentation(settings.data_dir, review_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Review not found: {review_id}")
    from riftlens.domain.sync_map import SyncAnchorInconsistent, build_manual_sync
    from riftlens.orchestration.cache import StageCache
    from riftlens.orchestration.context import DOWNSTREAM_FROM_SYNC

    try:
        sync = build_manual_sync(
            [(int(item["t_video_ms"]), int(item["t_game_ms"])) for item in body.anchors],
            video_duration_ms=body.video_duration_ms,
            match_id=str(payload["match_id"]),
            media_asset_id=body.media_asset_id,
            match_duration_ms=body.match_duration_ms,
        )
    except SyncAnchorInconsistent as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload["sync_map"] = sync.to_dict()
    save_review_presentation(settings.data_dir, payload)
    StageCache(settings.cache_dir / "stages").invalidate_prefix(set(DOWNSTREAM_FROM_SYNC))
    return payload


async def _gst_for_review(payload: dict[str, Any], request: Request) -> GameStateTimeline:
    match_id = str(payload["match_id"])
    settings = request.app.state.settings
    if match_id in _ALLOWED_FIXTURES:
        match_path = _FIXTURE_ROOT / match_id / "match.json"
        timeline_path = _FIXTURE_ROOT / match_id / "timeline.json"
        from riftlens.adapters.riot.models import MatchDto, TimelineDto
        from riftlens.pipeline.ingest_riot.fact_builder import build_game_state_timeline

        match = MatchDto.model_validate(json.loads(match_path.read_text(encoding="utf-8")))
        timeline = TimelineDto.model_validate(
            json.loads(timeline_path.read_text(encoding="utf-8"))
        )
        return build_game_state_timeline(match, timeline)
    ingested = await ensure_match_ingested(match_id, settings=settings)
    from riftlens.pipeline.ingest_riot.fact_builder import build_game_state_timeline

    return build_game_state_timeline(ingested.match, ingested.timeline)
