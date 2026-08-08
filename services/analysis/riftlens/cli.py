from __future__ import annotations

import asyncio

import structlog
import typer

from riftlens.adapters.riot.cache import RiotCache
from riftlens.adapters.riot.client import RiotClient
from riftlens.adapters.riot.rate_limiter import RiotRateLimiter
from riftlens.config import get_settings
from riftlens.logging import configure_logging

app = typer.Typer(add_completion=False, no_args_is_help=True)
riot_app = typer.Typer(add_completion=False, no_args_is_help=True)
app.add_typer(riot_app, name="riot")

log = structlog.get_logger("riftlens.cli")


@riot_app.command("fetch-match")
def fetch_match(
    match_id: str,
    region: str = typer.Option("americas", "--region"),
) -> None:
    """Download and permanently cache a MATCH-V5 game. Assumes RIFTLENS_RIOT_API_KEY is set."""
    configure_logging()
    asyncio.run(_fetch_match(match_id=match_id, region=region))


async def _fetch_match(*, match_id: str, region: str) -> None:
    settings = get_settings()
    if not settings.riot_api_key:
        raise typer.BadParameter("RIFTLENS_RIOT_API_KEY is not set")
    cache = RiotCache(settings.cache_dir)
    client = RiotClient(
        api_key=settings.riot_api_key,
        cache=cache,
        limiter=RiotRateLimiter(),
    )
    try:
        match = await client.get_match(match_id, region)
        timeline = await client.get_timeline(match_id, region)
    finally:
        await client.aclose()
    log.info(
        "fetch_match_done",
        match_id=match.metadata.match_id,
        queue_id=match.info.queue_id,
        frames=len(timeline.info.frames),
        cache_dir=str(settings.cache_dir),
    )


def main() -> None:
    """CLI entrypoint. Assumes invocation via python -m riftlens.cli."""
    app()


if __name__ == "__main__":
    main()
