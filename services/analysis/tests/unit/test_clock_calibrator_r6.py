from __future__ import annotations

import json
from pathlib import Path

from riftlens.domain.clock_map import ClockConfidence, ClockMap, ClockMode
from riftlens.domain.enums import FactKind
from riftlens.domain.replay_errors import ReplayErrorCode
from riftlens.domain.sync_map import SEEK_LEAD_IN_MS, seek_target
from riftlens.replay_host.api.models import EventData, GameStats
from riftlens.replay_host.clock.anchor_matcher import KillEvent
from riftlens.replay_host.clock.calibrator import (
    DURATION_TOLERANCE_MS,
    GamestatsRelation,
    calibrate_replay_clock,
    kills_from_eventdata,
    kills_from_gst,
    manual_replay_clock,
    pause_crosscheck_gamestats,
)
from riftlens.replay_host.seek import clamp_game_ms
from tests.helpers.gst import fact, make_gst, make_participant

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "replay_api" / "16.15"
R0_LENGTH_MS = 1_902_973


def _kills(offset_ms: int = 2_000) -> tuple[tuple[KillEvent, ...], tuple[KillEvent, ...]]:
    riot = (
        KillEvent(100_000, "Ahri", "Zed"),
        KillEvent(200_000, "Lux", "Jinx"),
        KillEvent(300_000, "Garen", "Darius"),
        KillEvent(400_000, "LeeSin", "Graves"),
    )
    lcd = tuple(
        KillEvent(item.t_ms - offset_ms, item.killer_champion, item.victim_champion)
        for item in riot
    )
    return riot, lcd


def test_identity_mapping_fallback_unverified() -> None:
    result = calibrate_replay_clock(
        playback_length_ms=R0_LENGTH_MS,
        match_duration_ms=R0_LENGTH_MS + 1_200,
        lcd_available=False,
    )
    assert result.method == "identity_estimated"
    assert result.clock.mode is ClockMode.IDENTITY
    assert result.clock.verified is False
    assert result.clock.confidence is ClockConfidence.DEGRADED
    assert result.calibrated is False
    assert result.offset_ms == 0
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.LIVE_CLIENT_DATA_UNAVAILABLE


def test_duration_sanity_pass_and_fail() -> None:
    ok = calibrate_replay_clock(
        playback_length_ms=1_900_000,
        match_duration_ms=1_903_000,
        lcd_available=False,
    )
    assert ok.duration_delta_ms is not None
    assert abs(ok.duration_delta_ms) <= DURATION_TOLERANCE_MS
    assert ok.method == "identity_estimated"

    bad = calibrate_replay_clock(
        playback_length_ms=1_800_000,
        match_duration_ms=1_900_000,
        lcd_available=False,
    )
    assert bad.duration_delta_ms == 100_000
    assert bad.method == "duration_anchor"
    assert bad.clock.mode is ClockMode.OFFSET
    assert bad.clock.verified is False
    assert bad.calibrated is False
    assert bad.error is not None
    assert bad.error.details.get("reason") == "duration_mismatch"


def test_clean_event_calibration_is_verified_good() -> None:
    riot, lcd = _kills(2_500)
    result = calibrate_replay_clock(
        playback_length_ms=R0_LENGTH_MS,
        match_duration_ms=R0_LENGTH_MS,
        riot_kills=riot,
        lcd_kills=lcd,
        playback_time_s=60.0,
        gamestats_game_time_s=60.1,
    )
    assert result.calibrated is True
    assert result.method == "event_anchor"
    assert result.clock.verified is True
    assert result.clock.confidence is ClockConfidence.GOOD
    assert result.offset_ms == 2_500
    assert result.anchor_count >= 3
    assert result.gamestats_relation is GamestatsRelation.TRACKS_PLAYBACK


