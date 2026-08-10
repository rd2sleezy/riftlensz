from __future__ import annotations

from collections.abc import Callable

from riftlens.domain.enums import FactKind, Role, Team
from riftlens.domain.geometry import Point
from riftlens.domain.timeline import GameStateTimeline, ParticipantInfo
from tests.helpers.synthetic import (
    BLUE_MID,
    BLUE_MID_TURRET,
    DRAGON_PIT,
    FAR_FROM_DRAGON,
    RIVER_ENEMY_FOR_BLUE,
    buy,
    elite,
    fact,
    healing,
    kill,
    level_up,
    make_gst,
    plate,
    quiet_frames,
    roster,
    seen,
    summoner_loadout,
    ward,
)

ScenarioFn = Callable[[], GameStateTimeline]


def _gst(
    match_id: str, extra: list, *, duration_ms: int = 1_500_000, **kwargs: object
) -> GameStateTimeline:
    frames = quiet_frames(duration_ms, **kwargs)  # type: ignore[arg-type]
    return make_gst([*frames, *extra], match_id=match_id, duration_ms=duration_ms)


def _gold(t_ms: int, pid: int, current: int, total: int):
    return fact(
        t_ms,
        FactKind.GOLD,
        pid,
        {"currentGold": current, "totalGold": total, "goldPerSecond": 0},
    )


def _cs(t_ms: int, pid: int, minions: int):
    return fact(t_ms, FactKind.CS, pid, {"minionsKilled": minions, "jungleMinionsKilled": 0})


def r001_fire() -> GameStateTimeline:
    death = 270_000
    extra = [
        seen(death - 50_000, 8),
        *kill(death, 1, 8, position=RIVER_ENEMY_FOR_BLUE, dealers={8: 500, 6: 100}),
    ]
    return _gst("S01_unseen_jungler", extra, duration_ms=600_000)


def r001_quiet() -> GameStateTimeline:
    death = 270_000
    extra = [
        seen(death - 10_000, 8),
        *kill(death, 1, 8, position=RIVER_ENEMY_FOR_BLUE, dealers={8: 500}),
    ]
    return _gst("S02_known_jungler", extra, duration_ms=600_000)


def r002_fire() -> GameStateTimeline:
    death = 300_000
    extra = [
        buy(60_000, 1, 1001),
        fact(death, FactKind.GOLD, 1, {"currentGold": 1600, "totalGold": 4000, "goldPerSecond": 0}),
        *kill(death, 1, 6, position=BLUE_MID, dealers={6: 400}),
    ]
    return _gst("S03_gold_death", extra, duration_ms=600_000)


def r002_quiet() -> GameStateTimeline:
    death = 300_000
    extra = [
        buy(60_000, 1, 1001),
        *kill(death, 1, 6, position=BLUE_MID, dealers={6: 400}),
    ]
    return _gst("S04_poor_gold_death", extra, duration_ms=600_000, gold={1: 200})


def r005_fire() -> GameStateTimeline:
    # Two deaths; CS rate after each is much lower. Custom CS via frames is uniform —
    # inject extra CS facts that drop post-death growth.
    extra = [
        *kill(180_000, 1, 6, position=BLUE_MID, dealers={6: 400}),
        *kill(480_000, 1, 6, position=BLUE_MID, dealers={6: 400}),
        fact(0, FactKind.CS, 1, {"minionsKilled": 0, "jungleMinionsKilled": 0}),
        fact(180_000, FactKind.CS, 1, {"minionsKilled": 40, "jungleMinionsKilled": 0}),
        fact(360_000, FactKind.CS, 1, {"minionsKilled": 44, "jungleMinionsKilled": 0}),
        fact(480_000, FactKind.CS, 1, {"minionsKilled": 70, "jungleMinionsKilled": 0}),
        fact(660_000, FactKind.CS, 1, {"minionsKilled": 74, "jungleMinionsKilled": 0}),
    ]
    return _gst("S05_cs_collapse", extra, duration_ms=900_000)


