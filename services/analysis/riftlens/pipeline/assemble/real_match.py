"""Ingest MATCH-V5 + timeline and assemble a real-match H.8 review."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from riftlens.adapters.db.engine import init_database, make_session_factory
from riftlens.adapters.db.repositories import SqlMatchRepository
from riftlens.adapters.riot.cache import RiotCache
from riftlens.adapters.riot.client import RiotClient
from riftlens.adapters.riot.errors import Forbidden, NotFound, RateLimited, ServerError
from riftlens.adapters.riot.models import MatchDto, TimelineDto
from riftlens.adapters.riot.rate_limiter import RiotRateLimiter
from riftlens.adapters.riot.routing import region_for
from riftlens.config import Settings, get_settings
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.pipeline.assemble.review_builder import ReviewBuildResult, build_review_from_dtos
from riftlens.pipeline.assemble.review_presentation import (
    review_to_presentation,
    save_review_presentation,
)
from riftlens.pipeline.ingest_riot.persist import persist_riot_match


@dataclass(frozen=True)
class MatchIngestResult:
    """Outcome of ensuring a match exists locally (fetch + persist if needed)."""

    match_id: str
    fetched: bool
    match: MatchDto
    timeline: TimelineDto


@dataclass(frozen=True)
class RealMatchReviewResult:
    """Persisted presentation for a real MATCH-V5 review."""

    review_id: str
    match_id: str
    participant_id: int
    champion: str
    presentation: dict[str, Any]
    ingested: bool
    build: ReviewBuildResult


def resolve_api_key(api_key: str | None, settings: Settings) -> str | None:
    """Return a non-empty Riot API key from the request or settings, else None."""
    for candidate in (api_key, settings.riot_api_key):
        if candidate is not None and candidate.strip():
            return candidate.strip()
    return None


async def ensure_match_ingested(
    match_id: str,
    *,
    api_key: str | None = None,
    region: str | None = None,
    settings: Settings | None = None,
) -> MatchIngestResult:
    """Return match+timeline DTOs, fetching from Riot when not already cached/persisted.

    Uses ``api_key`` when provided, otherwise ``settings.riot_api_key``.
    Never fabricates MATCH-V5 payloads. Cache hits do not require a live network call.
    """
    cfg = settings if settings is not None else get_settings()
    key = resolve_api_key(api_key, cfg)
    engine = init_database(cfg)
    try:
        repo = SqlMatchRepository(make_session_factory(engine))
        existing = await repo.get_match(match_id)
        if existing is not None:
            pair = await _load_match_timeline(
                match_id, key=key or "cache-only", region=region, settings=cfg
            )
            if pair is not None:
                return MatchIngestResult(
                    match_id=match_id, fetched=False, match=pair[0], timeline=pair[1]
                )
            if key is None:
                raise ReplayError(
                    ReplayErrorCode.RIOT_CREDENTIAL_MISSING,
                    details={"match_id": match_id, "suggested_action": "sign_in_api_key"},
                )
            match, timeline = await _fetch_pair(match_id, key=key, region=region, settings=cfg)
            await persist_riot_match(repo, match, timeline)
            return MatchIngestResult(
                match_id=match_id, fetched=True, match=match, timeline=timeline
            )
        if key is None:
            raise ReplayError(
                ReplayErrorCode.RIOT_CREDENTIAL_MISSING,
                details={"match_id": match_id, "suggested_action": "sign_in_api_key"},
            )
        match, timeline = await _fetch_pair(match_id, key=key, region=region, settings=cfg)
        await persist_riot_match(repo, match, timeline)
        return MatchIngestResult(match_id=match_id, fetched=True, match=match, timeline=timeline)
    finally:
        engine.dispose()


async def list_match_participants(
    match_id: str,
    *,
    api_key: str | None = None,
    region: str | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Return participant picker rows for ``match_id`` (ingesting first when needed)."""
    cfg = settings if settings is not None else get_settings()
    engine = init_database(cfg)
    try:
        repo = SqlMatchRepository(make_session_factory(engine))
        existing = await repo.get_match(match_id)
        if existing is not None:
            rows = await repo.list_participations(match_id)
            if rows:
                return [
                    {
                        "participant_id": row.participant_id,
                        "champion_name": row.champion_name,
                        "champion_id": row.champion_id,
                        "team_id": row.team_id,
                        "riot_id_game_name": None,
                        "riot_id_tagline": None,
                        "individual_position": row.individual_position,
                        "win": bool(row.win),
                    }
                    for row in rows
                ]
    finally:
        engine.dispose()
    ingested = await ensure_match_ingested(
        match_id, api_key=api_key, region=region, settings=cfg
    )
    return [
        {
            "participant_id": participant.participant_id,
            "champion_name": participant.champion_name,
            "champion_id": participant.champion_id,
            "team_id": participant.team_id,
            "riot_id_game_name": participant.riot_id_game_name,
            "riot_id_tagline": participant.riot_id_tagline,
            "individual_position": participant.individual_position or None,
            "win": participant.win,
        }
        for participant in ingested.match.info.participants
    ]