def test_residual_gate_degrades_instead_of_forcing() -> None:
    riot = (
        KillEvent(100_000, "Ahri", "Zed"),
        KillEvent(200_000, "Lux", "Jinx"),
        KillEvent(300_000, "Garen", "Darius"),
        KillEvent(400_000, "LeeSin", "Graves"),
    )
    lcd = (
        KillEvent(98_000, "Ahri", "Zed"),
        KillEvent(190_000, "Lux", "Jinx"),
        KillEvent(280_000, "Garen", "Darius"),
        KillEvent(360_000, "LeeSin", "Graves"),
    )
    result = calibrate_replay_clock(
        playback_length_ms=1_900_000,
        match_duration_ms=1_902_000,
        riot_kills=riot,
        lcd_kills=lcd,
    )
    assert result.calibrated is False
    assert result.method == "identity_estimated"
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.CLOCK_CALIBRATION_FAILED
    assert result.match is not None
    assert result.match.reason == "residual_too_high"


def test_outlier_resistance_keeps_calibration() -> None:
    riot = (
        KillEvent(100_000, "Ahri", "Zed"),
        KillEvent(200_000, "Lux", "Jinx"),
        KillEvent(300_000, "Garen", "Darius"),
        KillEvent(400_000, "LeeSin", "Graves"),
        KillEvent(500_000, "Orianna", "Syndra"),
    )
    lcd = (
        KillEvent(98_000, "Ahri", "Zed"),
        KillEvent(198_000, "Lux", "Jinx"),
        KillEvent(240_000, "Garen", "Darius"),
        KillEvent(398_000, "LeeSin", "Graves"),
        KillEvent(498_000, "Orianna", "Syndra"),
    )
    result = calibrate_replay_clock(
        playback_length_ms=1_900_000,
        match_duration_ms=1_900_000,
        riot_kills=riot,
        lcd_kills=lcd,
    )
    assert result.calibrated is True
    assert result.offset_ms == 2_000
    assert result.anchor_count == 4


def test_insufficient_anchors_degrades() -> None:
    riot = (KillEvent(100_000, "Ahri", "Zed"), KillEvent(200_000, "Lux", "Jinx"))
    lcd = (KillEvent(98_000, "Ahri", "Zed"), KillEvent(198_000, "Lux", "Jinx"))
    result = calibrate_replay_clock(
        playback_length_ms=1_900_000,
        match_duration_ms=1_900_000,
        riot_kills=riot,
        lcd_kills=lcd,
    )
    assert result.calibrated is False
    assert result.match is not None
    assert result.match.reason == "insufficient_anchors"


def test_ambiguous_matching_degrades() -> None:
    riot = (
        KillEvent(100_000, "Ahri", "Zed"),
        KillEvent(200_000, "Lux", "Jinx"),
        KillEvent(300_000, "Garen", "Darius"),
    )
    lcd = (
        KillEvent(12_000, "Yasuo", "Malphite"),
        KillEvent(40_000, "Jhin", "Caitlyn"),
        KillEvent(90_000, "Sett", "Ornn"),
    )
    result = calibrate_replay_clock(
        playback_length_ms=1_900_000,
        match_duration_ms=1_900_000,
        riot_kills=riot,
        lcd_kills=lcd,
    )
    assert result.calibrated is False
    assert result.match is not None
    assert result.match.reason == "ambiguous"


def test_clockmap_game_source_round_trip() -> None:
    riot, lcd = _kills(3_000)
    result = calibrate_replay_clock(
        playback_length_ms=1_800_000,
        match_duration_ms=1_803_000,
        riot_kills=riot,
        lcd_kills=lcd,
    )
    clock = result.clock
    for game_ms in (3_000, 60_000, 300_000, 1_200_000):
        source = clock.game_to_source(game_ms)
        assert source is not None
        assert clock.source_to_game(source) == game_ms


