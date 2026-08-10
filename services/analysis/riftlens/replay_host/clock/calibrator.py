from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from riftlens.domain.clock_map import ClockConfidence, ClockMap, ClockMode
from riftlens.domain.enums import FactKind
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.domain.timeline import GameStateTimeline
from riftlens.replay_host.api.models import EventData, GameStats, LiveEvent, PlayerListEntry
from riftlens.replay_host.clock.anchor_matcher import (
    AnchorMatchResult,
    KillEvent,
    match_kill_anchors,
    normalize_identity_token,
)

DURATION_TOLERANCE_MS = 5_000
GAMESTATS_TRACK_TOLERANCE_MS = 1_500


class GamestatsRelation(StrEnum):
    """How ``gamestats.gameTime`` relates to Replay API ``playback.time``."""

    TRACKS_PLAYBACK = "TRACKS_PLAYBACK"
    TRACKS_GAME = "TRACKS_GAME"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class CalibrationResult:
    """Ladder outcome. Estimated maps are never marked verified/calibrated."""

    clock: ClockMap
    method: str
    confidence: ClockConfidence
    offset_ms: int
    anchor_count: int
    residual_ms: float | None
    stdev_ms: float | None
    duration_delta_ms: int | None
    gamestats_relation: GamestatsRelation
    lcd_available: bool
    error: ReplayError | None
    match: AnchorMatchResult | None
    reason: str
    riot_kill_count: int = 0
    lcd_kill_count: int = 0
    unmatched_riot: int = 0
    unmatched_lcd: int = 0

    @property
    def calibrated(self) -> bool:
        """Return True only for event-anchor maps that passed the residual gate."""
        return self.method == "event_anchor" and self.clock.verified


def manual_replay_clock(
    *,
    offset_ms: int,
    source_length_ms: int,
    match_duration_ms: int | None = None,
) -> ClockMap:
    """Build a caller-supplied offset map. H.9 SyncMap is not used or modified."""
    end = max(int(source_length_ms), 0)
    if match_duration_ms is not None:
        end = max(end, int(match_duration_ms) - int(offset_ms))
    return ClockMap.offset(
        offset_ms=int(offset_ms),
        source_start_ms=0,
        source_end_ms=max(end, 0),
        confidence=ClockConfidence.DEGRADED,
        verified=False,
    )


def calibrate_replay_clock(
    *,
    playback_length_ms: int,
    match_duration_ms: int | None,
    riot_kills: Sequence[KillEvent] = (),
    lcd_kills: Sequence[KillEvent] | None = None,
    lcd_available: bool = True,
    playback_time_s: float | None = None,
    gamestats_game_time_s: float | None = None,
    manual_offset_ms: int | None = None,
) -> CalibrationResult:
    """Run the §5.2 ladder. Does not seek or perform HTTP."""
    length = max(0, int(playback_length_ms))
    duration_delta = None if match_duration_ms is None else int(match_duration_ms) - length
    relation = _gamestats_relation(
        playback_time_s=playback_time_s,
        gamestats_game_time_s=gamestats_game_time_s,
        offset_ms=0,
    )
    if not lcd_available:
        relation = GamestatsRelation.UNAVAILABLE

    if manual_offset_ms is not None:
        clock = manual_replay_clock(
            offset_ms=manual_offset_ms,
            source_length_ms=length,
            match_duration_ms=match_duration_ms,
        )
        return CalibrationResult(
            clock=clock,
            method="manual",
            confidence=clock.confidence,
            offset_ms=clock.offset_ms,
            anchor_count=0,
            residual_ms=None,
            stdev_ms=None,
            duration_delta_ms=duration_delta,
            gamestats_relation=_gamestats_relation(
                playback_time_s=playback_time_s,
                gamestats_game_time_s=gamestats_game_time_s,
                offset_ms=clock.offset_ms,
            ),
            lcd_available=lcd_available,
            error=None,
            match=None,
            reason="manual_override",
        )

    match: AnchorMatchResult | None = None
    if lcd_available and lcd_kills is not None and riot_kills:
        match = match_kill_anchors(riot_kills, lcd_kills)
        if match.accepted and match.offset_ms is not None:
            clock = ClockMap.offset(
                offset_ms=match.offset_ms,
                source_start_ms=0,
                source_end_ms=length,
                confidence=ClockConfidence.GOOD,
                verified=True,
            )
            return CalibrationResult(
                clock=clock,
                method="event_anchor",
                confidence=ClockConfidence.GOOD,
                offset_ms=clock.offset_ms,
                anchor_count=match.inlier_count,
                residual_ms=match.residual_ms,
                stdev_ms=match.stdev_ms,
                duration_delta_ms=duration_delta,
                gamestats_relation=_gamestats_relation(
                    playback_time_s=playback_time_s,
                    gamestats_game_time_s=gamestats_game_time_s,
                    offset_ms=clock.offset_ms,
                ),
                lcd_available=True,
                error=None,
                match=match,
                reason="event_anchor",
                riot_kill_count=match.riot_count,
                lcd_kill_count=match.lcd_count,
                unmatched_riot=match.unmatched_riot,
                unmatched_lcd=match.unmatched_lcd,
            )

    estimated = _estimated_clock(length, match_duration_ms, duration_delta)
    error = None
    duration_bad = duration_delta is not None and abs(duration_delta) > DURATION_TOLERANCE_MS
    if match is not None and not match.accepted:
        error = ReplayError(
            ReplayErrorCode.CLOCK_CALIBRATION_FAILED,
            details={"reason": match.reason, "anchors": match.anchor_count},
        )
    elif duration_bad:
        error = ReplayError(
            ReplayErrorCode.CLOCK_CALIBRATION_FAILED,
            details={"reason": "duration_mismatch", "delta_ms": duration_delta},
        )
    elif not lcd_available:
        error = ReplayError(
            ReplayErrorCode.LIVE_CLIENT_DATA_UNAVAILABLE,
            details={"reason": "lcd_unavailable_for_calibration"},
        )
    return CalibrationResult(
        clock=estimated.clock,
        method=estimated.method,
        confidence=estimated.clock.confidence,
        offset_ms=estimated.clock.offset_ms,
        anchor_count=0 if match is None else match.inlier_count,
        residual_ms=None if match is None else match.residual_ms,
        stdev_ms=None if match is None else match.stdev_ms,
        duration_delta_ms=duration_delta,
        gamestats_relation=relation
        if estimated.clock.mode is ClockMode.UNMAPPED
        else _gamestats_relation(
            playback_time_s=playback_time_s,
            gamestats_game_time_s=gamestats_game_time_s,
            offset_ms=estimated.clock.offset_ms,
        ),
        lcd_available=lcd_available,
        error=error,
        match=match,
        reason=estimated.reason,
        riot_kill_count=0 if match is None else match.riot_count,
        lcd_kill_count=0 if match is None else match.lcd_count,
        unmatched_riot=0 if match is None else match.unmatched_riot,
        unmatched_lcd=0 if match is None else match.unmatched_lcd,
    )


