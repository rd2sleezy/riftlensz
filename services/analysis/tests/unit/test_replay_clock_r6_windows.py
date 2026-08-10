from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from riftlens.adapters.riot.cache import RiotCache
from riftlens.adapters.riot.client import RiotClient
from riftlens.adapters.riot.errors import RiotError
from riftlens.adapters.riot.rate_limiter import RiotRateLimiter
from riftlens.config import get_settings
from riftlens.domain.clock_map import ClockConfidence, ClockMap, ClockMode
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.domain.timeline import GameStateTimeline
from riftlens.pipeline.ingest_riot.fact_builder import build_game_state_timeline
from riftlens.replay_host.api.models import EventData
from riftlens.replay_host.clock.calibrator import (
    GamestatsRelation,
    calibrate_replay_clock,
    collect_lcd_kills,
    kills_from_gst,
    merge_eventdata,
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

MATCH_ID = "NA1_5617764200"


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


async def _load_gst(match_id: str) -> GameStateTimeline | None:
    settings = get_settings()
    key = settings.riot_api_key.strip() or "RGAPI-cache-read"
    cache = RiotCache(settings.cache_dir)
    client = RiotClient(api_key=key, cache=cache, limiter=RiotRateLimiter())
    try:
        match = await client.get_match(match_id, "americas")
        timeline = await client.get_timeline(match_id, "americas")
    except RiotError:
        return None
    finally:
        await client.aclose()
    if match.metadata.match_id != match_id:
        return None
    return build_game_state_timeline(match, timeline)


@pytest.mark.skipif(
    os.environ.get("RIFTLENS_R6_T4") != "1",
    reason="set RIFTLENS_R6_T4=1 for real calibration + seek",
)
def test_t4_real_replay_calibration_and_seek() -> None:
    rofl = _resolve_t4_rofl()
    if rofl is None:
        pytest.skip("No .rofl found via RIFTLENS_R6_ROFL / well-known Replays folder")
    gst = asyncio.run(_load_gst(MATCH_ID))
    if gst is None:
        pytest.skip(
            "MATCH-V5 match+timeline for NA1_5617764200 not in H.2 cache and fetch failed"
        )
    riot_kills = kills_from_gst(gst)
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
    report: dict[str, object] = {
        "rofl": rofl.name,
        "gst_match_id": gst.match_id,
        "gst_duration_ms": gst.duration_ms,
        "riot_kill_count": len(riot_kills),
    }
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
        snapshots: list[EventData] = []
        players: list[object] = []
        try:
            snapshots.append(live.get_eventdata())
            players = live.get_playerlist()
        except ReplayError as exc:
            lcd_error = exc

        report["lcd_error"] = None if lcd_error is None else lcd_error.code.value
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
        for frac in (0.25, 0.50, 0.75, 0.95):
            game_ms = min(int(length_ms * frac), max(0, length_ms - 1_000))
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
            if outcome.ok:
                try:
                    snapshots.append(live.get_eventdata())
                    players = live.get_playerlist()
                except ReplayError:
                    pass
        eventdata = merge_eventdata(snapshots) if snapshots else None
        lcd_kills = () if eventdata is None else collect_lcd_kills(eventdata, players)
        report["uncalibrated_probe_seeks"] = probe_rows
        report["event_count"] = 0 if eventdata is None else len(eventdata.Events)
        report["lcd_kill_count"] = len(lcd_kills)

        result = calibrate_replay_clock(
            playback_length_ms=length_ms,
            match_duration_ms=gst.duration_ms,
            riot_kills=riot_kills,
            lcd_kills=lcd_kills if eventdata is not None else None,
            lcd_available=eventdata is not None,
            playback_time_s=playback.time,
            gamestats_game_time_s=None if stats is None else stats.gameTime,
        )
        report["calibration_method"] = result.method
        report["calibrated"] = result.calibrated
        report["confidence"] = result.clock.confidence.value
        report["verified"] = result.clock.verified
        report["offset_ms"] = result.offset_ms
        report["anchor_count"] = result.anchor_count
        report["residual_ms"] = result.residual_ms
        report["stdev_ms"] = result.stdev_ms
        report["unmatched_riot"] = result.unmatched_riot
        report["unmatched_lcd"] = result.unmatched_lcd
        report["match_reason"] = None if result.match is None else result.match.reason
        report["reason"] = result.reason
        print("R6_T4_REPORT", report)

        assert snap.phase in {
            ReplaySessionPhase.READY,
            ReplaySessionPhase.PLAYING,
            ReplaySessionPhase.PAUSED,
            ReplaySessionPhase.SEEKING,
        }
        assert relation in set(GamestatsRelation)
        if not result.calibrated:
            pytest.fail(
                "R.6 event-anchor calibration did not pass the >=3 / <=750ms gate: "
                f"{report}"
            )

        assert result.residual_ms is not None and result.residual_ms <= 750
        duration = gst.duration_ms
        targets = (int(duration * 0.12), int(duration * 0.50), int(duration * 0.82))
        seek_rows: list[dict[str, object]] = []
        for game_ms in targets:
            outcome = verified_seek(
                replay,
                result.clock,
                game_ms,
                lead_in_ms=0,
                then_play=True,
                session_ready=True,
                landing_tolerance_ms=REAL_SEEK_TOLERANCE_MS,
                match_duration_ms=gst.duration_ms,
            )
            err = None
            if outcome.landed_source_ms is not None and outcome.target_source_ms is not None:
                err = outcome.landed_source_ms - outcome.target_source_ms
            row = {
                "requested_game_t_ms": game_ms,
                "target_game_ms": outcome.target_game_ms,
                "source_ms": outcome.target_source_ms,
                "landed_source_ms": outcome.landed_source_ms,
                "error_ms": err,
                "ok": outcome.ok,
                "pass": bool(
                    outcome.ok and err is not None and abs(err) <= REAL_SEEK_TOLERANCE_MS
                ),
                "error": None if outcome.error is None else outcome.error.code.value,
            }
            seek_rows.append(row)
            assert row["pass"] is True, row
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