def r005_quiet() -> GameStateTimeline:
    extra = [
        *kill(180_000, 1, 6, position=BLUE_MID, dealers={6: 400}),
        *kill(480_000, 1, 6, position=BLUE_MID, dealers={6: 400}),
    ]
    return _gst("S06_cs_stable", extra, duration_ms=900_000, cs={1: 80})


def r007_fire() -> GameStateTimeline:
    return _gst(
        "S07_low_hp_gold",
        [buy(60_000, 1, 1001)],
        duration_ms=480_000,
        gold={1: 1500},
        hp={1: (300, 1000)},
    )


def r007_quiet() -> GameStateTimeline:
    return _gst(
        "S08_healthy_gold",
        [buy(60_000, 1, 1001)],
        duration_ms=480_000,
        gold={1: 1500},
        hp={1: (900, 1000)},
    )


def r008_fire() -> GameStateTimeline:
    extra = [elite(900_000, killer=8, monster="DRAGON", team_id=200)]
    return _gst(
        "S09_obj_noshow",
        extra,
        duration_ms=1_200_000,
        positions={1: FAR_FROM_DRAGON},
    )


def r008_quiet() -> GameStateTimeline:
    extra = [
        elite(900_000, killer=8, monster="DRAGON", team_id=200),
        plate(890_000, 1),
        plate(895_000, 1),
    ]
    return _gst("S10_obj_trade", extra, duration_ms=1_200_000, positions={1: FAR_FROM_DRAGON})


def r011_fire() -> GameStateTimeline:
    extra = [healing(8, 8000.0), healing(10, 9000.0)]
    return _gst("S11_no_antiheal", extra, duration_ms=1_500_000)


def r011_quiet() -> GameStateTimeline:
    extra = [healing(8, 8000.0), buy(1_000_000, 1, 3916)]  # Oblivion Orb
    return _gst("S12_bought_antiheal", extra, duration_ms=1_500_000)


def r012_fire() -> GameStateTimeline:
    t0 = 1_080_000
    extra = [
        seen(t0 - 40_000, 7),
        seen(t0 - 40_000, 10),
        *kill(
            t0,
            1,
            6,
            assists=[8],
            position=RIVER_ENEMY_FOR_BLUE,
            dealers={6: 300, 8: 200},
        ),
        *kill(
            t0 + 2000,
            5,
            9,
            assists=[6],
            position=RIVER_ENEMY_FOR_BLUE,
            dealers={9: 400, 6: 100},
        ),
    ]
    return _gst("S13_fight_unknown", extra, duration_ms=1_320_000)


def p001_fire() -> GameStateTimeline:
    return _gst(
        "S14_clean_lane",
        [],
        duration_ms=1_000_000,
        cs={1: 120, 6: 80},
    )


def p001_quiet() -> GameStateTimeline:
    extra = [
        *kill(120_000, 1, 6, position=BLUE_MID, dealers={6: 400}),
        *kill(300_000, 1, 6, position=BLUE_MID, dealers={6: 400}),
    ]
    return _gst("p001_quiet", extra, duration_ms=1_000_000, cs={1: 50, 6: 80})


def p005_fire() -> GameStateTimeline:
    facts = quiet_frames(1_560_000)
    # Overwrite gold frames for pid 1/6 to show a comeback.
    extra = []
    for t_ms in range(0, 1_560_001, 60_000):
        if t_ms <= 720_000:
            extra.append(_gold(t_ms, 1, 200, 2000))
            extra.append(_gold(t_ms, 6, 200, 4000))
        else:
            extra.append(_gold(t_ms, 1, 200, 9000))
            extra.append(_gold(t_ms, 6, 200, 8500))
    return make_gst([*facts, *extra], match_id="S15_recovered", duration_ms=1_560_000)


def r003_fire() -> GameStateTimeline:
    death = 300_000
    extra = [*kill(death, 1, 6, position=RIVER_ENEMY_FOR_BLUE, dealers={6: 400})]
    return _gst("r003_fire", extra, duration_ms=600_000)


