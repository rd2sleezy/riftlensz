from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping
from typing import Any

import structlog

from riftlens.adapters.riot.models import (
    EventDto,
    MatchDto,
    ParticipantDto,
    ParticipantFrameDto,
    TimelineDto,
    TimelineFrameDto,
)
from riftlens.domain.enums import DataTier, FactKind, Role, Source, Team
from riftlens.domain.fact import Fact, Provenance, SubjectRef
from riftlens.domain.timeline import GameStateTimeline, ParticipantInfo
from riftlens.pipeline.ingest_riot.lane_resolver import LaneAssignment, resolve_lanes

log = structlog.get_logger("riftlens.pipeline.ingest_riot.fact_builder")

_PRODUCER = "riot_timeline_fact_builder"
_PRODUCER_VERSION = 1
_PROVENANCE = Provenance(producer=_PRODUCER, producer_version=_PRODUCER_VERSION)

_EVENT_KINDS: dict[str, FactKind] = {
    "CHAMPION_KILL": FactKind.CHAMPION_KILL,
    "ITEM_PURCHASED": FactKind.ITEM_PURCHASED,
    "ITEM_SOLD": FactKind.ITEM_SOLD,
    "ITEM_DESTROYED": FactKind.ITEM_DESTROYED,
    "WARD_PLACED": FactKind.WARD_PLACED,
    "WARD_KILL": FactKind.WARD_KILL,
    "SKILL_LEVEL_UP": FactKind.SKILL_LEVEL_UP,
    "LEVEL_UP": FactKind.LEVEL_UP,
    "BUILDING_KILL": FactKind.BUILDING_KILL,
    "TURRET_PLATE_DESTROYED": FactKind.TURRET_PLATE_DESTROYED,
    "ELITE_MONSTER_KILL": FactKind.ELITE_MONSTER_KILL,
    "PAUSE_END": FactKind.PAUSE_END,
    "GAME_END": FactKind.GAME_END,
}

_NON_CHAMP_PREFIXES = ("SRU_", "Minion", "Turret", "Inhib", "Nexus", "HA_", "TT_", "Hor")


def build_game_state_timeline(match: MatchDto, timeline: TimelineDto) -> GameStateTimeline:
    """Return a GST built from Match-V5 + Timeline-V5 DTOs.

    Assumes timeline timestamps are game-clock milliseconds. When match.info
    ``gameId`` disagrees with timeline ``GAME_END.gameId``, participant identity
    (champion/role/team/puuid) is taken from the timeline so facts stay coherent.
    """
    paired = games_are_paired(match, timeline)
    assignment = resolve_lanes(match, timeline, trust_match_positions=paired)
    participants = _participants(match, timeline, assignment, paired=paired)
    gst = GameStateTimeline(
        match_id=match.metadata.match_id,
        patch=match.info.game_version,
        queue_id=match.info.queue_id,
        duration_ms=_duration_ms(match, timeline),
        participants=participants,
        available_data_tiers=frozenset({DataTier.RIOT_ONLY, DataTier.RIOT_DERIVED}),
        lane_opponents=assignment.opponents,
    )
    gst.add_facts(_iter_facts(timeline))
    return gst


def games_are_paired(match: MatchDto, timeline: TimelineDto) -> bool:
    """Return True when match and timeline appear to be the same game.

    Assumes ``gameId`` on match.info and GAME_END is the Riot field when present.
    Missing ids are treated as paired so production ingest does not drop roles.
    """
    match_game_id = _model_extra(match.info).get("gameId")
    end_event = _find_event(timeline, "GAME_END")
    if match_game_id is None or end_event is None:
        return True
    end_id = _dump(end_event).get("gameId")
    if end_id is None:
        return True
    return int(match_game_id) == int(end_id)


def _iter_facts(timeline: TimelineDto) -> Iterator[Fact]:
    for frame in timeline.info.frames:
        yield from _facts_from_frame(frame)
        for event in frame.events:
            yield from _facts_from_event(event)


def _facts_from_frame(frame: TimelineFrameDto) -> Iterator[Fact]:
    t_ms = frame.timestamp
    for raw_pid, pframe in frame.participant_frames.items():
        pid = _frame_pid(raw_pid, pframe)
        subject = SubjectRef(kind="participant", id=pid)
        yield from _frame_stat_facts(t_ms, subject, pframe)
        yield _fact(
            t_ms,
            FactKind.OBSERVATION,
            subject,
            {"omniscient": True},
        )


