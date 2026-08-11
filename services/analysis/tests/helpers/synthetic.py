from __future__ import annotations

from collections.abc import Iterable, Mapping

from riftlens.domain.enums import DataTier, FactKind, Role, Source, Team
from riftlens.domain.fact import Fact, Provenance, SubjectRef
from riftlens.domain.geometry import Point
from riftlens.domain.timeline import GameStateTimeline, ParticipantInfo

_PROV = Provenance(producer="synthetic_h7", producer_version=1)

# Landmarks used by H.7 synthetic scenarios (Summoner's Rift world units).
BLUE_MID = Point(6000.0, 6200.0)
RED_MID = Point(8800.0, 8600.0)
BLUE_TOP = Point(1400.0, 11000.0)
RED_TOP = Point(4300.0, 13600.0)
BLUE_BOT = Point(11000.0, 1500.0)
RED_BOT = Point(13600.0, 4300.0)
BLUE_JG = Point(3500.0, 7500.0)
RED_JG = Point(11300.0, 7500.0)
RIVER_ENEMY_FOR_BLUE = Point(9200.0, 9200.0)  # enemy half + river-ish
DRAGON_PIT = Point(9866.0, 4414.0)
FAR_FROM_DRAGON = Point(800.0, 800.0)
BLUE_MID_TURRET = Point(5846.0, 6396.0)
BLUE_BASE = Point(500.0, 500.0)
RED_BASE = Point(14000.0, 14000.0)
# Near red mid outer turret (8955, 8510) for failed-dive synthetics.
ENEMY_TURRET_DIVE_FOR_BLUE = Point(9000.0, 8600.0)
# Single-linkage chain landmarks matching real mid→jg→bot merge geometry.
CLUSTER_MID = Point(9383.0, 8964.0)
CLUSTER_JG = Point(10979.0, 6454.0)
CLUSTER_BOT = Point(11659.0, 4217.0)

_LANE_POS = {
    1: BLUE_MID,
    2: BLUE_TOP,
    3: BLUE_JG,
    4: BLUE_BOT,
    5: Point(10800.0, 1700.0),
    6: RED_MID,
    7: RED_TOP,
    8: RED_JG,
    9: RED_BOT,
    10: Point(13400.0, 4100.0),
}


def roster() -> dict[int, ParticipantInfo]:
    """Return a 10-player SR roster. Assumes pid 1 is the usual subject (blue mid)."""
    specs: list[tuple[int, Team, Role, str]] = [
        (1, Team.BLUE, Role.MIDDLE, "Ahri"),
        (2, Team.BLUE, Role.TOP, "Darius"),
        (3, Team.BLUE, Role.JUNGLE, "LeeSin"),
        (4, Team.BLUE, Role.BOTTOM, "Jinx"),
        (5, Team.BLUE, Role.UTILITY, "Nautilus"),
        (6, Team.RED, Role.MIDDLE, "Syndra"),
        (7, Team.RED, Role.TOP, "Garen"),
        (8, Team.RED, Role.JUNGLE, "Warwick"),
        (9, Team.RED, Role.BOTTOM, "Ashe"),
        (10, Team.RED, Role.UTILITY, "Soraka"),
    ]
    return {
        pid: ParticipantInfo(pid, champ, role, team, f"puuid-{pid}")
        for pid, team, role, champ in specs
    }


def make_gst(
    facts: Iterable[Fact],
    *,
    match_id: str,
    duration_ms: int = 1_500_000,
    participants: Mapping[int, ParticipantInfo] | None = None,
    lane_opponents: Mapping[int, int | None] | None = None,
) -> GameStateTimeline:
    """Return a synthetic GST. Assumes facts already use game-clock ms."""
    gst = GameStateTimeline(
        match_id=match_id,
        patch="12.4.423.2790",
        queue_id=420,
        duration_ms=duration_ms,
        participants=dict(participants or roster()),
        available_data_tiers=frozenset({DataTier.RIOT_ONLY, DataTier.RIOT_DERIVED}),
        lane_opponents=dict(
            lane_opponents or {1: 6, 6: 1, 2: 7, 7: 2, 4: 9, 9: 4, 5: 10, 10: 5, 3: 8, 8: 3}
        ),
    )
    gst.add_facts(facts)
    return gst


def fact(
    t_ms: int,
    kind: FactKind,
    pid: int | None,
    payload: Mapping[str, object],
    *,
    confidence: float = 1.0,
) -> Fact:
    """Return a synthetic Fact. ``pid`` None → global subject."""
    subject = SubjectRef(kind="global") if pid is None else SubjectRef(kind="participant", id=pid)
    return Fact(
        t_ms=t_ms,
        kind=kind,
        subject=subject,
        payload=dict(payload),
        source=Source.RIOT_TIMELINE,
        confidence=confidence,
        provenance=_PROV,
    )