def r003_quiet() -> GameStateTimeline:
    death = 300_000
    extra = [
        ward(240_000, 1),
        *kill(death, 1, 6, position=RIVER_ENEMY_FOR_BLUE, dealers={6: 400}),
    ]
    return _gst("r003_quiet", extra, duration_ms=600_000)


def r004_fire() -> GameStateTimeline:
    death = 960_000
    extra = [*kill(death, 1, 6, position=RIVER_ENEMY_FOR_BLUE, dealers={6: 500})]
    stacked = {2: BLUE_MID, 3: BLUE_MID, 4: BLUE_MID, 5: BLUE_MID}
    return _gst("r004_fire", extra, duration_ms=1_200_000, positions=stacked)


def r004_quiet() -> GameStateTimeline:
    death = 960_000
    extra = [
        *kill(
            death,
            1,
            6,
            assists=[8, 9],
            position=RIVER_ENEMY_FOR_BLUE,
            dealers={6: 200, 8: 200, 9: 200},
        )
    ]
    # Allies stacked on the death point → not alone.
    return _gst(
        "r004_quiet",
        extra,
        duration_ms=1_200_000,
        positions={1: RIVER_ENEMY_FOR_BLUE, 2: RIVER_ENEMY_FOR_BLUE, 3: RIVER_ENEMY_FOR_BLUE},
    )


def r006_fire() -> GameStateTimeline:
    return _gst("r006_fire", [], duration_ms=480_000, gold={1: 1800})


def r006_quiet() -> GameStateTimeline:
    return _gst("r006_quiet", [buy(120_000, 1, 1038)], duration_ms=480_000, gold={1: 400})


def r009_fire() -> GameStateTimeline:
    people = roster()
    people[1] = ParticipantInfo(1, "Nautilus", Role.UTILITY, Team.BLUE, "puuid-1")
    extra = [elite(900_000, killer=8, monster="DRAGON", team_id=200)]
    gst = make_gst(
        [*quiet_frames(1_200_000), *extra],
        match_id="r009_fire",
        duration_ms=1_200_000,
        participants=people,
    )
    return gst


def r009_quiet() -> GameStateTimeline:
    people = roster()
    people[1] = ParticipantInfo(1, "Nautilus", Role.UTILITY, Team.BLUE, "puuid-1")
    extra = [ward(850_000, 1), elite(900_000, killer=8, monster="DRAGON", team_id=200)]
    return make_gst(
        [*quiet_frames(1_200_000), *extra],
        match_id="r009_quiet",
        duration_ms=1_200_000,
        participants=people,
    )


def r010_fire() -> GameStateTimeline:
    people = roster()
    people[1] = ParticipantInfo(1, "Nautilus", Role.UTILITY, Team.BLUE, "puuid-1")
    extra = [
        buy(500_000, 1, 1001),
        buy(700_000, 1, 1001),
        buy(900_000, 1, 1001),
        buy(1_100_000, 1, 1036),
    ]
    return make_gst(
        [*quiet_frames(1_320_000), *extra],
        match_id="r010_fire",
        duration_ms=1_320_000,
        participants=people,
    )


def r010_quiet() -> GameStateTimeline:
    people = roster()
    people[1] = ParticipantInfo(1, "Nautilus", Role.UTILITY, Team.BLUE, "puuid-1")
    extra = [
        buy(500_000, 1, 2055),
        buy(700_000, 1, 2055),
        buy(900_000, 1, 2055),
        buy(1_100_000, 1, 2055),
    ]
    return make_gst(
        [*quiet_frames(1_320_000), *extra],
        match_id="r010_quiet",
        duration_ms=1_320_000,
        participants=people,
    )


def r013_fire() -> GameStateTimeline:
    extra = []
    for _index, t_ms in enumerate((300_000, 480_000, 660_000)):
        extra.extend(kill(t_ms, 1, 6, position=BLUE_MID, dealers={6: 400}))
        extra.extend(kill(t_ms + 1500, 6, 3, position=BLUE_MID, dealers={3: 400}))
    return _gst("r013_fire", extra, duration_ms=900_000)


