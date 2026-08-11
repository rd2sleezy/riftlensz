"""Real Windows T4 for R.10 — gated behind RIFTLENS_R10_T4=1."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

import pytest
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
START_MS = 1_110_000
END_MS = 1_135_000


def _resolve_rofl() -> Path | None:
    for key in ("RIFTLENS_R10_ROFL", "RIFTLENS_R6_ROFL", "RIFTLENS_REPLAY_ROFL"):
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


@pytest.mark.skipif(os.environ.get("RIFTLENS_R10_T4") != "1", reason="set RIFTLENS_R10_T4=1")
def test_r10_real_25s_capture_and_cancel() -> None:
    rofl = _resolve_rofl()
    if rofl is None:
        pytest.skip("NA1-5617764200.rofl not found")
    assert asyncio.run(_run(rofl)) is CaptureStatus.COMPLETE


async def _run(rofl: Path) -> CaptureStatus:
    settings = get_settings()
    engine = init_database(settings)
    factory = make_session_factory(engine)
    host = create_replay_host()
    gameplay_repo = SqlGameplayRepository(factory)
    captures = CaptureService(
        host=host,
        captures=SqlCaptureRepository(factory),
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
    try:
        imported = await service.import_rofl(str(rofl), now_ms=service.now_ms(), match_id=MATCH)
        assert imported.ok and imported.source_id
        source_id = imported.source_id
        session = await service.open_linked_source(source_id)
        if not session.is_active:
            pytest.skip(f"League Replay API not ready: {session.error}")
        started = await service.request_capture(
            CaptureRequest(
                source_id=source_id,
                start_game_ms=START_MS,
                end_game_ms=END_MS,
                mode=CaptureMode.CLIP,
                retention=RetentionClass.EPHEMERAL,
            ),
            now_ms=service.now_ms(),
        )
        assert started.capture_id
        result = await captures.await_result(started.capture_id, timeout_s=900.0)
        assert result.ok and result.status is CaptureStatus.COMPLETE
        assert result.manifest is not None
        assert result.manifest.clock_map_id
        assert result.manifest.requested_start_game_ms == START_MS
        assert result.manifest.requested_end_game_ms == END_MS
        assert result.artifacts
        for art in result.artifacts:
            path = settings.captures_dir / MATCH / started.capture_id / art.relative_path
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == art.sha256
            assert art.bytes > 0
        cancel_start = await service.request_capture(
            CaptureRequest(
                source_id=source_id,
                start_game_ms=START_MS,
                end_game_ms=START_MS + 60_000,
                mode=CaptureMode.CLIP,
                retention=RetentionClass.EPHEMERAL,
            ),
            now_ms=service.now_ms(),
        )
        assert cancel_start.capture_id
        await asyncio.sleep(1.0)
        cancelled = await service.cancel_capture(cancel_start.capture_id)
        assert cancelled.status is CaptureStatus.CANCELLED
        cancel_dir = settings.captures_dir / MATCH / cancel_start.capture_id
        assert not cancel_dir.exists() or not any(cancel_dir.rglob("*"))
        await service.close_session(source_id, now_ms=service.now_ms())
        return result.status
    finally:
        engine.dispose()
