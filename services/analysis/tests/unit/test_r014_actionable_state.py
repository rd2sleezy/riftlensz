from __future__ import annotations

from riftlens.analysis.features.fights import segment_fights
from riftlens.analysis.rules.engine import RuleEngine
from riftlens.analysis.rules.loader import load_rule_pack
from riftlens.analysis.rules.models import RulePack
from riftlens.analysis.rules.predicates._common import (
    died_in_fight,
    is_alive,
    subject_actionable_after_fight,
)
from tests.helpers.gst import bundled_patch
from tests.helpers.h7_scenarios import (
    MUST_FIRE,
    MUST_NOT,
    r014_dead_later_assist,
    r014_died_before_fight_ended,
    r014_fire,
    r014_low_hp_still_fires,
    r014_respawn_after_window,
)


def _run_r014(gst, pid: int = 1):
    pack = load_rule_pack()
    rule = next(item for item in pack.rules if item.id == "R-014")
    engine = RuleEngine(RulePack([rule], pack.concept_ids), patch=bundled_patch(gst.patch))
    return engine.run(gst, pid)


def _subject_fight(gst, pid: int = 1):
    fights = [
        fight
        for fight in segment_fights(gst)
        if any(pid in members for members in fight.participants_by_team.values())
    ]
    assert fights, "expected a clustered fight involving the subject"
    return max(fights, key=lambda fight: fight.t_end)


def test_r014_survived_and_failed_to_convert_must_fire() -> None:
    gst = r014_fire()
    findings = _run_r014(gst)
    assert findings
    assert all(item.rule_id == "R-014" for item in findings)


def test_r014_existing_must_fire_and_must_not_remain_green() -> None:
    assert _run_r014(MUST_FIRE["R-014"]())
    assert not _run_r014(MUST_NOT["R-014"]())


def test_r014_died_before_fight_ended_must_not_fire() -> None:
    gst = r014_died_before_fight_ended()
    fight = _subject_fight(gst)
    patch = bundled_patch(gst.patch)
    assert died_in_fight(fight, 1)
    assert not subject_actionable_after_fight(gst, 1, fight, patch)
    assert not _run_r014(gst)


def test_r014_dead_later_assist_must_not_fire() -> None:
    gst = r014_dead_later_assist()
    fight = _subject_fight(gst)
    patch = bundled_patch(gst.patch)
    assert not died_in_fight(fight, 1)
    assert not is_alive(gst, 1, fight.t_end, patch)
    assert not subject_actionable_after_fight(gst, 1, fight, patch)
    assert not _run_r014(gst)


def test_r014_respawn_after_useful_window_must_not_fire() -> None:
    gst = r014_respawn_after_window()
    fight = _subject_fight(gst)
    patch = bundled_patch(gst.patch)
    window_end = fight.t_end + 25_000
    assert not is_alive(gst, 1, fight.t_end, patch)
    assert is_alive(gst, 1, window_end + 8_000, patch)
    assert not subject_actionable_after_fight(gst, 1, fight, patch)
    assert not _run_r014(gst)


def test_r014_low_hp_survivor_still_fires() -> None:
    gst = r014_low_hp_still_fires()
    fight = _subject_fight(gst)
    patch = bundled_patch(gst.patch)
    assert not died_in_fight(fight, 1)
    assert subject_actionable_after_fight(gst, 1, fight, patch)
    assert _run_r014(gst)