def r013_quiet() -> GameStateTimeline:
    extra = []
    for t_ms in (300_000, 480_000, 660_000):
        extra.extend(kill(t_ms, 6, 1, position=BLUE_MID, dealers={1: 400}))
        extra.extend(kill(t_ms + 1500, 8, 3, position=BLUE_MID, dealers={3: 400}))
    return _gst("r013_quiet", extra, duration_ms=900_000)


def r014_fire() -> GameStateTimeline:
    t0 = 960_000
    extra = [
        *kill(t0, 6, 1, assists=[3], position=RIVER_ENEMY_FOR_BLUE, dealers={1: 300, 3: 200}),
        *kill(t0 + 1000, 8, 2, position=RIVER_ENEMY_FOR_BLUE, dealers={2: 400}),
    ]
    return _gst("r014_fire", extra, duration_ms=1_200_000)


def r014_quiet() -> GameStateTimeline:
    t0 = 960_000
    extra = [
        *kill(t0, 6, 1, assists=[3], position=RIVER_ENEMY_FOR_BLUE, dealers={1: 300, 3: 200}),
        *kill(t0 + 1000, 8, 2, position=RIVER_ENEMY_FOR_BLUE, dealers={2: 400}),
        elite(t0 + 8000, killer=1, monster="DRAGON", team_id=100, assists=[3]),
    ]
    return _gst("r014_quiet", extra, duration_ms=1_200_000)


def r015_fire() -> GameStateTimeline:
    extra = [
        *kill(
            240_000,
            1,
            6,
            assists=[8],
            position=BLUE_MID_TURRET,
            dealers={6: 300, 8: 200},
            turret=True,
        )
    ]
    return _gst("r015_fire", extra, duration_ms=480_000, hp={1: (300, 1000)})


def r015_quiet() -> GameStateTimeline:
    extra = [*kill(240_000, 1, 6, position=RIVER_ENEMY_FOR_BLUE, dealers={6: 400})]
    return _gst("r015_quiet", extra, duration_ms=480_000)


def r016_fire() -> GameStateTimeline:
    extra = [
        level_up(200_000, 6, 6),
        level_up(240_000, 1, 6),
        fact(240_000, FactKind.LEVEL, 1, {"level": 6}),
        fact(200_000, FactKind.LEVEL, 6, {"level": 6}),
        fact(
            180_000,
            FactKind.DAMAGE_ACCUM,
            1,
            {"totalDamageTaken": 100, "totalDamageDoneToChampions": 0},
        ),
        fact(
            280_000,
            FactKind.DAMAGE_ACCUM,
            1,
            {"totalDamageTaken": 500, "totalDamageDoneToChampions": 0},
        ),
        fact(180_000, FactKind.HEALTH, 1, {"health": 800, "healthMax": 1000, "healthRegen": 0}),
        *kill(250_000, 1, 6, position=BLUE_MID, dealers={6: 400}),
    ]
    return _gst("r016_fire", extra, duration_ms=480_000)


def r016_quiet() -> GameStateTimeline:
    extra = [
        level_up(230_000, 6, 6),
        level_up(240_000, 1, 6),
        fact(240_000, FactKind.LEVEL, 1, {"level": 6}),
        fact(230_000, FactKind.LEVEL, 6, {"level": 6}),
    ]
    return _gst("r016_quiet", extra, duration_ms=480_000)


def r017_fire() -> GameStateTimeline:
    extra = [
        fact(240_000, FactKind.CS, 1, {"minionsKilled": 50, "jungleMinionsKilled": 0}),
        fact(300_000, FactKind.CS, 1, {"minionsKilled": 51, "jungleMinionsKilled": 0}),
    ]
    return _gst(
        "r017_fire",
        extra,
        duration_ms=480_000,
        position_at={
            (300_000, 1): Point(7400.0, 11000.0),
            (360_000, 1): Point(7400.0, 11000.0),
        },
    )


def r017_quiet() -> GameStateTimeline:
    return _gst("r017_quiet", [], duration_ms=480_000, positions={1: BLUE_MID}, cs={1: 80})