def _frame_stat_facts(
    t_ms: int, subject: SubjectRef, pframe: ParticipantFrameDto
) -> Iterator[Fact]:
    if pframe.position is not None:
        pos = {"x": pframe.position.x, "y": pframe.position.y}
        yield _fact(t_ms, FactKind.POSITION, subject, pos)
    yield _fact(
        t_ms,
        FactKind.GOLD,
        subject,
        {
            "currentGold": pframe.current_gold,
            "totalGold": pframe.total_gold,
            "goldPerSecond": pframe.gold_per_second,
        },
    )
    yield _fact(t_ms, FactKind.XP, subject, {"xp": pframe.xp})
    yield _fact(t_ms, FactKind.LEVEL, subject, {"level": pframe.level})
    yield _fact(
        t_ms,
        FactKind.CS,
        subject,
        {
            "minionsKilled": pframe.minions_killed,
            "jungleMinionsKilled": pframe.jungle_minions_killed,
        },
    )
    stats = pframe.champion_stats
    yield _fact(
        t_ms,
        FactKind.HEALTH,
        subject,
        {
            "health": 0 if stats is None or stats.health is None else stats.health,
            "healthMax": 0 if stats is None or stats.health_max is None else stats.health_max,
            "healthRegen": 0 if stats is None or stats.health_regen is None else stats.health_regen,
        },
    )
    damage = {} if pframe.damage_stats is None else pframe.damage_stats.model_dump(by_alias=True)
    yield _fact(t_ms, FactKind.DAMAGE_ACCUM, subject, damage)


def _facts_from_event(event: EventDto) -> Iterator[Fact]:
    payload = _dump(event)
    kind = _EVENT_KINDS.get(event.type)
    if kind is None:
        log.debug("unknown_timeline_event", raw_type=event.type)
        payload = {"raw_type": event.type, **payload}
        kind = FactKind.DERIVED
    yield _fact(event.timestamp, kind, _event_subject(event, payload), payload)
    for pid in _observable_pids(event, payload):
        yield _fact(
            event.timestamp,
            FactKind.OBSERVATION,
            SubjectRef(kind="participant", id=pid),
            {"omniscient": False, "via": event.type},
        )


def _event_subject(event: EventDto, payload: Mapping[str, Any]) -> SubjectRef:
    for key in ("victimId", "participantId", "killerId", "creatorId"):
        value = payload.get(key)
        if isinstance(value, int) and value > 0:
            return SubjectRef(kind="participant", id=value)
    if event.type in {"PAUSE_END", "GAME_END"}:
        return SubjectRef(kind="global")
    team_id = payload.get("teamId")
    if isinstance(team_id, int) and team_id in {Team.BLUE, Team.RED}:
        return SubjectRef(kind="team", id=team_id)
    return SubjectRef(kind="global")


def _observable_pids(event: EventDto, payload: Mapping[str, Any]) -> list[int]:
    pids: list[int] = []
    if event.type == "CHAMPION_KILL":
        pids.extend(_positive_ids(payload.get("killerId"), payload.get("victimId")))
        pids.extend(_assist_ids(payload.get("assistingParticipantIds")))
    elif event.type == "WARD_KILL":
        pids.extend(_positive_ids(payload.get("killerId")))
    elif event.type in {"BUILDING_KILL", "ELITE_MONSTER_KILL"}:
        pids.extend(_positive_ids(payload.get("killerId")))
        pids.extend(_assist_ids(payload.get("assistingParticipantIds")))
    return list(dict.fromkeys(pids))


def _participants(
    match: MatchDto,
    timeline: TimelineDto,
    assignment: LaneAssignment,
    *,
    paired: bool,
) -> dict[int, ParticipantInfo]:
    match_by_pid = {p.participant_id: p for p in match.info.participants}
    puuids = _timeline_puuids(timeline)
    champs = _infer_champions(timeline) if not paired else {}
    teams = _spawn_teams(timeline)
    known = set(match_by_pid) | set(puuids) | set(assignment.roles) | set(_frame_pids(timeline))
    pids = sorted(known)
    out: dict[int, ParticipantInfo] = {}
    for pid in pids:
        match_p = match_by_pid.get(pid)
        if paired and match_p is not None:
            out[pid] = _participant_from_match(match_p, assignment)
            continue
        out[pid] = ParticipantInfo(
            participant_id=pid,
            champion=champs.get(pid) or (match_p.champion_name if match_p else "Unknown"),
            role=assignment.roles.get(pid, Role.UNKNOWN),
            team=teams.get(pid) or (Team(match_p.team_id) if match_p else Team.BLUE),
            puuid=puuids.get(pid) or (match_p.puuid if match_p else ""),
        )
    return out