def quiet_frames(
    duration_ms: int,
    *,
    positions: Mapping[int, Point] | None = None,
    gold: Mapping[int, int] | None = None,
    cs: Mapping[int, int] | None = None,
    hp: Mapping[int, tuple[int, int]] | None = None,
    level: Mapping[int, int] | None = None,
    dmg: Mapping[int, int] | None = None,
    total_gold: Mapping[int, int] | None = None,
    position_at: Mapping[tuple[int, int], Point] | None = None,
) -> list[Fact]:
    """Return per-minute frames for all pids. Assumes a calm, full-HP game."""
    pos = dict(_LANE_POS)
    if positions:
        pos.update(positions)
    facts: list[Fact] = []
    t_ms = 0
    tick = 0
    while t_ms <= duration_ms:
        for pid in roster():
            point = (position_at or {}).get((t_ms, pid), pos[pid])
            g = int((gold or {}).get(pid, 120 + (tick % 4) * 40))
            tg = int((total_gold or {}).get(pid, 500 + tick * 300))
            lane_cs = int((cs or {}).get(pid, tick * 6))
            lvl = int((level or {}).get(pid, min(18, 1 + t_ms // 180_000)))
            health, hmax = (hp or {}).get(pid, (1000, 1000))
            champ_dmg = int((dmg or {}).get(pid, tick * 200))
            facts.extend(
                [
                    fact(t_ms, FactKind.POSITION, pid, {"x": point.x, "y": point.y}),
                    fact(
                        t_ms,
                        FactKind.GOLD,
                        pid,
                        {"currentGold": g, "totalGold": tg, "goldPerSecond": 0},
                    ),
                    fact(t_ms, FactKind.XP, pid, {"xp": lvl * 200}),
                    fact(t_ms, FactKind.LEVEL, pid, {"level": lvl}),
                    fact(
                        t_ms,
                        FactKind.CS,
                        pid,
                        {"minionsKilled": lane_cs, "jungleMinionsKilled": 0},
                    ),
                    fact(
                        t_ms,
                        FactKind.HEALTH,
                        pid,
                        {"health": health, "healthMax": hmax, "healthRegen": 0},
                    ),
                    fact(
                        t_ms,
                        FactKind.DAMAGE_ACCUM,
                        pid,
                        {
                            "totalDamageDoneToChampions": champ_dmg,
                            "totalDamageTaken": tick * 50,
                        },
                    ),
                    fact(t_ms, FactKind.OBSERVATION, pid, {"omniscient": True}),
                ]
            )
        t_ms += 60_000
        tick += 1
    facts.append(fact(duration_ms, FactKind.GAME_END, None, {"gameId": 1}))
    return facts


def kill(
    t_ms: int,
    victim: int,
    killer: int,
    *,
    assists: list[int] | None = None,
    position: Point,
    dealers: Mapping[int, int] | None = None,
    turret: bool = False,
    timestamps: bool = True,
) -> list[Fact]:
    """Return a CHAMPION_KILL plus non-omniscient observations for those involved."""
    dmg = dict(dealers or {killer: 400})
    received: list[dict[str, object]] = []
    base_ts = t_ms - 2000
    for index, (pid, amount) in enumerate(dmg.items()):
        entry: dict[str, object] = {"participantId": pid, "damage": amount, "name": f"Champ{pid}"}
        if timestamps:
            entry["timestamp"] = base_ts + index * 2000
        received.append(entry)
    if turret:
        received.append(
            {
                "participantId": 0,
                "damage": 200,
                "name": "Turret",
                "type": "TOWER",
                "timestamp": t_ms - 400,
            }
        )
    payload: dict[str, object] = {
        "killerId": killer,
        "victimId": victim,
        "assistingParticipantIds": list(assists or []),
        "position": {"x": position.x, "y": position.y},
        "victimDamageReceived": received,
        "bounty": 300,
    }
    facts = [fact(t_ms, FactKind.CHAMPION_KILL, victim, payload)]
    for pid in [killer, victim, *(assists or [])]:
        facts.append(
            fact(t_ms, FactKind.OBSERVATION, pid, {"omniscient": False, "via": "CHAMPION_KILL"})
        )
    return facts


def elite(
    t_ms: int,
    *,
    killer: int,
    monster: str = "DRAGON",
    team_id: int = 200,
    assists: list[int] | None = None,
) -> Fact:
    """Return an ELITE_MONSTER_KILL fact."""
    return fact(
        t_ms,
        FactKind.ELITE_MONSTER_KILL,
        killer,
        {
            "killerId": killer,
            "monsterType": monster,
            "monsterSubType": monster,
            "teamId": team_id,
            "assistingParticipantIds": list(assists or []),
        },
    )


def buy(t_ms: int, pid: int, item_id: int) -> Fact:
    """Return ITEM_PURCHASED."""
    return fact(t_ms, FactKind.ITEM_PURCHASED, pid, {"itemId": item_id})


def ward(t_ms: int, pid: int, ward_type: str = "YELLOW_TRINKET") -> Fact:
    """Return WARD_PLACED (no position — Riot does not provide one)."""
    return fact(t_ms, FactKind.WARD_PLACED, pid, {"wardType": ward_type, "creatorId": pid})


def level_up(t_ms: int, pid: int, level: int) -> Fact:
    """Return LEVEL_UP."""
    return fact(t_ms, FactKind.LEVEL_UP, pid, {"level": level})


def seen(t_ms: int, pid: int) -> Fact:
    """Return a non-omniscient observation (kill-feed / ward-visible style)."""
    return fact(t_ms, FactKind.OBSERVATION, pid, {"omniscient": False, "via": "synthetic"})


def summoner_loadout(pid: int, *, flash_id: int = 4, casts: int = 0) -> Fact:
    """Return a DERIVED summoner loadout. Not inferred from unpaired match.json."""
    return fact(
        0,
        FactKind.DERIVED,
        pid,
        {
            "kind": "summoner_loadout",
            "summoner1Id": flash_id,
            "summoner2Id": 14,
            "summoner1Casts": casts,
            "summoner2Casts": 1,
        },
    )


def plate(t_ms: int, pid: int) -> Fact:
    """Return TURRET_PLATE_DESTROYED credited to ``pid``."""
    return fact(
        t_ms,
        FactKind.TURRET_PLATE_DESTROYED,
        pid,
        {"killerId": pid, "laneType": "MID_LANE"},
    )


def healing(pid: int, amount: float, t_ms: int = 1_200_000) -> Fact:
    """Return a DERIVED healing total for R-011 when timeline DAMAGE_ACCUM lacks heal."""
    return fact(t_ms, FactKind.DERIVED, pid, {"kind": "healing", "totalHeal": amount})