def r018_fire() -> GameStateTimeline:
    extra = []
    for t_ms in (180_000, 300_000, 420_000):
        extra.extend(kill(t_ms, 1, 6, position=RIVER_ENEMY_FOR_BLUE, dealers={6: 400}))
    return _gst("r018_fire", extra, duration_ms=600_000)


def r018_quiet() -> GameStateTimeline:
    extra = [*kill(180_000, 1, 6, position=BLUE_MID, dealers={6: 400})]
    return _gst("r018_quiet", extra, duration_ms=600_000)


def r019_fire() -> GameStateTimeline:
    return _gst(
        "r019_fire",
        [],
        duration_ms=1_500_000,
        dmg={1: 1000, 2: 8000, 3: 7000, 4: 9000, 5: 2000},
        total_gold={1: 12000, 2: 10000, 3: 10000, 4: 10000, 5: 8000},
    )


def r019_quiet() -> GameStateTimeline:
    return _gst(
        "r019_quiet",
        [],
        duration_ms=1_500_000,
        dmg={1: 9000, 2: 8000, 3: 7000, 4: 9000, 5: 2000},
        total_gold={1: 11000, 2: 10000, 3: 10000, 4: 10000, 5: 8000},
    )


def r020_fire() -> GameStateTimeline:
    extra = [
        summoner_loadout(1, casts=0),
        *kill(
            300_000,
            1,
            6,
            position=BLUE_MID,
            dealers={6: 200, 8: 200},
            timestamps=True,
        ),
    ]
    return _gst("r020_fire", extra, duration_ms=480_000)


def r020_quiet() -> GameStateTimeline:
    extra = [
        summoner_loadout(1, casts=3),
        *kill(300_000, 1, 6, position=BLUE_MID, dealers={6: 400}),
    ]
    return _gst("r020_quiet", extra, duration_ms=480_000)


