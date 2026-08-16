from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from riftlens.adapters.db.repositories import SqlPlayerRepository
from riftlens.adapters.riot.cache import RiotCache
from riftlens.adapters.riot.client import RiotClient
from riftlens.adapters.riot.errors import Forbidden, NotFound, RateLimited, ServerError
from riftlens.adapters.riot.rate_limiter import RiotRateLimiter
from riftlens.adapters.riot.routing import region_for
from riftlens.domain.ids import new_ulid
from riftlens.domain.ports import PlayerAccountRecord, PlayerRecord
from riftlens.orchestration.progress import now_ms
from riftlens.pipeline.assemble.real_match import resolve_api_key

router = APIRouter()


class LinkAccountRequest(BaseModel):
    gameName: str = Field(min_length=1)
    tagLine: str = Field(min_length=1)
    platform: str = Field(min_length=2)
    api_key: str | None = None


@router.post("/accounts/link")
async def link_account(body: LinkAccountRequest, request: Request) -> dict[str, Any]:
    """Resolve a Riot ID via H.2 and persist the account. Desktop remains credential owner."""
    settings = request.app.state.settings
    key = resolve_api_key(body.api_key, settings)
    if key is None:
        raise HTTPException(status_code=400, detail="Riot API key is required")
    platform = body.platform.lower()
    try:
        region = region_for(platform)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cache = RiotCache(settings.cache_dir)
    client = RiotClient(api_key=key, cache=cache, limiter=RiotRateLimiter())
    try:
        account = await client.get_account_by_riot_id(body.gameName, body.tagLine, region)
        entries = await client.get_league_entries_by_puuid(account.puuid, platform)
    except (Forbidden, NotFound, RateLimited, ServerError) as exc:
        raise HTTPException(status_code=400, detail=type(exc).__name__) from exc
    finally:
        await client.aclose()
    ranked = next((item for item in entries if item.queue_type == "RANKED_SOLO_5x5"), None)
    if ranked is None and entries:
        ranked = entries[0]
    factory = request.app.state.session_factory
    players = SqlPlayerRepository(factory)
    player_id = new_ulid()
    await players.upsert_player(
        PlayerRecord(
            id=player_id,
            display_name=f"{account.game_name or body.gameName}#{account.tag_line or body.tagLine}",
            is_local_user=1,
            created_at=now_ms(),
        )
    )
    await players.upsert_account(
        PlayerAccountRecord(
            id=new_ulid(),
            player_id=player_id,
            puuid=account.puuid,
            game_name=account.game_name or body.gameName,
            tag_line=account.tag_line or body.tagLine,
            platform=platform,
            region=region,
            summoner_level=None,
            tier=None if ranked is None else ranked.tier,
            rank_division=None if ranked is None else ranked.rank,
            league_points=None if ranked is None else ranked.league_points,
            rank_updated_at=now_ms(),
        )
    )
    return {
        "puuid": account.puuid,
        "game_name": account.game_name or body.gameName,
        "tag_line": account.tag_line or body.tagLine,
        "platform": platform,
        "region": region,
        "tier": None if ranked is None else ranked.tier,
        "rank": None if ranked is None else ranked.rank,
        "league_points": None if ranked is None else ranked.league_points,
        "player_id": player_id,
    }


@router.get("/accounts/{puuid}/matches")
async def list_account_matches(
    puuid: str,
    request: Request,
    count: int = 20,
    platform: str = "na1",
    api_key: str | None = None,
) -> dict[str, Any]:
    """Return recent match ids for ``puuid`` via H.2. Assumes count is 1..100."""
    settings = request.app.state.settings
    key = resolve_api_key(api_key, settings)
    if key is None:
        raise HTTPException(status_code=400, detail="Riot API key is required")
    bounded = max(1, min(count, 100))
    try:
        region = region_for(platform.lower())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cache = RiotCache(settings.cache_dir)
    client = RiotClient(api_key=key, cache=cache, limiter=RiotRateLimiter())
    try:
        match_ids = await client.get_match_ids(puuid, region, count=bounded)
    except (Forbidden, NotFound, RateLimited, ServerError) as exc:
        raise HTTPException(status_code=400, detail=type(exc).__name__) from exc
    finally:
        await client.aclose()
    return {"puuid": puuid, "match_ids": match_ids, "count": len(match_ids)}
