from __future__ import annotations

from riftlens.analysis.features.fights import segment_fights
from riftlens.analysis.rules.engine import RuleEngine
from riftlens.analysis.rules.loader import load_rule_pack
from riftlens.analysis.rules.models import RulePack
from riftlens.analysis.rules.predicates._common import (
    SUBJECT_FIGHT_DECISION_MS,
    failed_enemy_tower_dive_trade,
    subject_involved_near_fight_start,
    zone_matches_lane,
)
from riftlens.domain.enums import FactKind, Lane
from riftlens.domain.geometry import zone_of
from tests.helpers.gst import bundled_patch
from tests.helpers.h7_scenarios import (
    MUST_FIRE,
    MUST_NOT,
    r004_failed_dive_trade,
    r004_fire,
    r012_fire,
    r012_late_cluster_join,
    r017_fire,
    r017_return_from_base,
)
from tests.helpers.synthetic import BLUE_BASE


def _run(rule_id: str, gst, pid: int = 1):
    pack = load_rule_pack()
    rule = next(item for item in pack.rules if item.id == rule_id)
    engine = RuleEngine(RulePack([rule], pack.concept_ids), patch=bundled_patch(gst.patch))
    return engine.run(gst, pid)


def _death(gst, pid: int, t_ms: int):
    for fact in gst.facts(kind=FactKind.CHAMPION_KILL):
        if fact.payload.get("victimId") == pid and fact.t_ms == t_ms:
            return fact
    raise AssertionError(f"missing death pid={pid} t_ms={t_ms}")


def test_r012_existing_must_fire_and_must_not_remain_green() -> None:
    assert _run("R-012", MUST_FIRE["R-012"]())
    assert not _run("R-012", MUST_NOT["R-012"]())


def test_r012_subject_at_fight_start_must_fire() -> None:
    gst = r012_fire()
    fight = next(f for f in segment_fights(gst) if subject_involved_near_fight_start(f, 1))
    assert fight.t_start == 1_080_000
    assert subject_involved_near_fight_start(fight, 1)
    findings = _run("R-012", gst)
    assert findings
    assert all(item.t_ms == fight.t_start for item in findings)


def test_r012_late_cluster_join_must_not_fire() -> None:
    gst = r012_late_cluster_join()
    fights = [
        fight
        for fight in segment_fights(gst)
        if any(1 in members for members in fight.participants_by_team.values())
    ]
    assert fights, "expected chained cluster involving the subject"
    fight = max(fights, key=lambda item: len(item.deaths_in_order))
    assert fight.t_end - fight.t_start >= SUBJECT_FIGHT_DECISION_MS
    assert any(1 in members for members in fight.participants_by_team.values())
    assert not subject_involved_near_fight_start(fight, 1)
    assert not _run("R-012", gst)


def test_r017_existing_must_fire_and_must_not_remain_green() -> None:
    assert _run("R-017", MUST_FIRE["R-017"]())
    assert not _run("R-017", MUST_NOT["R-017"]())


def test_r017_true_lane_to_river_still_fires() -> None:
    gst = r017_fire()
    findings = _run("R-017", gst)
    assert findings


def test_r017_return_from_base_must_not_fire() -> None:
    gst = r017_return_from_base()
    assert zone_of(BLUE_BASE)  # sanity
    assert not zone_matches_lane(zone_of(BLUE_BASE), Lane.MIDDLE)
    assert not _run("R-017", gst)


def test_r004_existing_must_fire_and_must_not_remain_green() -> None:
    assert _run("R-004", MUST_FIRE["R-004"]())
    assert not _run("R-004", MUST_NOT["R-004"]())


def test_r004_classic_isolated_catch_still_fires() -> None:
    gst = r004_fire()
    findings = _run("R-004", gst)
    assert findings
    death = _death(gst, 1, 960_000)
    assert not failed_enemy_tower_dive_trade(gst, 1, death, 960_000)


def test_r004_failed_dive_trade_must_not_fire() -> None:
    gst = r004_failed_dive_trade()
    death = _death(gst, 1, 960_000)
    assert failed_enemy_tower_dive_trade(gst, 1, death, 960_000)
    assert not _run("R-004", gst)