def p002_fire() -> GameStateTimeline:
    extra = []
    for t_ms in (300_000, 540_000, 780_000):
        extra.append(buy(t_ms, 1, 1038))  # BF sword 1300 total / 1300 base in 12.4?
        extra.append(_gold(t_ms - 1000, 1, 1400, 4000))
        extra.append(_cs(t_ms, 1, 40 + t_ms // 20_000))
        extra.append(_cs(t_ms + 60_000, 1, 48 + t_ms // 20_000))
    return _gst("p002_fire", extra, duration_ms=1_000_000, gold={1: 200})


def p002_quiet() -> GameStateTimeline:
    return _gst("p002_quiet", [buy(300_000, 1, 1001)], duration_ms=600_000)


def p003_fire() -> GameStateTimeline:
    extra = [
        elite(480_000, killer=1, monster="DRAGON", team_id=100),
        elite(720_000, killer=3, monster="RIFTHERALD", team_id=100, assists=[1]),
        elite(960_000, killer=1, monster="DRAGON", team_id=100),
        elite(1_200_000, killer=3, monster="BARON", team_id=100, assists=[1]),
    ]
    return _gst("p003_fire", extra, duration_ms=1_320_000, positions={1: DRAGON_PIT})


def p003_quiet() -> GameStateTimeline:
    extra = [
        elite(480_000, killer=8, monster="DRAGON", team_id=200),
        elite(720_000, killer=8, monster="RIFTHERALD", team_id=200),
        elite(960_000, killer=8, monster="DRAGON", team_id=200),
        elite(1_200_000, killer=8, monster="BARON", team_id=200),
    ]
    return _gst("p003_quiet", extra, duration_ms=1_320_000, positions={1: FAR_FROM_DRAGON})


def p004_fire() -> GameStateTimeline:
    people = roster()
    people[1] = ParticipantInfo(1, "Nautilus", Role.UTILITY, Team.BLUE, "puuid-1")
    extra = [
        buy(500_000, 1, 2055),
        buy(700_000, 1, 2055),
        buy(900_000, 1, 2055),
        buy(1_100_000, 1, 2055),
    ]
    return make_gst(
        [*quiet_frames(1_320_000), *extra],
        match_id="p004_fire",
        duration_ms=1_320_000,
        participants=people,
    )


def p004_quiet() -> GameStateTimeline:
    people = roster()
    people[1] = ParticipantInfo(1, "Nautilus", Role.UTILITY, Team.BLUE, "puuid-1")
    extra = [buy(500_000, 1, 1001), buy(700_000, 1, 1001), buy(900_000, 1, 1001)]
    return make_gst(
        [*quiet_frames(1_320_000), *extra],
        match_id="p004_quiet",
        duration_ms=1_320_000,
        participants=people,
    )


def quiet_game(n: int) -> GameStateTimeline:
    """Diverse quiet games for fire-rate: vary duration and gold, no deaths."""
    duration = 900_000 + (n % 7) * 120_000
    g = 150 + (n * 17) % 400
    return _gst(f"quiet_{n:03d}", [], duration_ms=duration, gold={1: g, 6: g + 50})


MUST_FIRE: dict[str, ScenarioFn] = {
    "R-001": r001_fire,
    "R-002": r002_fire,
    "R-003": r003_fire,
    "R-004": r004_fire,
    "R-005": r005_fire,
    "R-006": r006_fire,
    "R-007": r007_fire,
    "R-008": r008_fire,
    "R-009": r009_fire,
    "R-010": r010_fire,
    "R-011": r011_fire,
    "R-012": r012_fire,
    "R-013": r013_fire,
    "R-014": r014_fire,
    "R-015": r015_fire,
    "R-016": r016_fire,
    "R-017": r017_fire,
    "R-018": r018_fire,
    "R-019": r019_fire,
    "R-020": r020_fire,
    "P-001": p001_fire,
    "P-002": p002_fire,
    "P-003": p003_fire,
    "P-004": p004_fire,
    "P-005": p005_fire,
}

MUST_NOT: dict[str, ScenarioFn] = {
    "R-001": r001_quiet,
    "R-002": r002_quiet,
    "R-003": r003_quiet,
    "R-004": r004_quiet,
    "R-005": r005_quiet,
    "R-006": r006_quiet,
    "R-007": r007_quiet,
    "R-008": r008_quiet,
    "R-009": r009_quiet,
    "R-010": r010_quiet,
    "R-011": r011_quiet,
    "R-012": lambda: r001_quiet(),
    "R-013": r013_quiet,
    "R-014": r014_quiet,
    "R-015": r015_quiet,
    "R-016": r016_quiet,
    "R-017": r017_quiet,
    "R-018": r018_quiet,
    "R-019": r019_quiet,
    "R-020": r020_quiet,
    "P-001": p001_quiet,
    "P-002": p002_quiet,
    "P-003": p003_quiet,
    "P-004": p004_quiet,
    "P-005": lambda: _gst("p005_quiet", [], duration_ms=1_560_000, total_gold={1: 5000, 6: 5200}),
}

LABELLED: list[tuple[str, ScenarioFn, list[str]]] = [
    ("S01_unseen_jungler", r001_fire, ["R-001"]),
    ("S02_known_jungler", r001_quiet, ["R-003"]),
    ("S03_gold_death", r002_fire, ["R-002"]),
    ("S04_poor_gold_death", r002_quiet, []),
    ("S05_cs_collapse", r005_fire, ["R-005"]),
    ("S06_cs_stable", r005_quiet, []),
    ("S07_low_hp_gold", r007_fire, ["R-006", "R-007"]),
    ("S08_healthy_gold", r007_quiet, ["R-006"]),
    ("S09_obj_noshow", r008_fire, ["R-008"]),
    ("S10_obj_trade", r008_quiet, []),
    ("S11_no_antiheal", r011_fire, ["R-011"]),
    ("S12_bought_antiheal", r011_quiet, []),
    ("S13_fight_unknown", r012_fire, ["R-012"]),
    ("S14_clean_lane", p001_fire, ["P-001"]),
    ("S15_recovered", p005_fire, ["P-005"]),
]
