from __future__ import annotations

from riftlens.coaching.clusterer import _make_cluster
from riftlens.coaching.data import load_rank_relevance, load_scoring, load_taxonomy_index
from riftlens.coaching.prioritizer import prioritize
from riftlens.coaching.scoring import score_clusters
from riftlens.domain.enums import IssueType, Severity
from tests.helpers.h8_findings import finding

_LANING = [
    "LANING.FARM.CS_COLLAPSE_AFTER_DEATH",
    "LANING.RECALL_TIMING.RECALL_WITH_EXCESS_GOLD",
    "LANING.LEVEL_SPIKES.DEFICIT_AT_SPIKE",
    "LANING.WAVE_MANAGEMENT.PUSHING_WITHOUT_A_PLAN",
    "LANING.JUNGLE_TRACKING.POSITIONING_BY_ENEMY_JUNGLER_INFORMATION_AGE",
]
_VISION = "VISION.DENIAL.NO_CONTROL_WARDS"
_MACRO = "MACRO.TEMPO.NO_CONVERSION"
_COMBAT = "COMBAT.SUMMONER_SPELLS.UNUSED_ESCAPE"
_ECON = "ECONOMY.SPENDING.UNSPENT_AT_DEATH"


def _cluster(concept_id: str, gold: float, t_ms: int = 100_000, strength: bool = False):
    scoring = load_scoring()
    taxonomy = load_taxonomy_index()
    ranks = load_rank_relevance(unranked_treats_as=scoring.unranked_treats_as)
    rule = "P-001" if strength else "R-005"
    item = finding(
        rule_id=rule,
        concept_id=concept_id,
        t_ms=t_ms,
        gold_equivalent=gold,
        severity=Severity.HIGH,
        outcome="NONE" if strength else "CS_LOST",
    )
    return _make_cluster(
        root_concept_id=concept_id,
        members=(item,),
        symptoms=(item,),
        causes=(),
        taxonomy=taxonomy,
        ranks=ranks,
        scoring=scoring,
        reason="test cluster",
        contributing=(),
        is_strength=strength,
    )


def test_diversity_does_not_return_three_laning_focus_items() -> None:
    scoring = load_scoring()
    taxonomy = load_taxonomy_index()
    ranks = load_rank_relevance(unranked_treats_as=scoring.unranked_treats_as)
    clusters = [
        _cluster(concept, 2000.0, t_ms=100_000 + index * 10_000)
        for index, concept in enumerate(_LANING)
    ]
    clusters.append(_cluster(_VISION, 400.0, t_ms=900_000))
    scored = score_clusters(clusters, rank="IRON", scoring=scoring, ranks=ranks, taxonomy=taxonomy)
    picked = prioritize(scored, rank="IRON", scoring=scoring, ranks=ranks)
    assert len(picked.focus) == 3
    laning = sum(1 for item in picked.focus if item.domain == "LANING")
    assert laning < 3
    assert any(item.domain == "VISION" for item in picked.focus)


def test_rank_sensitivity_iron_vs_diamond_changes_focus() -> None:
    scoring = load_scoring()
    taxonomy = load_taxonomy_index()
    ranks = load_rank_relevance(unranked_treats_as=scoring.unranked_treats_as)
    clusters = [
        _cluster("LANING.FARM.CS_COLLAPSE_AFTER_DEATH", 800.0, t_ms=120_000),
        _cluster(_MACRO, 800.0, t_ms=240_000),
        _cluster(_VISION, 800.0, t_ms=360_000),
        _cluster(_COMBAT, 800.0, t_ms=480_000),
        _cluster(_ECON, 800.0, t_ms=600_000),
    ]
    iron = prioritize(
        score_clusters(clusters, rank="IRON", scoring=scoring, ranks=ranks, taxonomy=taxonomy),
        rank="IRON",
        scoring=scoring,
        ranks=ranks,
    )
    diamond = prioritize(
        score_clusters(clusters, rank="DIAMOND", scoring=scoring, ranks=ranks, taxonomy=taxonomy),
        rank="DIAMOND",
        scoring=scoring,
        ranks=ranks,
    )
    iron_ids = [item.root_concept_id for item in iron.focus]
    diamond_ids = [item.root_concept_id for item in diamond.focus]
    assert iron_ids != diamond_ids
    assert _MACRO in diamond_ids
    assert _MACRO not in iron_ids


def test_below_gold_requires_two_mechanical_or_tactical() -> None:
    scoring = load_scoring()
    taxonomy = load_taxonomy_index()
    ranks = load_rank_relevance(unranked_treats_as=scoring.unranked_treats_as)
    clusters = [
        _cluster(_MACRO, 5000.0, t_ms=100_000),
        _cluster("MACRO.OBJECTIVES.NO_SHOW", 4900.0, t_ms=200_000),
        _cluster("MACRO.ROAMING.ROAM_COST_EXCEEDED", 4800.0, t_ms=300_000),
        _cluster(_VISION, 200.0, t_ms=400_000),
        _cluster(_COMBAT, 200.0, t_ms=500_000),
    ]
    picked = prioritize(
        score_clusters(clusters, rank="IRON", scoring=scoring, ranks=ranks, taxonomy=taxonomy),
        rank="IRON",
        scoring=scoring,
        ranks=ranks,
    )
    local = sum(
        1
        for item in picked.focus
        if item.issue_type in {IssueType.MECHANICAL, IssueType.TACTICAL}
    )
    assert local >= 2


def test_selects_two_to_three_strengths_when_present() -> None:
    scoring = load_scoring()
    taxonomy = load_taxonomy_index()
    ranks = load_rank_relevance(unranked_treats_as=scoring.unranked_treats_as)
    clusters = [
        _cluster(_VISION, 500.0, t_ms=100_000),
        _cluster(_ECON, 500.0, t_ms=200_000),
        _cluster(_COMBAT, 500.0, t_ms=300_000),
        _cluster("STRENGTH.CLEAN_LANE_PHASE", 50.0, t_ms=840_000, strength=True),
        _cluster("STRENGTH.VISION_HABIT", 50.0, t_ms=900_000, strength=True),
        _cluster("STRENGTH.EFFICIENT_RESETS", 50.0, t_ms=200_000, strength=True),
    ]
    picked = prioritize(
        score_clusters(clusters, rank="GOLD", scoring=scoring, ranks=ranks, taxonomy=taxonomy),
        rank="GOLD",
        scoring=scoring,
        ranks=ranks,
    )
    assert 2 <= len(picked.strengths) <= 3
    assert len(picked.focus) == 3
    assert len(picked.secondary) <= 5
