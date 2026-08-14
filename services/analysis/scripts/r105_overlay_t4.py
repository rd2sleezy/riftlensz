"""R.10.5 T4 helper: open native replay, print League bounds readiness for overlay.

Requires RIFTLENS_R105_T4=1. Does not hardcode the ROFL path.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from riftlens.adapters.db.engine import init_database, make_session_factory
from riftlens.adapters.db.repositories import SqlGameplayRepository, SqlMatchRepository
from riftlens.config import get_settings
from riftlens.gameplay.service import GameplaySourceService
from riftlens.replay_host.factory import create_replay_host

MATCH = "NA1_5617764200"


def _resolve_rofl() -> Path | None:
    for key in (
        "RIFTLENS_R105_ROFL",
        "RIFTLENS_R10_ROFL",
        "RIFTLENS_R6_ROFL",
        "RIFTLENS_REPLAY_ROFL",
    ):
        raw = os.environ.get(key)
        if raw:
            path = Path(raw)
            return path if path.is_file() else None
    candidates = (
        Path.home() / "OneDrive" / "Documents" / "League of Legends" / "Replays",
        Path.home() / "Documents" / "League of Legends" / "Replays",
    )
    for folder in candidates:
        if not folder.is_dir():
            continue
        hits = sorted(folder.glob("*5617764200*.rofl"))
        if hits:
            return hits[0]
    return None


async def _main() -> int:
    if os.environ.get("RIFTLENS_R105_T4") != "1":
        print("SKIP: set RIFTLENS_R105_T4=1")
        return 0
    rofl = _resolve_rofl()
    if rofl is None:
        print("FAIL: NA1-5617764200.rofl not found")
        return 2
    print("ROFL", rofl)
    settings = get_settings()
    engine = init_database(settings)
    factory = make_session_factory(engine)
    host = create_replay_host()
    service = GameplaySourceService(
        host=host,
        gameplay=SqlGameplayRepository(factory),
        matches=SqlMatchRepository(factory),
    )
    try:
        env = host.check_environment()
        print("ENV live_game=", env.live_game, "install=", env.install_found)
        if env.live_game:
            print("FAIL: live game in progress — overlay must stay off")
            return 3
        imported = await service.import_rofl(
            str(rofl), now_ms=int(time.time() * 1000), match_id=MATCH
        )
        if not imported.ok or not imported.source_id:
            print("FAIL import", imported)
            return 4
        session = await service.open_linked_source(imported.source_id)
        print("SESSION", session.phase, "active=", session.is_active, "error=", session.error)
        if not session.is_active:
            return 5
        print("READY — leave League open; run desktop overlay T4 against this session")
        print("SOURCE", imported.source_id)
        # Keep process alive briefly so League stays up for manual overlay check.
        await asyncio.sleep(8)
        await service.close_session(imported.source_id, now_ms=int(time.time() * 1000))
        print("CLOSED")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
