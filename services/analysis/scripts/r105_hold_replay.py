"""Hold a native replay session open for R.10.5 overlay T4 probing."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from riftlens.adapters.db.engine import init_database, make_session_factory
from riftlens.adapters.db.repositories import SqlGameplayRepository, SqlMatchRepository
from riftlens.config import get_settings
from riftlens.gameplay.service import GameplaySourceService
from riftlens.replay_host.factory import create_replay_host

MATCH = "NA1_5617764200"
READY_FLAG = Path(__file__).resolve().parents[3] / "apps" / "desktop" / "scripts" / "_t4_ready"


def _rofl() -> Path:
    for folder in (
        Path.home() / "OneDrive" / "Documents" / "League of Legends" / "Replays",
        Path.home() / "Documents" / "League of Legends" / "Replays",
    ):
        if not folder.is_dir():
            continue
        hits = sorted(folder.glob("*5617764200*.rofl"))
        if hits:
            return hits[0]
    raise SystemExit("no rofl")


async def main() -> None:
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
        path = _rofl()
        print("ROFL", path, flush=True)
        imported = await service.import_rofl(
            str(path), now_ms=int(time.time() * 1000), match_id=MATCH
        )
        assert imported.ok and imported.source_id
        session = await service.open_linked_source(imported.source_id)
        print("SESSION", session.phase, session.is_active, flush=True)
        assert session.is_active
        READY_FLAG.write_text(imported.source_id, encoding="utf-8")
        await asyncio.sleep(60)
        await service.close_session(imported.source_id, now_ms=int(time.time() * 1000))
        print("CLOSED", flush=True)
    finally:
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
