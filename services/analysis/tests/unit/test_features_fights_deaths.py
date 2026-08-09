from __future__ import annotations

from riftlens.analysis.features.deaths import DeathCause, classify, death_cost
from riftlens.analysis.features.fights import segment_fights
from riftlens.analysis.features.jungle_info import info_age
from riftlens.domain.enums import FactKind, Role, Team
from tests.helpers.gst import bundled_patch, fact, load_gst, make_gst, make_participant


def test_segment_fights_fixture_b_snapshot(snapshot: object) -> None:
    """Fixture B is an id-renamed copy of fixture A/C; fight count is identical.

    24 clusters: many isolated solo kills plus multi-kill skirmishes and one
    9-kill ace around 24:25. A human review agrees this is not one giant fight.
    """
    gst = load_gst("NA1_fixture_b")
    fights = segment_fights(gst)
    payload = {
        "count": len(fights),
        "sizes": [len(fight.deaths_in_order) for fight in fights],
        "windows": [[fight.t_start, fight.t_end] for fight in fights],
        "winners": [None if fight.winner is None else fight.winner.value for fight in fights],
    }
    assert payload == snapshot
    assert payload["count"] == 24
    assert max(payload["sizes"]) == 9


def test_segment_fights_joins_nearby_kills() -> None:
    gst = _two_team_gst(
        [
            _kill(10_000, killer=6, victim=1, x=2000, y=2000),
            _kill(15_000, killer=7, victim=2, x=2500, y=2200),
            _kill(90_000, killer=1, victim=6, x=12000, y=12000),
        ]
    )
    fights = segment_fights(gst)
    assert len(fights) == 2
    assert len(fights[0].deaths_in_order) == 2
    assert len(fights[1].deaths_in_order) == 1


def test_info_age_ignores_omniscient_frames() -> None:
    gst = _two_team_gst(
        [
            fact(0, FactKind.OBSERVATION, 6, {"omniscient": True}),
            fact(30_000, FactKind.OBSERVATION, 6, {"omniscient": False, "via": "CHAMPION_KILL"}),
            fact(0, FactKind.CS, 6, {"minionsKilled": 0, "jungleMinionsKilled": 0}),
            fact(60_000, FactKind.CS, 6, {"minionsKilled": 0, "jungleMinionsKilled": 4}),
        ]
    )
    early = info_age(gst, Team.BLUE, 6, 10_000)
    later = info_age(gst, Team.BLUE, 6, 40_000)
    camp = info_age(gst, Team.BLUE, 6, 70_000)
    assert early.confidence < 0.5
    assert later.value == 10_000
    assert camp.value == 10_000


def test_classify_unseen_gank_and_unknown() -> None:
    patch = bundled_patch()
    gst = _two_team_gst(
        [
            fact(0, FactKind.POSITION, 1, {"x": 2000, "y": 11000}),
            fact(0, FactKind.POSITION, 6, {"x": 4000, "y": 12000}),
            fact(0, FactKind.LEVEL, 1, {"level": 5}),
            _kill(
                120_000,
                killer=6,
                victim=1,
                x=2100,
                y=11200,
                dealers=[(6, "LeeSin", 400)],
            ),
        ]
    )
    kill = gst.facts(kind=FactKind.CHAMPION_KILL)[0]
    estimate = classify(gst, kill, patch)
    assert estimate.value is DeathCause.UNSEEN_GANK
    empty = classify(
        gst,
        fact(200_000, FactKind.CHAMPION_KILL, 1, {"victimId": 99, "killerId": 6, "bounty": 300}),
        patch,
    )
    assert empty.value is DeathCause.UNKNOWN
    assert empty.confidence < 0.5


def test_death_cost_includes_bounty() -> None:
    patch = bundled_patch()
    gst = _two_team_gst(
        [
            fact(0, FactKind.LEVEL, 1, {"level": 6}),
            fact(0, FactKind.CS, 1, {"minionsKilled": 0, "jungleMinionsKilled": 0}),
            fact(300_000, FactKind.CS, 1, {"minionsKilled": 50, "jungleMinionsKilled": 0}),
            _kill(180_000, killer=6, victim=1, x=3000, y=3000),
        ]
    )
    kill = gst.facts(kind=FactKind.CHAMPION_KILL)[0]
    estimate = death_cost(gst, kill, patch)
    assert estimate.value >= 300
    assert estimate.confidence > 0.4


def _two_team_gst(facts: list[object]) -> object:
    from riftlens.domain.fact import Fact

    typed = [item for item in facts if isinstance(item, Fact)]
    participants = {
        1: make_participant(1, team=Team.BLUE, role=Role.TOP, champion="Garen"),
        2: make_participant(2, team=Team.BLUE, role=Role.MIDDLE, champion="Ahri"),
        6: make_participant(6, team=Team.RED, role=Role.JUNGLE, champion="LeeSin"),
        7: make_participant(7, team=Team.RED, role=Role.MIDDLE, champion="Zed"),
    }
    return make_gst(typed, participants, duration_ms=400_000, lane_opponents={1: 7, 2: 7, 7: 2})


def _kill(
    t_ms: int,
    *,
    killer: int,
    victim: int,
    x: int,
    y: int,
    dealers: list[tuple[int, str, int]] | None = None,
) -> object:
    received = [
        {
            "participantId": pid,
            "name": name,
            "type": "OTHER",
            "physicalDamage": dmg,
            "magicDamage": 0,
            "trueDamage": 0,
        }
        for pid, name, dmg in (dealers or [(killer, "X", 300)])
    ]
    return fact(
        t_ms,
        FactKind.CHAMPION_KILL,
        victim,
        {
            "killerId": killer,
            "victimId": victim,
            "bounty": 300,
            "position": {"x": x, "y": y},
            "assistingParticipantIds": [],
            "victimDamageReceived": received,
            "victimDamageDealt": [],
        },
    )
