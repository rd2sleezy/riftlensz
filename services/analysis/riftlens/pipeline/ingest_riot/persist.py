from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from typing import Any

from riftlens.adapters.riot.models import (
    EventDto,
    MatchDto,
    ParticipantDto,
    ParticipantFrameDto,
    TimelineDto,
)
from riftlens.adapters.riot.routing import region_for
from riftlens.domain.ports import (
    MatchParticipationRecord,
    MatchRecord,
    MatchRepository,
    ParticipantFrameRecord,
    TimelineEventRecord,
)
from riftlens.pipeline.ingest_riot.fact_builder import games_are_paired
from riftlens.pipeline.ingest_riot.lane_resolver import resolve_lanes


def normalize_patch(game_version: str) -> str:
    """Return ``major.minor`` from a Riot ``gameVersion``. Assumes dotted version text."""
    parts = game_version.split(".")
    if len(parts) < 2:
        return game_version
    return f"{parts[0]}.{parts[1]}"


def platform_from_match_id(match_id: str) -> str:
    """Return the platform shard encoded in a match id. Assumes ``PLATFORM_...`` form."""
    prefix = match_id.split("_", 1)[0]
    return prefix.lower()


def dumps_json(value: object) -> str:
    """Return compact deterministic JSON. Assumes ``value`` is JSON-serializable."""
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def content_hash(value: Mapping[str, Any]) -> str:
    """Return sha256 of canonical JSON. Assumes ``value`` is a Riot DTO dump."""
    return hashlib.sha256(dumps_json(value).encode("utf-8")).hexdigest()


async def persist_riot_match(
    repo: MatchRepository,
    match: MatchDto,
    timeline: TimelineDto,
    *,
    now_ms: int | None = None,
) -> str:
    """Store match + timeline tables idempotently. Returns ``match_id``.

    Assumes GST remains the in-memory analysis source; this writes §9.2 rows only.
    Re-ingesting the same pair replaces child rows so counts stay identical.
    """
    ingested_at = int(time.time() * 1000) if now_ms is None else now_ms
    match_id = match.metadata.match_id
    paired = games_are_paired(match, timeline)
    assignment = resolve_lanes(match, timeline, trust_match_positions=paired)
    header = _match_record(match, timeline, ingested_at)
    participations = [
        _participation_record(
            match_id,
            participant,
            assignment.opponents.get(participant.participant_id),
        )
        for participant in match.info.participants
    ]
    events = [
        _event_record(match_id, event)
        for frame in timeline.info.frames
        for event in frame.events
    ]
    frames = [
        _frame_record(match_id, frame.timestamp, raw_pid, pframe)
        for frame in timeline.info.frames
        for raw_pid, pframe in frame.participant_frames.items()
    ]
    await repo.upsert_match(header)
    await repo.replace_participations(match_id, participations)
    await repo.replace_timeline_events(match_id, events)
    await repo.replace_participant_frames(match_id, frames)
    return match_id


def _match_record(match: MatchDto, timeline: TimelineDto, ingested_at: int) -> MatchRecord:
    info = match.info
    platform = platform_from_match_id(match.metadata.match_id)
    start = (
        info.game_start_timestamp
        if info.game_start_timestamp is not None
        else info.game_creation
    )
    duration = info.game_duration
    duration_ms = duration * 1000 if duration < 100_000 else duration
    return MatchRecord(
        match_id=match.metadata.match_id,
        platform=platform,
        region=region_for(platform),
        queue_id=info.queue_id,
        map_id=info.map_id,
        game_version=info.game_version,
        patch=normalize_patch(info.game_version),
        game_creation=info.game_creation,
        game_start=start,
        game_duration_ms=duration_ms,
        game_end_ts=info.game_end_timestamp,
        winning_team=_winning_team(match),
        raw_match_blob=content_hash(match.model_dump(by_alias=True)),
        raw_timeline_blob=content_hash(timeline.model_dump(by_alias=True)),
        ingested_at=ingested_at,
    )


