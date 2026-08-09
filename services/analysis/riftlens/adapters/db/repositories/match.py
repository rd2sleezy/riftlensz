from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from riftlens.adapters.db.models import (
    MatchParticipationRow,
    MatchRow,
    ParticipantFrameRow,
    TimelineEventRow,
)
from riftlens.adapters.db.repositories.base import SessionRepository
from riftlens.domain.ports import (
    MatchParticipationRecord,
    MatchRecord,
    ParticipantFrameRecord,
    TimelineEventRecord,
)


class SqlMatchRepository(SessionRepository):
    async def upsert_match(self, row: MatchRecord) -> None:
        """Insert or replace the match header. Assumes ``match_id`` is Riot-native."""
        await self.call(lambda session: session.merge(_match_row(row)))

    async def get_match(self, match_id: str) -> MatchRecord | None:
        """Return the match header or None. Assumes ``match_id`` is Riot-native."""

        def work(session: Session) -> MatchRecord | None:
            found = session.get(MatchRow, match_id)
            return None if found is None else _match_record(found)

        return await self.call(work)

    async def replace_participations(
        self, match_id: str, rows: Sequence[MatchParticipationRecord]
    ) -> None:
        """Replace all participation rows for a match. Assumes ``match_id`` already exists."""

        def work(session: Session) -> None:
            session.execute(
                delete(MatchParticipationRow).where(MatchParticipationRow.match_id == match_id)
            )
            for row in rows:
                session.add(_participation_row(row))

        await self.call(work)

    async def list_participations(self, match_id: str) -> Sequence[MatchParticipationRecord]:
        """Return participations ordered by participant_id. Assumes the match may be missing."""

        def work(session: Session) -> list[MatchParticipationRecord]:
            rows = session.scalars(
                select(MatchParticipationRow)
                .where(MatchParticipationRow.match_id == match_id)
                .order_by(MatchParticipationRow.participant_id)
            ).all()
            return [_participation_record(row) for row in rows]

        return await self.call(work)

    async def replace_timeline_events(
        self, match_id: str, rows: Sequence[TimelineEventRecord]
    ) -> None:
        """Replace timeline events for a match. Assumes ``match_id`` already exists."""

        def work(session: Session) -> None:
            session.execute(delete(TimelineEventRow).where(TimelineEventRow.match_id == match_id))
            for row in rows:
                session.add(_event_row(row))

        await self.call(work)

    async def list_timeline_events(self, match_id: str) -> Sequence[TimelineEventRecord]:
        """Return events ordered by t_ms then id. Assumes the match may be missing."""

        def work(session: Session) -> list[TimelineEventRecord]:
            rows = session.scalars(
                select(TimelineEventRow)
                .where(TimelineEventRow.match_id == match_id)
                .order_by(TimelineEventRow.t_ms, TimelineEventRow.id)
            ).all()
            return [_event_record(row) for row in rows]

        return await self.call(work)

    async def replace_participant_frames(
        self, match_id: str, rows: Sequence[ParticipantFrameRecord]
    ) -> None:
        """Replace frame rows for a match. Assumes ``match_id`` already exists."""

        def work(session: Session) -> None:
            session.execute(
                delete(ParticipantFrameRow).where(ParticipantFrameRow.match_id == match_id)
            )
            for row in rows:
                session.add(_frame_row(row))

        await self.call(work)

    async def list_participant_frames(self, match_id: str) -> Sequence[ParticipantFrameRecord]:
        """Return frames ordered by t_ms, participant_id. Assumes the match may be missing."""

        def work(session: Session) -> list[ParticipantFrameRecord]:
            rows = session.scalars(
                select(ParticipantFrameRow)
                .where(ParticipantFrameRow.match_id == match_id)
                .order_by(ParticipantFrameRow.t_ms, ParticipantFrameRow.participant_id)
            ).all()
            return [_frame_record(row) for row in rows]

        return await self.call(work)


def _match_row(row: MatchRecord) -> MatchRow:
    return MatchRow(
        match_id=row.match_id,
        platform=row.platform,
        region=row.region,
        queue_id=row.queue_id,
        map_id=row.map_id,
        game_version=row.game_version,
        patch=row.patch,
        game_creation=row.game_creation,
        game_start=row.game_start,
        game_duration_ms=row.game_duration_ms,
        game_end_ts=row.game_end_ts,
        winning_team=row.winning_team,
        raw_match_blob=row.raw_match_blob,
        raw_timeline_blob=row.raw_timeline_blob,
        ingested_at=row.ingested_at,
    )