async def build_real_match_review(
    match_id: str,
    participant_id: int,
    *,
    api_key: str | None = None,
    region: str | None = None,
    rank: str = "UNRANKED",
    settings: Settings | None = None,
) -> RealMatchReviewResult:
    """Ingest if needed, build H.8 review for ``participant_id``, persist presentation."""
    if participant_id < 1 or participant_id > 10:
        raise ReplayError(
            ReplayErrorCode.PARTICIPANT_REQUIRED,
            details={"participant_id": participant_id, "suggested_action": "choose_participant"},
        )
    cfg = settings if settings is not None else get_settings()
    ingested = await ensure_match_ingested(
        match_id, api_key=api_key, region=region, settings=cfg
    )

    def _build() -> ReviewBuildResult:
        return build_review_from_dtos(
            ingested.match,
            ingested.timeline,
            participant_id,
            rank=rank,
            llm_provider="null",
            persist=True,
            settings=cfg,
        )

    built = await asyncio.to_thread(_build)
    payload = review_to_presentation(built.review, fixture_id=None)
    save_review_presentation(cfg.data_dir, payload)
    return RealMatchReviewResult(
        review_id=built.review.id,
        match_id=match_id,
        participant_id=participant_id,
        champion=built.review.champion,
        presentation=payload,
        ingested=ingested.fetched,
        build=built,
    )


async def _fetch_pair(
    match_id: str,
    *,
    key: str,
    region: str | None,
    settings: Settings,
) -> tuple[MatchDto, TimelineDto]:
    """Fetch MATCH-V5 + timeline from Riot (or forever-cache). Assumes ``key`` is non-empty."""
    platform = match_id.split("_", 1)[0]
    routing = region if region else region_for(platform)
    cache = RiotCache(settings.cache_dir)
    client = RiotClient(api_key=key, cache=cache, limiter=RiotRateLimiter())
    try:
        match = await client.get_match(match_id, routing)
        timeline = await client.get_timeline(match_id, routing)
    except (Forbidden, NotFound, RateLimited, ServerError) as exc:
        raise ReplayError(
            ReplayErrorCode.MATCH_NOT_INGESTED,
            details={
                "match_id": match_id,
                "riot_error": type(exc).__name__,
                "suggested_action": "ingest_match",
            },
        ) from exc
    finally:
        await client.aclose()
    return match, timeline


async def _load_match_timeline(
    match_id: str,
    *,
    key: str,
    region: str | None,
    settings: Settings,
) -> tuple[MatchDto, TimelineDto] | None:
    """Return DTOs from Riot forever-cache when present; None on miss/network failure."""
    try:
        return await _fetch_pair(match_id, key=key, region=region, settings=settings)
    except ReplayError:
        return None
