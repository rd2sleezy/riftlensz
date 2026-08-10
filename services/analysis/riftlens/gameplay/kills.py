from __future__ import annotations

import json

from riftlens.domain.ports import MatchRepository
from riftlens.replay_host.clock.anchor_matcher import KillEvent


async def riot_kills_from_match(repo: MatchRepository, match_id: str) -> tuple[KillEvent, ...]:
    """Project persisted CHAMPION_KILL rows into R.6 matcher events."""
    parts = await repo.list_participations(match_id)
    champions = {row.participant_id: row.champion_name for row in parts}
    events = await repo.list_timeline_events(match_id)
    kills: list[KillEvent] = []
    for event in events:
        if event.type != "CHAMPION_KILL":
            continue
        payload: dict[str, object] = {}
        if event.payload:
            try:
                loaded = json.loads(event.payload)
            except json.JSONDecodeError:
                loaded = None
            if isinstance(loaded, dict):
                payload = loaded
        killer_id = event.killer_id
        victim_id = event.victim_id
        killer_champ = champions.get(killer_id) if killer_id is not None else None
        victim_champ = champions.get(victim_id) if victim_id is not None else None
        if killer_champ is None:
            killer_champ = _payload_str(payload, "killerChampionName", "killerChampion")
        if victim_champ is None:
            victim_champ = _payload_str(payload, "victimChampionName", "victimChampion")
        kills.append(
            KillEvent(
                t_ms=int(event.t_ms),
                killer_champion=killer_champ,
                victim_champion=victim_champ,
            )
        )
    return tuple(kills)


def _payload_str(payload: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None
