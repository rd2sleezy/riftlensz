from __future__ import annotations

import json
from typing import Any, Literal
from urllib.parse import quote, urlencode, urljoin

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from riftlens.adapters.riot.cache import RiotCache
from riftlens.adapters.riot.errors import Forbidden, NotFound, RateLimited, ServerError
from riftlens.adapters.riot.models import (
    AccountDto,
    LeagueEntryDto,
    MatchDto,
    SummonerDto,
    TimelineDto,
)
from riftlens.adapters.riot.rate_limiter import Priority, RiotRateLimiter
from riftlens.adapters.riot.routing import platform_host, region_host

log = structlog.get_logger("riftlens.riot")

_ACCOUNT_TTL_S = 30 * 24 * 3600
_SUMMONER_LEAGUE_TTL_S = 24 * 3600
_MATCH_IDS_TTL_S = 300
_NEGATIVE_TTL_S = 600
_FORBIDDEN_MSG = (
    "your Riot API key may have expired — development keys expire every 24 hours"
)


def ttl_for_url(url: str) -> int | None:
    """Return cache TTL seconds, or None for immutable forever. Assumes a Riot URL path."""
    path = httpx.URL(url).path
    if path.endswith("/timeline") or "/timeline" in path:
        return None
    if "/lol/match/v5/matches/by-puuid/" in path:
        return _MATCH_IDS_TTL_S
    if "/lol/match/v5/matches/" in path:
        return None
    if "/riot/account/v1/accounts/" in path:
        return _ACCOUNT_TTL_S
    if "/lol/summoner/v4/" in path or "/lol/league/v4/" in path:
        return _SUMMONER_LEAGUE_TTL_S
    return _SUMMONER_LEAGUE_TTL_S