def _match_record(row: MatchRow) -> MatchRecord:
    return MatchRecord(
        match_id=row.match_id,
        platform=row.platform,
        region=row.region,
        queue_id=row.queue_id,
        map_id=row.map_id,
        game_version=row.game_version,
        patch=row.patch,
        game_creation=row.game_creation,
        game_start=row.game_start,
        game_duration_ms=row.game_duration_ms,
        game_end_ts=row.game_end_ts,
        winning_team=row.winning_team,
        raw_match_blob=row.raw_match_blob,
        raw_timeline_blob=row.raw_timeline_blob,
        ingested_at=row.ingested_at,
    )


def _participation_row(row: MatchParticipationRecord) -> MatchParticipationRow:
    return MatchParticipationRow(
        id=row.id,
        match_id=row.match_id,
        participant_id=row.participant_id,
        puuid=row.puuid,
        team_id=row.team_id,
        champion_id=row.champion_id,
        champion_name=row.champion_name,
        team_position=row.team_position,
        individual_position=row.individual_position,
        lane_opponent_participant_id=row.lane_opponent_participant_id,
        win=row.win,
        kills=row.kills,
        deaths=row.deaths,
        assists=row.assists,
        total_cs=row.total_cs,
        gold_earned=row.gold_earned,
        gold_spent=row.gold_spent,
        vision_score=row.vision_score,
        summoner1_id=row.summoner1_id,
        summoner2_id=row.summoner2_id,
        items=row.items,
        perks=row.perks,
        challenges=row.challenges,
        stats_json=row.stats_json,
    )


def _participation_record(row: MatchParticipationRow) -> MatchParticipationRecord:
    return MatchParticipationRecord(
        id=row.id,
        match_id=row.match_id,
        participant_id=row.participant_id,
        puuid=row.puuid,
        team_id=row.team_id,
        champion_id=row.champion_id,
        champion_name=row.champion_name,
        team_position=row.team_position,
        individual_position=row.individual_position,
        lane_opponent_participant_id=row.lane_opponent_participant_id,
        win=row.win,
        kills=row.kills,
        deaths=row.deaths,
        assists=row.assists,
        total_cs=row.total_cs,
        gold_earned=row.gold_earned,
        gold_spent=row.gold_spent,
        vision_score=row.vision_score,
        summoner1_id=row.summoner1_id,
        summoner2_id=row.summoner2_id,
        items=row.items,
        perks=row.perks,
        challenges=row.challenges,
        stats_json=row.stats_json,
    )


def _event_row(row: TimelineEventRecord) -> TimelineEventRow:
    return TimelineEventRow(
        match_id=row.match_id,
        t_ms=row.t_ms,
        type=row.type,
        participant_id=row.participant_id,
        victim_id=row.victim_id,
        killer_id=row.killer_id,
        pos_x=row.pos_x,
        pos_y=row.pos_y,
        payload=row.payload,
    )


def _event_record(row: TimelineEventRow) -> TimelineEventRecord:
    return TimelineEventRecord(
        id=row.id,
        match_id=row.match_id,
        t_ms=row.t_ms,
        type=row.type,
        participant_id=row.participant_id,
        victim_id=row.victim_id,
        killer_id=row.killer_id,
        pos_x=row.pos_x,
        pos_y=row.pos_y,
        payload=row.payload,
    )


def _frame_row(row: ParticipantFrameRecord) -> ParticipantFrameRow:
    return ParticipantFrameRow(
        match_id=row.match_id,
        t_ms=row.t_ms,
        participant_id=row.participant_id,
        pos_x=row.pos_x,
        pos_y=row.pos_y,
        current_gold=row.current_gold,
        total_gold=row.total_gold,
        gold_per_second=row.gold_per_second,
        xp=row.xp,
        level=row.level,
        minions_killed=row.minions_killed,
        jungle_minions_killed=row.jungle_minions_killed,
        health=row.health,
        health_max=row.health_max,
        power=row.power,
        power_max=row.power_max,
        total_damage_done_to_champions=row.total_damage_done_to_champions,
        total_damage_taken=row.total_damage_taken,
        champion_stats=row.champion_stats,
        damage_stats=row.damage_stats,
    )


def _frame_record(row: ParticipantFrameRow) -> ParticipantFrameRecord:
    return ParticipantFrameRecord(
        match_id=row.match_id,
        t_ms=row.t_ms,
        participant_id=row.participant_id,
        pos_x=row.pos_x,
        pos_y=row.pos_y,
        current_gold=row.current_gold,
        total_gold=row.total_gold,
        gold_per_second=row.gold_per_second,
        xp=row.xp,
        level=row.level,
        minions_killed=row.minions_killed,
        jungle_minions_killed=row.jungle_minions_killed,
        health=row.health,
        health_max=row.health_max,
        power=row.power,
        power_max=row.power_max,
        total_damage_done_to_champions=row.total_damage_done_to_champions,
        total_damage_taken=row.total_damage_taken,
        champion_stats=row.champion_stats,
        damage_stats=row.damage_stats,
    )
