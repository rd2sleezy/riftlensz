from __future__ import annotations

import sys
import time
from typing import Any

from fastapi import APIRouter, Request

from riftlens import __version__

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Return liveness JSON. Assumes app.state.settings and started_monotonic exist."""
    settings = request.app.state.settings
    started = float(request.app.state.started_monotonic)
    uptime_ms = int((time.monotonic() - started) * 1000)
    py = sys.version_info
    return {
        "status": "ok",
        "version": __version__,
        "python": f"{py.major}.{py.minor}.{py.micro}",
        "db_path": str(settings.db_path),
        "uptime_ms": uptime_ms,
    }
