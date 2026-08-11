"""Real Windows T4 for R.10 capture — requires League + NA1-5617764200.rofl.

Set RIFTLENS_R10_T4=1 to enable. Optional RIFTLENS_R6_ROFL / RIFTLENS_REPLAY_ROFL.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from riftlens.adapters.db.engine import init_database, make_session_factory
from riftlens.adapters.db.repositories import (
    SqlCaptureRepository,
    SqlGameplayRepository,
    SqlMatchRepository,
)
from riftlens.config import get_settings
from riftlens.domain.capture import CaptureMode, CaptureRequest, CaptureStatus, RetentionClass
from riftlens.gameplay.service import GameplaySourceService
from riftlens.replay_host.capture.capture_service import CaptureService
from riftlens.replay_host.factory import create_replay_host

MATCH = "NA1_5617764200"
START_MS = 1_110_000  # 18:30
END_MS = 1_135_000  # 18:55


def _resolve_rofl() -> Path | None:
    for key in ("RIFTLENS_R6_ROFL", "RIFTLENS_REPLAY_ROFL", "RIFTLENS_R10_ROFL"):
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
    if os.environ.get("RIFTLENS_R10_T4") != "1":
        print("SKIP: set RIFTLENS_R10_T4=1 for real capture T4")
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
    gameplay_repo = SqlGameplayRepository(factory)
    capture_repo = SqlCaptureRepository(factory)
    captures = CaptureService(
        host=host,
        captures=capture_repo,
        gameplay=gameplay_repo,
        captures_dir=settings.captures_dir,
        budget=settings.capture_budget,
    )
    service = GameplaySourceService(
        host=host,
        gameplay=gameplay_repo,
        matches=SqlMatchRepository(factory),
        captures=captures,
    )
    now = int(time.time() * 1000)
    imported = await service.import_rofl(str(rofl), now_ms=now, match_id=MATCH)
    print("IMPORT", imported.ok, imported.source_id, imported.error)
    if not imported.ok or imported.source_id is None:
        return 3
    source_id = imported.source_id
    print("OPENING SESSION (League will launch)...")
    session = await service.open_linked_source(source_id)
    print("SESSION", session.phase, session.error)
    if not session.is_active:
        return 4
    # Capture 18:30–18:55 CLIP
    req = CaptureRequest(
        source_id=source_id,
        start_game_ms=START_MS,
        end_game_ms=END_MS,
        mode=CaptureMode.CLIP,
        retention=RetentionClass.EPHEMERAL,
    )
    started = await service.request_capture(req, now_ms=int(time.time() * 1000))
    print("CAPTURE_START", started.capture_id, started.status, started.error)
    if started.capture_id is None:
        await service.close_session(source_id, now_ms=int(time.time() * 1000))
        return 5
    result = await captures.await_result(started.capture_id, timeout_s=900.0)
    print("CAPTURE_DONE", result.status, result.ok, result.error)
    if result.manifest is not None:
        print("MANIFEST", json.dumps(result.manifest.to_dict(), indent=2)[:2000])
    for art in result.artifacts:
        path = settings.captures_dir / MATCH / started.capture_id / art.relative_path
        exists = path.is_file()
        digest = ""
        if exists:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        print(
            "ARTIFACT",
            art.kind,
            art.relative_path,
            "bytes",
            art.bytes,
            "game_t",
            art.game_t_ms,
            "exists",
            exists,
            "sha_match",
            digest == art.sha256,
        )
    # Cancel test: short capture then cancel
    cancel_req = CaptureRequest(
        source_id=source_id,
        start_game_ms=START_MS,
        end_game_ms=START_MS + 60_000,
        mode=CaptureMode.CLIP,
        retention=RetentionClass.EPHEMERAL,
    )
    cancel_start = await service.request_capture(cancel_req, now_ms=int(time.time() * 1000))
    print("CANCEL_START", cancel_start.capture_id, cancel_start.status)
    await asyncio.sleep(1.5)
    cancelled = await service.cancel_capture(cancel_start.capture_id or "")
    print("CANCELLED", cancelled.status, cancelled.ok, cancelled.error)
    if cancel_start.capture_id:
        cancel_dir = settings.captures_dir / MATCH / cancel_start.capture_id
        leftovers = list(cancel_dir.rglob("*")) if cancel_dir.exists() else []
        print("CANCEL_LEFTOVERS", leftovers)
    await service.close_session(source_id, now_ms=int(time.time() * 1000))
    engine.dispose()
    if not result.ok or result.status is not CaptureStatus.COMPLETE:
        return 6
    if cancelled.status is not CaptureStatus.CANCELLED:
        return 7
    print("T4_PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
