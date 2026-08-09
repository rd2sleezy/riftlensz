from __future__ import annotations

import pytest
from riftlens.analysis.rules.engine import RuleEngine
from riftlens.analysis.rules.explain import render_rule_template, template_dir
from riftlens.analysis.rules.loader import load_rule_pack
from riftlens.analysis.rules.models import RulePack
from tests.helpers.gst import bundled_patch
from tests.helpers.h7_scenarios import MUST_FIRE, MUST_NOT

_PRODUCTION = tuple(f"R-{i:03d}" for i in range(1, 21)) + tuple(f"P-{i:03d}" for i in range(1, 6))


@pytest.fixture(scope="module")
def pack() -> RulePack:
    return load_rule_pack()


def _run_one(pack: RulePack, rule_id: str, gst, pid: int = 1):
    rule = next(item for item in pack.rules if item.id == rule_id)
    engine = RuleEngine(RulePack([rule], pack.concept_ids), patch=bundled_patch(gst.patch))
    return engine.run(gst, pid)


@pytest.mark.parametrize("rule_id", _PRODUCTION)
def test_production_rule_has_two_false_positives_and_template(pack: RulePack, rule_id: str) -> None:
    rule = next(item for item in pack.rules if item.id == rule_id)
    assert len(rule.false_positives) >= 2
    assert rule.evidence_template
    assert (template_dir() / f"{rule_id}.j2").is_file()
    prose = render_rule_template(
        rule_id,
        {
            "t_mmss": "4:30",
            "death_zone": "TOP_RIVER",
            "jungler_champion": "Warwick",
            "jungler_damage_pct": 40,
            "info_age_s": 50,
            "jungler_last_seen_mmss": "3:40",
            "certainty": "likely",
            "gold": 1600,
            "last_shop_mmss": "2:00",
            "lookback_s": 90,
            "dealer_count": 1,
            "allies_near": 0,
            "n": 2,
            "ratio_max_pct": 55,
            "threshold": 1300,
            "hold_s": 120,
            "hp_pct": 30,
            "last_purchase_mmss": "1:00",
            "monster": "DRAGON",
            "distance": 7000,
            "cs_delta": 8,
            "role": "UTILITY",
            "resets": 4,
            "bought": 0,
            "ratio": 0.1,
            "enemy_names": "Warwick",
            "healing_known": False,
            "suggested_item": "Oblivion Orb",
            "unknown": 2,
            "our_deaths": 2,
            "fight_mmss": "18:00",
            "firsts": 3,
            "joined": 5,
            "pct": 60,
            "kills": 3,
            "window_s": 25,
            "turret_damage": True,
            "level": 6,
            "lead_s": 30,
            "opponent": "Syndra",
            "cs_lost": 14,
            "zone": "BOT_RIVER",
            "cluster_n": 3,
            "death_clocks": "10:00",
            "dmg_pct": 20,
            "gold_pct": 40,
            "span_s": 2.1,
            "diff": 12,
            "deaths": 0,
            "example_mmss": "8:10",
            "worst": -1800,
            "worst_mmss": "12:00",
            "pid": 1,
            "champion": "Ahri",
            "t_ms": 1,
        },
    )
    assert prose.strip()


@pytest.mark.parametrize("rule_id", _PRODUCTION)
def test_rule_must_fire(pack: RulePack, rule_id: str) -> None:
    gst = MUST_FIRE[rule_id]()
    findings = _run_one(pack, rule_id, gst)
    assert findings, f"{rule_id} must fire on synthetic {gst.match_id}"
    for finding in findings:
        assert finding.evidence
        assert finding.t_ms >= 0
        assert 0.0 < finding.confidence <= 1.0
        assert finding.explanation


@pytest.mark.parametrize("rule_id", _PRODUCTION)
def test_rule_must_not_fire(pack: RulePack, rule_id: str) -> None:
    gst = MUST_NOT[rule_id]()
    findings = _run_one(pack, rule_id, gst)
    assert not findings, f"{rule_id} must not fire on {gst.match_id}: {[f.t_ms for f in findings]}"
