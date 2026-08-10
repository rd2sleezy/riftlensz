from __future__ import annotations

import pytest
from riftlens.domain.gameplay_source import PlaybackState
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.session import (
    IllegalSessionTransition,
    ReplaySessionMachine,
    ReplaySessionPhase,
)


def _state(*, paused: bool = False, seeking: bool = False) -> PlaybackState:
    return PlaybackState(
        t_source_ms=2000,
        length_ms=1_902_970,
        paused=paused,
        seeking=seeking,
        speed_milli=1000,
    )


def test_full_successful_state_sequence() -> None:
    machine = ReplaySessionMachine()
    assert machine.snapshot.phase is ReplaySessionPhase.IDLE
    launching = machine.start_launch()
    assert launching.phase is ReplaySessionPhase.LAUNCHING
    connecting = machine.begin_connect()
    assert connecting.phase is ReplaySessionPhase.CONNECTING
    ready = machine.mark_ready(_state())
    assert ready.phase is ReplaySessionPhase.READY
    assert ready.reached_ready is True
    playing = machine.sync_playback(_state(paused=False))
    assert playing.phase is ReplaySessionPhase.PLAYING
    paused = machine.sync_playback(_state(paused=True))
    assert paused.phase is ReplaySessionPhase.PAUSED
    seeking = machine.sync_playback(_state(seeking=True))
    assert seeking.phase is ReplaySessionPhase.SEEKING
    machine.begin_close()
    closed = machine.finish_close()
    assert closed.phase is ReplaySessionPhase.CLOSED
    assert closed.relaunch_count == 0


def test_failed_reachable_from_idle_and_launching() -> None:
    idle = ReplaySessionMachine()
    idle.fail(ReplayError(ReplayErrorCode.LIVE_GAME_IN_PROGRESS))
    assert idle.snapshot.phase is ReplaySessionPhase.FAILED
    launching = ReplaySessionMachine()
    launching.start_launch()
    launching.fail(ReplayError(ReplayErrorCode.LAUNCH_FAILED))
    assert launching.snapshot.phase is ReplaySessionPhase.FAILED


def test_session_lost_does_not_relaunch() -> None:
    machine = ReplaySessionMachine()
    machine.start_launch()
    machine.begin_connect()
    machine.mark_ready(_state())
    machine.sync_playback(_state())
    machine.session_lost()
    assert machine.snapshot.phase is ReplaySessionPhase.FAILED
    assert machine.snapshot.error is not None
    assert machine.snapshot.error.code is ReplayErrorCode.SESSION_LOST
    assert machine.snapshot.relaunch_count == 0
    with pytest.raises(IllegalSessionTransition):
        machine.start_launch()


def test_illegal_transitions_rejected() -> None:
    machine = ReplaySessionMachine()
    with pytest.raises(IllegalSessionTransition):
        machine.mark_ready(_state())
    machine.start_launch()
    with pytest.raises(IllegalSessionTransition):
        machine.mark_ready(_state())
    machine.begin_connect()
    with pytest.raises(IllegalSessionTransition):
        machine.start_launch()
    machine.fail(ReplayError(ReplayErrorCode.LAUNCH_TIMEOUT))
    with pytest.raises(IllegalSessionTransition):
        machine.begin_close()
    with pytest.raises(IllegalSessionTransition):
        machine.finish_close()


def test_ready_is_not_idle_process_inference() -> None:
    machine = ReplaySessionMachine()
    machine.record_attempt("direct_exe")
    machine.start_launch()
    machine.note_launch(strategy="direct_exe", owns_process=True, pid=4242)
    assert machine.snapshot.pid == 4242
    assert machine.snapshot.reached_ready is False
    assert machine.snapshot.is_active is False
    machine.begin_connect()
    assert machine.snapshot.is_active is False