def _participation_record(
    match_id: str,
    participant: ParticipantDto,
    opponent: int | None,
) -> MatchParticipationRecord:
    if participant.champion_id is None:
        raise ValueError(f"participant {participant.participant_id} missing championId")
    perks = participant.perks
    perks_dump: object
    if perks is None:
        perks_dump = None
    elif hasattr(perks, "model_dump"):
        perks_dump = perks.model_dump(by_alias=True)
    else:
        perks_dump = perks
    stats = participant.model_dump(by_alias=True)
    return MatchParticipationRecord(
        id=_stable_id("participation", match_id, participant.participant_id),
        match_id=match_id,
        participant_id=participant.participant_id,
        puuid=participant.puuid,
        team_id=participant.team_id,
        champion_id=participant.champion_id,
        champion_name=participant.champion_name,
        team_position=_blank_to_none(participant.team_position),
        individual_position=_blank_to_none(participant.individual_position),
        lane_opponent_participant_id=opponent,
        win=1 if participant.win else 0,
        kills=participant.kills,
        deaths=participant.deaths,
        assists=participant.assists,
        total_cs=participant.total_minions_killed + participant.neutral_minions_killed,
        gold_earned=participant.gold_earned,
        gold_spent=participant.gold_spent,
        vision_score=participant.vision_score,
        summoner1_id=participant.summoner1_id,
        summoner2_id=participant.summoner2_id,
        items=dumps_json(
            [
                participant.item0,
                participant.item1,
                participant.item2,
                participant.item3,
                participant.item4,
                participant.item5,
                participant.item6,
            ]
        ),
        perks=None if perks_dump is None else dumps_json(perks_dump),
        challenges=None if participant.challenges is None else dumps_json(participant.challenges),
        stats_json=dumps_json(stats),
    )


def _event_record(match_id: str, event: EventDto) -> TimelineEventRecord:
    payload = event.model_dump(by_alias=True)
    position = payload.get("position")
    pos_x = pos_y = None
    if isinstance(position, dict):
        pos_x = _as_int(position.get("x"))
        pos_y = _as_int(position.get("y"))
    return TimelineEventRecord(
        match_id=match_id,
        t_ms=event.timestamp,
        type=event.type,
        participant_id=_as_int(payload.get("participantId")),
        victim_id=_as_int(payload.get("victimId")),
        killer_id=_as_int(payload.get("killerId")),
        pos_x=pos_x,
        pos_y=pos_y,
        payload=dumps_json(payload),
    )


def _frame_record(
    match_id: str,
    t_ms: int,
    raw_pid: str,
    pframe: ParticipantFrameDto,
) -> ParticipantFrameRecord:
    pid = pframe.participant_id if pframe.participant_id is not None else int(raw_pid)
    stats = pframe.champion_stats
    damage = pframe.damage_stats
    return ParticipantFrameRecord(
        match_id=match_id,
        t_ms=t_ms,
        participant_id=pid,
        pos_x=None if pframe.position is None else pframe.position.x,
        pos_y=None if pframe.position is None else pframe.position.y,
        current_gold=pframe.current_gold,
        total_gold=pframe.total_gold,
        gold_per_second=pframe.gold_per_second,
        xp=pframe.xp,
        level=pframe.level,
        minions_killed=pframe.minions_killed,
        jungle_minions_killed=pframe.jungle_minions_killed,
        health=_as_int(None if stats is None else stats.health),
        health_max=_as_int(None if stats is None else stats.health_max),
        power=_as_int(None if stats is None else stats.power),
        power_max=_as_int(None if stats is None else stats.power_max),
        total_damage_done_to_champions=(
            None if damage is None else damage.total_damage_done_to_champions
        ),
        total_damage_taken=None if damage is None else damage.total_damage_taken,
        champion_stats=None if stats is None else dumps_json(stats.model_dump(by_alias=True)),
        damage_stats=None if damage is None else dumps_json(damage.model_dump(by_alias=True)),
    )


def _winning_team(match: MatchDto) -> int | None:
    for team in match.info.teams:
        if team.win:
            return team.team_id
    return None


def _blank_to_none(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    return value


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _stable_id(*parts: object) -> str:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return digest[:26]
