from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from riftlens.adapters.db.models import (
    PlayerAccountRow,
    PlayerChampionProfileRow,
    PlayerRow,
    PlayerTrendRow,
)
from riftlens.adapters.db.repositories.base import SessionRepository
from riftlens.domain.ports import (
    PlayerAccountRecord,
    PlayerChampionProfileRecord,
    PlayerRecord,
    PlayerTrendRecord,
)


class SqlPlayerRepository(SessionRepository):
    async def upsert_player(self, row: PlayerRecord) -> None:
        """Insert or replace a player row. Assumes ``row.id`` is a ULID."""
        await self.call(lambda session: session.merge(_player_row(row)))

    async def get_player(self, player_id: str) -> PlayerRecord | None:
        """Return the player or None. Assumes ``player_id`` is the local PK."""

        def work(session: Session) -> PlayerRecord | None:
            found = session.get(PlayerRow, player_id)
            return None if found is None else _player_record(found)

        return await self.call(work)

    async def upsert_account(self, row: PlayerAccountRecord) -> None:
        """Insert or replace a linked Riot account. Assumes ``puuid`` is unique."""
        await self.call(lambda session: session.merge(_account_row(row)))

    async def get_account_by_puuid(self, puuid: str) -> PlayerAccountRecord | None:
        """Return the account for ``puuid`` or None. Assumes PUUID is Riot-canonical."""

        def work(session: Session) -> PlayerAccountRecord | None:
            found = session.scalar(select(PlayerAccountRow).where(PlayerAccountRow.puuid == puuid))
            return None if found is None else _account_record(found)

        return await self.call(work)

    async def upsert_trend(self, row: PlayerTrendRecord) -> None:
        """Insert or replace a cross-game trend row. Assumes player exists."""
        await self.call(lambda session: session.merge(_trend_row(row)))

    async def get_trend(self, trend_id: str) -> PlayerTrendRecord | None:
        """Return a trend row or None. Assumes ``trend_id`` is the local PK."""

        def work(session: Session) -> PlayerTrendRecord | None:
            found = session.get(PlayerTrendRow, trend_id)
            return None if found is None else _trend_record(found)

        return await self.call(work)

    async def upsert_champion_profile(self, row: PlayerChampionProfileRecord) -> None:
        """Insert or replace a per-champion aggregate. Assumes player exists."""
        await self.call(lambda session: session.merge(_pcp_row(row)))

    async def get_champion_profile(
        self, player_id: str, champion_id: int, role: str
    ) -> PlayerChampionProfileRecord | None:
        """Return the player+champion+role profile or None. Assumes role is a stored string."""

        def work(session: Session) -> PlayerChampionProfileRecord | None:
            found = session.scalar(
                select(PlayerChampionProfileRow).where(
                    PlayerChampionProfileRow.player_id == player_id,
                    PlayerChampionProfileRow.champion_id == champion_id,
                    PlayerChampionProfileRow.role == role,
                )
            )
            return None if found is None else _pcp_record(found)

        return await self.call(work)


def _player_row(row: PlayerRecord) -> PlayerRow:
    return PlayerRow(
        id=row.id,
        display_name=row.display_name,
        is_local_user=row.is_local_user,
        created_at=row.created_at,
    )


def _player_record(row: PlayerRow) -> PlayerRecord:
    return PlayerRecord(
        id=row.id,
        display_name=row.display_name,
        is_local_user=row.is_local_user,
        created_at=row.created_at,
    )


def _account_row(row: PlayerAccountRecord) -> PlayerAccountRow:
    return PlayerAccountRow(
        id=row.id,
        player_id=row.player_id,
        puuid=row.puuid,
        game_name=row.game_name,
        tag_line=row.tag_line,
        platform=row.platform,
        region=row.region,
        summoner_level=row.summoner_level,
        tier=row.tier,
        rank_division=row.rank_division,
        league_points=row.league_points,
        rank_updated_at=row.rank_updated_at,
    )


def _account_record(row: PlayerAccountRow) -> PlayerAccountRecord:
    return PlayerAccountRecord(
        id=row.id,
        player_id=row.player_id,
        puuid=row.puuid,
        game_name=row.game_name,
        tag_line=row.tag_line,
        platform=row.platform,
        region=row.region,
        summoner_level=row.summoner_level,
        tier=row.tier,
        rank_division=row.rank_division,
        league_points=row.league_points,
        rank_updated_at=row.rank_updated_at,
    )


def _trend_row(row: PlayerTrendRecord) -> PlayerTrendRow:
    return PlayerTrendRow(
        id=row.id,
        player_id=row.player_id,
        concept_id=row.concept_id,
        metric_id=row.metric_id,
        window_start=row.window_start,
        window_end=row.window_end,
        n_matches=row.n_matches,
        value=row.value,
        prev_value=row.prev_value,
        direction=row.direction,
        significance=row.significance,
    )


def _trend_record(row: PlayerTrendRow) -> PlayerTrendRecord:
    return PlayerTrendRecord(
        id=row.id,
        player_id=row.player_id,
        concept_id=row.concept_id,
        metric_id=row.metric_id,
        window_start=row.window_start,
        window_end=row.window_end,
        n_matches=row.n_matches,
        value=row.value,
        prev_value=row.prev_value,
        direction=row.direction,
        significance=row.significance,
    )


def _pcp_row(row: PlayerChampionProfileRecord) -> PlayerChampionProfileRow:
    return PlayerChampionProfileRow(
        id=row.id,
        player_id=row.player_id,
        champion_id=row.champion_id,
        role=row.role,
        games=row.games,
        aggregates_json=row.aggregates_json,
        updated_at=row.updated_at,
    )


def _pcp_record(row: PlayerChampionProfileRow) -> PlayerChampionProfileRecord:
    return PlayerChampionProfileRecord(
        id=row.id,
        player_id=row.player_id,
        champion_id=row.champion_id,
        role=row.role,
        games=row.games,
        aggregates_json=row.aggregates_json,
        updated_at=row.updated_at,
    )
