from __future__ import annotations

import os
from pathlib import Path

import pytest
from riftlens.domain.replay_errors import ReplayErrorCode
from riftlens.replay_host.launch_strategies import windows_process_ops
from riftlens.replay_host.lcu.port import NullLcuReplayPort
from riftlens.replay_host.session import ReplaySessionPhase
from riftlens.replay_host.supervisor import (
    ReplayProcessSupervisor,
    WallClock,
    default_api_transport,
)
from riftlens.replay_host.windows.install_locator import locate_league_install

REAL_ROFL = Path(
    r"C:\Users\rylan\OneDrive\Documents\League of Legends\Replays\NA1-5617764200.rofl"
)


@pytest.mark.skipif(
    os.environ.get("RIFTLENS_R5_T4") != "1",
    reason="set RIFTLENS_R5_T4=1 for real launch",
)
@pytest.mark.skipif(not REAL_ROFL.is_file(), reason="R.0 replay file is not present")
def test_t4_real_replay_launch_reaches_ready() -> None:
    located = locate_league_install(platform="win32")
    if located.install is None:
        pytest.skip(f"League install not found: {located.error}")
    transport = default_api_transport()
    supervisor = ReplayProcessSupervisor(
        transport=transport,
        live_probe=transport,
        processes=windows_process_ops(),
        lcu=NullLcuReplayPort(),
        clock=WallClock(),
        allow_user_assisted=False,
        startup_timeout_s=120.0,
    )
    try:
        snap = supervisor.open(REAL_ROFL, located.install)
        if snap.error is not None and snap.error.code is ReplayErrorCode.LIVE_GAME_IN_PROGRESS:
            pytest.fail(
                "Live game or queue detected. Finish the live match, then re-run R.5 T4."
            )
        if snap.error is not None and snap.error.code is ReplayErrorCode.LAUNCH_TIMEOUT:
            pytest.fail(f"Replay API did not become ready: {snap.error.details}")
        assert snap.reached_ready is True, (
            f"expected READY, got {snap.phase.value} "
            f"error={None if snap.error is None else snap.error.code}"
        )
        assert snap.playback is not None
        assert snap.playback.length_ms > 0
        assert snap.winning_strategy in {"direct_exe", "shell_open", "lcu_watch"}
        assert snap.phase in {
            ReplaySessionPhase.READY,
            ReplaySessionPhase.PLAYING,
            ReplaySessionPhase.PAUSED,
        }
    finally:
        closed = supervisor.close()
    assert closed.phase is ReplaySessionPhase.CLOSED
    assert closed.relaunch_count == 0