class RiotClient:
    def __init__(
        self,
        api_key: str,
        cache: RiotCache,
        limiter: RiotRateLimiter | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._cache = cache
        self._limiter = limiter or RiotRateLimiter()
        self._http = http or httpx.AsyncClient(timeout=20.0)
        self._owns_http = http is None

    async def aclose(self) -> None:
        """Close the owned httpx client. Assumes a caller-supplied client stays open."""
        if self._owns_http:
            await self._http.aclose()

    async def get_account_by_riot_id(
        self,
        game_name: str,
        tag_line: str,
        region: str,
        *,
        priority: Priority = Priority.INTERACTIVE,
    ) -> AccountDto:
        """Return ACCOUNT-V1 by Riot ID. Assumes region is a regional routing value."""
        path = (
            f"/riot/account/v1/accounts/by-riot-id/"
            f"{quote(game_name, safe='')}/{quote(tag_line, safe='')}"
        )
        payload = await self._get_json("account-by-riot-id", region_host(region), path, priority)
        return AccountDto.model_validate(payload)

    async def get_summoner_by_puuid(
        self,
        puuid: str,
        platform: str,
        *,
        priority: Priority = Priority.INTERACTIVE,
    ) -> SummonerDto:
        """Return SUMMONER-V4 by PUUID. Assumes platform is a shard id like na1."""
        path = f"/lol/summoner/v4/summoners/by-puuid/{quote(puuid, safe='')}"
        payload = await self._get_json("summoner-by-puuid", platform_host(platform), path, priority)
        return SummonerDto.model_validate(payload)

    async def get_league_entries_by_puuid(
        self,
        puuid: str,
        platform: str,
        *,
        priority: Priority = Priority.INTERACTIVE,
    ) -> list[LeagueEntryDto]:
        """Return LEAGUE-V4 entries. Assumes platform is a shard id like na1."""
        path = f"/lol/league/v4/entries/by-puuid/{quote(puuid, safe='')}"
        payload = await self._get_json("league-by-puuid", platform_host(platform), path, priority)
        if not isinstance(payload, list):
            raise ServerError(500, "league entries payload was not a list")
        return [LeagueEntryDto.model_validate(item) for item in payload]

    async def get_match_ids(
        self,
        puuid: str,
        region: str,
        *,
        start: int = 0,
        count: int = 20,
        queue: int | None = None,
        start_time: int | None = None,
        priority: Priority = Priority.INTERACTIVE,
    ) -> list[str]:
        """Return recent match ids. Assumes count is within Riot's 0–100 range."""
        query: dict[str, int] = {"start": start, "count": count}
        if queue is not None:
            query["queue"] = queue
        if start_time is not None:
            query["startTime"] = start_time
        path = f"/lol/match/v5/matches/by-puuid/{quote(puuid, safe='')}/ids?{urlencode(query)}"
        payload = await self._get_json("match-ids", region_host(region), path, priority)
        if not isinstance(payload, list):
            raise ServerError(500, "match id list payload was not a list")
        return [str(item) for item in payload]

    async def get_match(
        self,
        match_id: str,
        region: str,
        *,
        priority: Priority = Priority.INTERACTIVE,
    ) -> MatchDto:
        """Return MATCH-V5 detail. Assumes match_id includes the platform prefix."""
        path = f"/lol/match/v5/matches/{quote(match_id, safe='')}"
        payload = await self._get_json("match", region_host(region), path, priority)
        return MatchDto.model_validate(payload)

    async def get_timeline(
        self,
        match_id: str,
        region: str,
        *,
        priority: Priority = Priority.INTERACTIVE,
    ) -> TimelineDto:
        """Return MATCH-V5 timeline. Assumes match_id includes the platform prefix."""
        path = f"/lol/match/v5/matches/{quote(match_id, safe='')}/timeline"
        payload = await self._get_json("timeline", region_host(region), path, priority)
        return TimelineDto.model_validate(payload)

    async def _get_json(
        self,
        method_key: str,
        origin: str,
        path: str,
        priority: Priority,
    ) -> Any:
        url = urljoin(origin.rstrip("/") + "/", path.lstrip("/"))
        return await self._request(method_key, url, priority, retry_429=True)

    async def _request(
        self,
        method_key: str,
        url: str,
        priority: Priority,
        *,
        retry_429: bool,
        consume_token: bool = True,
    ) -> Any:
        cached = self._cache.lookup(url)
        if cached is not None:
            log.info("riot_get", url=_safe_url(url), cache_hit=True, status=cached.status)
            return self._payload_from_cache(cached.status, cached.body, url)

        if consume_token:
            await self._limiter.acquire(method_key, priority)
        try:
            payload = await self._send(method_key, url)
        except RateLimited as exc:
            if not retry_429:
                raise
            await self._limiter.penalize(exc.retry_after_s, _scope_from_type(exc.scope), method_key)
            return await self._request(
                method_key,
                url,
                priority,
                retry_429=False,
                consume_token=False,
            )
        return payload

    @retry(
        retry=retry_if_exception_type((ServerError, httpx.ConnectError, httpx.TransportError)),
        wait=wait_exponential_jitter(initial=0.05, max=2.0),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _send(self, method_key: str, url: str) -> Any:
        response = await self._http.get(url, headers={"X-Riot-Token": self._api_key})
        self._limiter.update_from_response(method_key, response.headers)
        status = response.status_code
        if status == 429:
            retry_after = int(response.headers.get("Retry-After", "1"))
            limit_type = response.headers.get("X-Rate-Limit-Type", "application")
            raise RateLimited(retry_after_s=float(retry_after), scope=limit_type)
        if status == 404:
            self._cache.put_negative(url, 404, _NEGATIVE_TTL_S)
            raise NotFound(f"riot resource not found: {_safe_url(url)}")
        if status == 403:
            raise Forbidden(_FORBIDDEN_MSG)
        if status >= 500:
            raise ServerError(status)
        if status >= 400:
            raise ServerError(status, f"unexpected riot HTTP {status}")
        self._cache.put(url, response.content, ttl_for_url(url))
        log.info("riot_get", url=_safe_url(url), cache_hit=False, status=status)
        return response.json()

    def _payload_from_cache(self, status: int, body: bytes, url: str) -> Any:
        if status == 404:
            raise NotFound(f"riot resource not found: {_safe_url(url)}")
        if status == 403:
            raise Forbidden(_FORBIDDEN_MSG)
        if status >= 400:
            raise ServerError(status, "cached riot error")
        return json.loads(body)


def _scope_from_type(limit_type: str) -> Literal["app", "method"]:
    if limit_type.lower() == "method":
        return "method"
    return "app"


def _safe_url(url: str) -> str:
    return str(httpx.URL(url).copy_with(params={}))