def test_lead_in_clamps_at_game_start() -> None:
    assert clamp_game_ms(5_000, lead_in_ms=SEEK_LEAD_IN_MS, match_duration_ms=1_902_000) == 0
    mid = clamp_game_ms(1_122_000, lead_in_ms=SEEK_LEAD_IN_MS, match_duration_ms=1_800_000)
    assert mid == 1_114_000


def test_manual_offset_path_overrides_automatic() -> None:
    riot, lcd = _kills(2_000)
    result = calibrate_replay_clock(
        playback_length_ms=1_900_000,
        match_duration_ms=1_900_000,
        riot_kills=riot,
        lcd_kills=lcd,
        manual_offset_ms=12_000,
    )
    assert result.method == "manual"
    assert result.offset_ms == 12_000
    assert result.calibrated is False
    assert result.clock.verified is False
    clock = manual_replay_clock(offset_ms=12_000, source_length_ms=1_900_000)
    assert clock.game_to_source(90_000) == 78_000


def test_kills_from_gst_and_eventdata() -> None:
    gst = make_gst(
        [
            fact(100_000, FactKind.CHAMPION_KILL, 1, {"killerId": 1, "victimId": 6}),
            fact(200_000, FactKind.CHAMPION_KILL, 2, {"killerId": 2, "victimId": 7}),
        ],
        participants={
            1: make_participant(1, champion="Ahri"),
            2: make_participant(2, champion="Lux"),
            6: make_participant(6, champion="Zed"),
            7: make_participant(7, champion="Jinx"),
        },
    )
    riot = kills_from_gst(gst)
    assert len(riot) == 2
    assert riot[0].killer_champion == "Ahri"
    assert riot[0].victim_champion == "Zed"
    events = EventData.model_validate(
        {
            "Events": [
                {"EventName": "GameStart", "EventTime": 0.0},
                {
                    "EventName": "ChampionKill",
                    "EventTime": 98.0,
                    "KillerName": "Player1",
                    "VictimName": "Player6",
                    "KillerChampion": "Ahri",
                    "VictimChampion": "Zed",
                },
            ]
        }
    )
    lcd = kills_from_eventdata(events)
    assert len(lcd) == 1
    assert lcd[0].t_ms == 98_000
    assert lcd[0].killer_champion == "Ahri"


def test_gamestats_relation_tracks_game_when_offset_explains_delta() -> None:
    relation = pause_crosscheck_gamestats(
        playback_time_s=60.0,
        stats=GameStats(gameTime=62.5, gameMode="CLASSIC"),
        offset_ms=2_500,
    )
    assert relation is GamestatsRelation.TRACKS_GAME
    missing = pause_crosscheck_gamestats(playback_time_s=60.0, stats=None, offset_ms=0)
    assert missing is GamestatsRelation.UNAVAILABLE


def test_r0_length_fixture_is_sane_identity_candidate() -> None:
    samples = json.loads(FIXTURES.joinpath("playback_samples.json").read_text(encoding="utf-8"))
    length_s = samples["playback_samples"][0]["length"]
    length_ms = int(round(float(length_s) * 1000.0))
    result = calibrate_replay_clock(
        playback_length_ms=length_ms,
        match_duration_ms=length_ms,
        lcd_available=False,
    )
    assert result.method == "identity_estimated"
    assert abs(result.duration_delta_ms or 0) <= DURATION_TOLERANCE_MS


def test_h9_sync_map_seek_target_unchanged() -> None:
    from riftlens.domain.sync_map import build_manual_sync

    sync = build_manual_sync(
        [(20_000, 80_000)],
        video_duration_ms=300_000,
        match_id="m",
    )
    target = seek_target(sync, 80_000)
    assert target.seek_video_ms == 20_000 - SEEK_LEAD_IN_MS
    clock = ClockMap.from_sync_map(sync)
    assert clock.source_to_game(20_000) == sync.video_to_game(20_000)
    identity = ClockMap.identity(duration_ms=1_000)
    assert identity.verified is True
    assert identity.confidence is ClockConfidence.EXACT
