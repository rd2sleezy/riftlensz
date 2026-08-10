from __future__ import annotations

import os
from pathlib import Path

import pytest
from riftlens.domain.clock_map import ClockConfidence, ClockMap, ClockMode
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.clock.calibrator import (
    GamestatsRelation,
    calibrate_replay_clock,
    collect_lcd_kills,
    pause_crosscheck_gamestats,
)
from riftlens.replay_host.lcu.port import NullLcuReplayPort
from riftlens.replay_host.seek import REAL_SEEK_TOLERANCE_MS, verified_seek
from riftlens.replay_host.session import ReplaySessionPhase
from riftlens.replay_host.supervisor import (
    ReplayProcessSupervisor,
    WallClock,
    default_api_transport,
)
from riftlens.replay_host.windows.install_locator import locate_league_install

_ANALYSIS_ROOT = Path(__file__).resolve().parents[2]
_REPO = Path(__file__).resolve().parents[4]


def _resolve_t4_rofl() -> Path | None:
    for key in ("RIFTLENS_R6_ROFL", "RIFTLENS_REPLAY_ROFL"):
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
        preferred = sorted(folder.glob("*5617764200*.rofl"))
        if preferred:
            return preferred[0]
        any_rofl = sorted(folder.glob("*.rofl"))
        if any_rofl:
            return any_rofl[0]
    return None


def _find_local_gst_or_match(match_hint: str) -> tuple[object | None, str]:
    needle = match_hint.replace("-", "_")
    search_roots = (
        _ANALYSIS_ROOT / "tests" / "fixtures" / "riot",
        _REPO / "services" / "analysis" / "tests" / "fixtures" / "riot",
        Path.home() / "AppData" / "Local" / "RiftLens",
        Path.home() / ".riftlens",
    )
    hits: list[Path] = []
    for root in search_roots:
        if not root.exists():
            continue
        hits.extend(root.rglob("*timeline*.json"))
        hits.extend(root.rglob("*match.json"))
        hits.extend(root.rglob("*.sqlite"))
        hits.extend(root.rglob("*.db"))
    matching = [path for path in hits if needle in str(path).replace("-", "_")]
    if matching:
        return matching[0], f"found_unparsed:{matching[0]}"
    return None, (
        "MISSING local MATCH-V5 timeline / GST for this replay. "
        f"Searched {', '.join(str(item) for item in search_roots)} "
        f"for match hint {needle}. Automatic event-anchor calibration cannot run."
    )


