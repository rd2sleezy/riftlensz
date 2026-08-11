from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import typer
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from riftlens import __version__
from riftlens.adapters.db.engine import init_database, make_session_factory
from riftlens.adapters.db.repositories import (
    SqlCaptureRepository,
    SqlGameplayRepository,
    SqlMatchRepository,
)
from riftlens.api.capture import router as capture_router
from riftlens.api.gameplay import router as gameplay_router
from riftlens.api.health import router as health_router
from riftlens.api.media import router as media_router
from riftlens.api.reviews import router as reviews_router
from riftlens.api.sync import router as sync_router
from riftlens.config import Settings, get_settings
from riftlens.gameplay.service import GameplaySourceService
from riftlens.logging import configure_logging
from riftlens.replay_host.capture.capture_service import CaptureService
from riftlens.replay_host.factory import create_replay_host
from riftlens.replay_host.port import ReplayHostPort

_UNAUTHORIZED = JSONResponse({"detail": "Unauthorized"}, status_code=401)


def create_app(
    *,
    settings: Settings | None = None,
    token: str | None = None,
    replay_host: ReplayHostPort | None = None,
) -> FastAPI:
    """Build the FastAPI app. Assumes token is the process bearer secret when serving."""
    resolved = settings or get_settings()
    injected_host = replay_host

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = init_database(resolved)
        app.state.engine = engine
        session_factory = make_session_factory(engine)
        app.state.session_factory = session_factory
        host = injected_host if injected_host is not None else create_replay_host()
        app.state.replay_host = host
        gameplay_repo = SqlGameplayRepository(session_factory)
        capture_service = CaptureService(
            host=host,
            captures=SqlCaptureRepository(session_factory),
            gameplay=gameplay_repo,
            captures_dir=resolved.captures_dir,
            budget=resolved.capture_budget,
        )
        app.state.capture_service = capture_service
        app.state.gameplay_service = GameplaySourceService(
            host=host,
            gameplay=gameplay_repo,
            matches=SqlMatchRepository(session_factory),
            captures=capture_service,
        )
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title="RiftLens",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.state.token = token or ""
    app.state.started_monotonic = time.monotonic()

    @app.middleware("http")
    async def require_bearer(
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ) -> Any:
        if request.url.path == "/health":
            return await call_next(request)
        expected = str(request.app.state.token)
        header = request.headers.get("authorization", "")
        if header != f"Bearer {expected}" or expected == "":
            return _UNAUTHORIZED
        return await call_next(request)

    app.include_router(health_router)
    app.include_router(reviews_router)
    app.include_router(media_router)
    app.include_router(sync_router)
    app.include_router(gameplay_router)
    app.include_router(capture_router)
    return app


def _bound_port(server: uvicorn.Server) -> int:
    """Return the TCP port uvicorn bound. Assumes startup completed successfully."""
    for srv in server.servers:
        sockets = getattr(srv, "sockets", None) or []
        for sock in sockets:
            name = sock.getsockname()
            if isinstance(name, tuple) and len(name) >= 2:
                return int(name[1])
    raise RuntimeError("uvicorn bound no TCP port")


async def _serve(host: str, port: int, token: str, settings: Settings) -> None:
    app = create_app(settings=settings, token=token)
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_config=None,
        access_log=False,
        lifespan="on",
    )
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())
    deadline = time.monotonic() + 30.0
    while not server.started:
        if serve_task.done():
            exc = serve_task.exception()
            raise RuntimeError(f"uvicorn failed to start: {exc!r}")
        if time.monotonic() > deadline:
            serve_task.cancel()
            raise TimeoutError("uvicorn did not start within 30s")
        await asyncio.sleep(0.01)

    payload = {"port": _bound_port(server), "pid": os.getpid(), "version": __version__}
    sys.stdout.write(f"RIFTLENS_READY {json.dumps(payload)}\n")
    sys.stdout.flush()
    await serve_task


def cli(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(0, "--port"),
    token: str = typer.Option(..., "--token"),
) -> None:
    """Start the sidecar and block until exit. Assumes --token is a non-empty secret."""
    configure_logging()
    settings = get_settings()
    asyncio.run(_serve(host=host, port=port, token=token, settings=settings))


if __name__ == "__main__":
    typer.run(cli)