def kills_from_gst(gst: GameStateTimeline) -> tuple[KillEvent, ...]:
    """Project GST ``CHAMPION_KILL`` facts into matcher events. Assumes facts use game ms."""
    kills: list[KillEvent] = []
    for fact in gst.facts(kind=FactKind.CHAMPION_KILL):
        payload = fact.payload
        killer_id = _as_int(payload.get("killerId"))
        victim_id = _as_int(payload.get("victimId"))
        killer_champ = _champ(gst, killer_id)
        victim_champ = _champ(gst, victim_id)
        kills.append(
            KillEvent(
                t_ms=int(fact.t_ms),
                killer_champion=killer_champ,
                victim_champion=victim_champ,
            )
        )
    return tuple(kills)


def kills_from_eventdata(
    eventdata: EventData,
    *,
    name_to_champion: Mapping[str, str] | None = None,
) -> tuple[KillEvent, ...]:
    """Project LCD events into matcher kills. Unobserved kill fields stay None."""
    mapping: dict[str, str] = {}
    for key, value in (name_to_champion or {}).items():
        mapping[key.strip().lower()] = value
        token = normalize_identity_token(key, kind="name")
        if token:
            mapping[token] = value
    kills: list[KillEvent] = []
    for event in eventdata.Events:
        if not _is_champion_kill(event):
            continue
        dumped = event.model_dump()
        killer_name = _str_field(dumped, "KillerName", "killerName")
        victim_name = _str_field(dumped, "VictimName", "victimName")
        killer_champ = _str_field(dumped, "KillerChampion", "killerChampion") or _lookup(
            mapping, killer_name
        )
        victim_champ = _str_field(dumped, "VictimChampion", "victimChampion") or _lookup(
            mapping, victim_name
        )
        time_s = event.EventTime
        if time_s is None:
            continue
        kills.append(
            KillEvent(
                t_ms=max(0, int(round(float(time_s) * 1000.0))),
                killer_champion=killer_champ,
                victim_champion=victim_champ,
                killer_name=killer_name,
                victim_name=victim_name,
            )
        )
    return tuple(kills)


def name_to_champion_from_playerlist(players: Sequence[PlayerListEntry]) -> dict[str, str]:
    """Build summoner-name → champion from playerlist extras when present."""
    out: dict[str, str] = {}
    for player in players:
        dumped = player.model_dump()
        champ = _str_field(dumped, "championName", "ChampionName")
        if champ is None:
            continue
        for key in ("summonerName", "riotIdGameName", "gameName", "riotId"):
            name = _str_field(dumped, key)
            if not name:
                continue
            out[name.strip().lower()] = champ
            token = normalize_identity_token(name, kind="name")
            if token:
                out[token] = champ
            if "#" in name:
                short = name.split("#", 1)[0].strip().lower()
                if short:
                    out[short] = champ
    return out