def _participant_from_match(
    participant: ParticipantDto, assignment: LaneAssignment
) -> ParticipantInfo:
    return ParticipantInfo(
        participant_id=participant.participant_id,
        champion=participant.champion_name,
        role=assignment.roles.get(participant.participant_id, Role.UNKNOWN),
        team=Team(participant.team_id),
        puuid=participant.puuid,
    )


def _infer_champions(timeline: TimelineDto) -> dict[int, str]:
    counts: dict[int, Counter[str]] = {}
    for frame in timeline.info.frames:
        for event in frame.events:
            if event.type != "CHAMPION_KILL":
                continue
            payload = _dump(event)
            _count_damage_names(counts, payload.get("victimDamageReceived"))
            victim = payload.get("victimId")
            dealt = payload.get("victimDamageDealt")
            if isinstance(victim, int) and isinstance(dealt, list):
                for entry in dealt:
                    name = entry.get("name") if isinstance(entry, dict) else None
                    if isinstance(name, str) and _looks_like_champion(name):
                        counts.setdefault(victim, Counter())[name] += 1
    return {pid: counter.most_common(1)[0][0] for pid, counter in counts.items() if counter}


def _count_damage_names(counts: dict[int, Counter[str]], entries: object) -> None:
    if not isinstance(entries, list):
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("participantId")
        name = entry.get("name")
        if (
            isinstance(pid, int)
            and pid > 0
            and isinstance(name, str)
            and _looks_like_champion(name)
        ):
            counts.setdefault(pid, Counter())[name] += 1


def _looks_like_champion(name: str) -> bool:
    return bool(name) and not name.startswith(_NON_CHAMP_PREFIXES)


def _timeline_puuids(timeline: TimelineDto) -> dict[int, str]:
    out: dict[int, str] = {}
    for entry in timeline.info.participants:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("participantId")
        puuid = entry.get("puuid")
        if isinstance(pid, int) and isinstance(puuid, str):
            out[pid] = puuid
    if out:
        return out
    metadata = timeline.metadata
    if metadata is None:
        return {}
    return {index + 1: puuid for index, puuid in enumerate(metadata.participants)}


def _spawn_teams(timeline: TimelineDto) -> dict[int, Team]:
    if not timeline.info.frames:
        return {}
    out: dict[int, Team] = {}
    for raw_pid, pframe in timeline.info.frames[0].participant_frames.items():
        pid = _frame_pid(raw_pid, pframe)
        if pframe.position is None:
            continue
        out[pid] = Team.BLUE if pframe.position.x + pframe.position.y < 8000 else Team.RED
    return out


def _frame_pids(timeline: TimelineDto) -> set[int]:
    pids: set[int] = set()
    for frame in timeline.info.frames:
        for raw_pid, pframe in frame.participant_frames.items():
            pids.add(_frame_pid(raw_pid, pframe))
    return pids


def _duration_ms(match: MatchDto, timeline: TimelineDto) -> int:
    end_event = _find_event(timeline, "GAME_END")
    if end_event is not None:
        return end_event.timestamp
    if timeline.info.frames:
        return timeline.info.frames[-1].timestamp
    game_duration = match.info.game_duration
    return game_duration * 1000 if game_duration < 100_000 else game_duration


def _find_event(timeline: TimelineDto, event_type: str) -> EventDto | None:
    for frame in timeline.info.frames:
        for event in frame.events:
            if event.type == event_type:
                return event
    return None


def _frame_pid(raw_pid: str, pframe: ParticipantFrameDto) -> int:
    return pframe.participant_id if pframe.participant_id is not None else int(raw_pid)


def _dump(event: EventDto) -> dict[str, Any]:
    return event.model_dump(by_alias=True)


def _model_extra(model: object) -> dict[str, Any]:
    extra = getattr(model, "model_extra", None)
    return dict(extra) if isinstance(extra, dict) else {}


def _fact(t_ms: int, kind: FactKind, subject: SubjectRef, payload: Mapping[str, Any]) -> Fact:
    return Fact(
        t_ms=t_ms,
        kind=kind,
        subject=subject,
        payload=dict(payload),
        source=Source.RIOT_TIMELINE,
        confidence=1.0,
        provenance=_PROVENANCE,
    )


def _positive_ids(*values: object) -> list[int]:
    return [value for value in values if isinstance(value, int) and value > 0]


def _assist_ids(raw: object) -> list[int]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, int) and item > 0]