@pytest.mark.skipif(
    os.environ.get("RIFTLENS_R6_T4") != "1",
    reason="set RIFTLENS_R6_T4=1 for real calibration + seek",
)
def test_t4_real_replay_calibration_and_seek() -> None:
    rofl = _resolve_t4_rofl()
    if rofl is None:
        pytest.skip("No .rofl found via RIFTLENS_R6_ROFL / well-known Replays folder")
    located = locate_league_install(platform="win32")
    if located.install is None:
        pytest.skip(f"League install not found: {located.error}")

    transport = default_api_transport()
    supervisor = ReplayProcessSupervisor(
        transport=transport,
        live_probe=transport,
        lcu=NullLcuReplayPort(),
        clock=WallClock(),
        allow_user_assisted=False,
        startup_timeout_s=120.0,
    )
    report: dict[str, object] = {"rofl": rofl.name}
    try:
        snap = supervisor.open(rofl, located.install)
        if snap.error is not None and snap.error.code is ReplayErrorCode.LIVE_GAME_IN_PROGRESS:
            pytest.fail("Live game or queue detected. Finish it, then re-run R.6 T4.")
        assert snap.reached_ready is True, (
            f"expected READY, got {snap.phase.value} "
            f"error={None if snap.error is None else snap.error.code}"
        )
        assert snap.playback is not None
        assert snap.playback.length_ms > 0
        report["phase"] = snap.phase.value
        report["length_ms"] = snap.playback.length_ms
        report["winning_strategy"] = snap.winning_strategy

        replay = transport.replay
        live = transport.live
        assert live is not None
        replay.set_playback(paused=True, readback=True)
        playback = replay.get_playback()
        try:
            stats = live.get_gamestats()
            lcd_error = None
        except ReplayError as exc:
            stats = None
            lcd_error = exc
        try:
            eventdata = live.get_eventdata()
        except ReplayError as exc:
            eventdata = None
            lcd_error = exc
        try:
            players = live.get_playerlist()
        except ReplayError:
            players = []

        report["lcd_error"] = None if lcd_error is None else lcd_error.code.value
        report["event_count_at_pause"] = 0 if eventdata is None else len(eventdata.Events)
        relation = pause_crosscheck_gamestats(
            playback_time_s=playback.time,
            stats=stats,
            offset_ms=0,
        )
        report["gamestats_gameTime"] = None if stats is None else stats.gameTime
        report["playback_time"] = playback.time
        report["gamestats_relation"] = relation.value

        length_ms = int(round(playback.length * 1000.0))
        probe_clock = ClockMap(
            mode=ClockMode.IDENTITY,
            source_start_ms=0,
            source_end_ms=length_ms,
            offset_ms=0,
            confidence=ClockConfidence.DEGRADED,
            verified=False,
        )
        probe_rows: list[dict[str, object]] = []
        for game_ms in (int(length_ms * 0.25), int(length_ms * 0.50), int(length_ms * 0.75)):
            outcome = verified_seek(
                replay,
                probe_clock,
                game_ms,
                lead_in_ms=0,
                then_play=False,
                session_ready=True,
                landing_tolerance_ms=REAL_SEEK_TOLERANCE_MS,
            )
            probe_rows.append(
                {
                    "target_source_ms": outcome.target_source_ms,
                    "landed_source_ms": outcome.landed_source_ms,
                    "ok": outcome.ok,
                    "error": None if outcome.error is None else outcome.error.code.value,
                }
            )
            if outcome.ok and live is not None:
                try:
                    eventdata = live.get_eventdata()
                    players = live.get_playerlist()
                except ReplayError:
                    pass
        report["uncalibrated_probe_seeks"] = probe_rows
        lcd_kills = () if eventdata is None else collect_lcd_kills(eventdata, players)
        report["event_count"] = 0 if eventdata is None else len(eventdata.Events)
        report["lcd_kill_count"] = len(lcd_kills)

        match_hint = rofl.stem.replace("-", "_")
        gst_path, gst_note = _find_local_gst_or_match(match_hint)
        report["gst"] = gst_note
        result = calibrate_replay_clock(
            playback_length_ms=int(round(playback.length * 1000.0)),
            match_duration_ms=None,
            riot_kills=(),
            lcd_kills=lcd_kills if eventdata is not None else None,
            lcd_available=eventdata is not None,
            playback_time_s=playback.time,
            gamestats_game_time_s=None if stats is None else stats.gameTime,
        )
        report["calibration_method"] = result.method
        report["calibrated"] = result.calibrated
        report["offset_ms"] = result.offset_ms
        report["anchor_count"] = result.anchor_count
        report["residual_ms"] = result.residual_ms
        report["reason"] = result.reason
        print("R6_T4_REPORT", report)

        assert snap.phase in {
            ReplaySessionPhase.READY,
            ReplaySessionPhase.PLAYING,
            ReplaySessionPhase.PAUSED,
            ReplaySessionPhase.SEEKING,
        }
        assert relation in set(GamestatsRelation)
        if gst_path is None:
            assert result.calibrated is False
            pytest.skip(
                "R.6 T4 stopped before calibrated seeks: "
                f"{gst_note} LCD events={report['event_count']} "
                f"kills={report['lcd_kill_count']} "
                f"gamestats_relation={relation.value} "
                f"playback.length_ms={report['length_ms']}"
            )

        assert result.calibrated is True
        assert result.residual_ms is not None and result.residual_ms <= 750
        length = int(round(playback.length * 1000.0))
        targets = (int(length * 0.12), int(length * 0.50), int(length * 0.82))
        seek_rows: list[dict[str, object]] = []
        for game_ms in targets:
            outcome = verified_seek(
                replay,
                result.clock,
                game_ms,
                lead_in_ms=0,
                then_play=True,
                machine=supervisor._machine,  # noqa: SLF001
                landing_tolerance_ms=REAL_SEEK_TOLERANCE_MS,
            )
            seek_rows.append(
                {
                    "game_ms": game_ms,
                    "ok": outcome.ok,
                    "target_source_ms": outcome.target_source_ms,
                    "landed_source_ms": outcome.landed_source_ms,
                    "error": None if outcome.error is None else outcome.error.code.value,
                }
            )
            assert outcome.ok is True, seek_rows[-1]
            assert outcome.landed_source_ms is not None
            assert outcome.target_source_ms is not None
            delta = abs(outcome.landed_source_ms - outcome.target_source_ms)
            assert delta <= REAL_SEEK_TOLERANCE_MS
        report["seeks"] = seek_rows
        print("R6_T4_SEEKS", seek_rows)
        paused = replay.set_playback(paused=True, readback=True)
        assert paused is not None and paused.paused is True
        playing = replay.set_playback(paused=False, readback=True)
        assert playing is not None and playing.paused is False
    finally:
        closed = supervisor.close()
    assert closed.phase is ReplaySessionPhase.CLOSED
    assert closed.relaunch_count == 0