def merge_eventdata(parts: Sequence[EventData]) -> EventData:
    """Union LCD event snapshots by EventID. Sparse/stale windows are expected."""
    by_id: dict[int, LiveEvent] = {}
    anonymous: list[LiveEvent] = []
    for part in parts:
        for event in part.Events:
            if event.EventID is None:
                anonymous.append(event)
                continue
            by_id[int(event.EventID)] = event
    merged = [by_id[key] for key in sorted(by_id)]
    merged.extend(anonymous)
    return EventData(Events=merged)


def _estimated_clock(
    length_ms: int, match_duration_ms: int | None, duration_delta: int | None
) -> CalibrationResult:
    if match_duration_ms is None:
        clock = ClockMap(
            mode=ClockMode.IDENTITY,
            source_start_ms=0,
            source_end_ms=length_ms,
            offset_ms=0,
            confidence=ClockConfidence.DEGRADED,
            verified=False,
        )
        return CalibrationResult(
            clock=clock,
            method="identity_estimated",
            confidence=ClockConfidence.DEGRADED,
            offset_ms=0,
            anchor_count=0,
            residual_ms=None,
            stdev_ms=None,
            duration_delta_ms=None,
            gamestats_relation=GamestatsRelation.UNKNOWN,
            lcd_available=False,
            error=None,
            match=None,
            reason="identity_no_match_duration",
        )
    if duration_delta is not None and abs(duration_delta) <= DURATION_TOLERANCE_MS:
        clock = ClockMap(
            mode=ClockMode.IDENTITY,
            source_start_ms=0,
            source_end_ms=length_ms,
            offset_ms=0,
            confidence=ClockConfidence.DEGRADED,
            verified=False,
        )
        return CalibrationResult(
            clock=clock,
            method="identity_estimated",
            confidence=ClockConfidence.DEGRADED,
            offset_ms=0,
            anchor_count=0,
            residual_ms=None,
            stdev_ms=None,
            duration_delta_ms=duration_delta,
            gamestats_relation=GamestatsRelation.UNKNOWN,
            lcd_available=False,
            error=None,
            match=None,
            reason="identity_duration_ok",
        )
    # Rung 1: duration difference as a weak offset. Do not silently claim identity.
    offset = int(duration_delta or 0)
    clock = ClockMap.offset(
        offset_ms=offset,
        source_start_ms=0,
        source_end_ms=length_ms,
        confidence=ClockConfidence.DEGRADED,
        verified=False,
    )
    return CalibrationResult(
        clock=clock,
        method="duration_anchor",
        confidence=ClockConfidence.DEGRADED,
        offset_ms=offset,
        anchor_count=0,
        residual_ms=None,
        stdev_ms=None,
        duration_delta_ms=duration_delta,
        gamestats_relation=GamestatsRelation.UNKNOWN,
        lcd_available=False,
        error=None,
        match=None,
        reason="duration_anchor_estimated",
    )


def _gamestats_relation(
    *,
    playback_time_s: float | None,
    gamestats_game_time_s: float | None,
    offset_ms: int,
) -> GamestatsRelation:
    if playback_time_s is None or gamestats_game_time_s is None:
        return GamestatsRelation.UNAVAILABLE
    playback_ms = int(round(playback_time_s * 1000.0))
    game_ms = int(round(gamestats_game_time_s * 1000.0))
    if abs(game_ms - playback_ms) <= GAMESTATS_TRACK_TOLERANCE_MS:
        return GamestatsRelation.TRACKS_PLAYBACK
    if abs(game_ms - (playback_ms + offset_ms)) <= GAMESTATS_TRACK_TOLERANCE_MS:
        return GamestatsRelation.TRACKS_GAME
    return GamestatsRelation.UNKNOWN


def _is_champion_kill(event: LiveEvent) -> bool:
    name = (event.EventName or "").strip().lower()
    return name in {"championkill", "champion_kill"}


def _champ(gst: GameStateTimeline, pid: int | None) -> str | None:
    if pid is None or pid not in gst.participants:
        return None
    name = gst.champion_of(pid)
    return name if name and name != "Unknown" else None


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _str_field(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _lookup(mapping: Mapping[str, str], name: str | None) -> str | None:
    if name is None:
        return None
    direct = mapping.get(name.strip().lower())
    if direct:
        return direct
    token = normalize_identity_token(name, kind="name")
    if token is None:
        return None
    return mapping.get(token)


def collect_lcd_kills(
    eventdata: EventData,
    players: Sequence[PlayerListEntry] | None = None,
) -> tuple[KillEvent, ...]:
    """Convenience wrapper used by session calibration. Assumes eventdata was fetched."""
    names = name_to_champion_from_playerlist(players or ())
    return kills_from_eventdata(eventdata, name_to_champion=names)


def pause_crosscheck_gamestats(
    *,
    playback_time_s: float,
    stats: GameStats | None,
    offset_ms: int,
) -> GamestatsRelation:
    """Classify gamestats vs playback while paused. Missing stats stay UNAVAILABLE."""
    if stats is None:
        return GamestatsRelation.UNAVAILABLE
    return _gamestats_relation(
        playback_time_s=playback_time_s,
        gamestats_game_time_s=stats.gameTime,
        offset_ms=offset_ms,
    )
