from __future__ import annotations

from riftlens.coaching.clusterer import cluster_findings
from riftlens.coaching.data import (
    load_causal_graph,
    load_rank_relevance,
    load_scoring,
    load_taxonomy_index,
)
from tests.helpers.h8_findings import finding

_R001 = "RISK.DEATH_CAUSE.UNSEEN_JUNGLER"
_R003 = "RISK.EXPOSURE.FORWARD_NO_VISION_ATTEMPT"
_INFO = "LANING.JUNGLE_TRACKING.POSITIONING_BY_ENEMY_JUNGLER_INFORMATION_AGE"


def _deps() -> tuple[object, object, object, object]:
    scoring = load_scoring()
    return (
        load_causal_graph(),
        load_taxonomy_index(),
        load_rank_relevance(unranked_treats_as=scoring.unranked_treats_as),
        scoring,
    )


def test_two_unseen_deaths_promote_info_age_root() -> None:
    graph, taxonomy, ranks, scoring = _deps()
    originals = [
        finding(rule_id="R-001", concept_id=_R001, t_ms=480_000, info_age_ms=60_000),
        finding(rule_id="R-001", concept_id=_R001, t_ms=720_000, info_age_ms=90_000),
    ]
    result = cluster_findings(
        originals, graph=graph, taxonomy=taxonomy, ranks=ranks, scoring=scoring
    )
    assert originals[0].evidence  # originals preserved
    assert len(result.clusters) == 1
    cluster = result.clusters[0]
    assert cluster.root_concept_id == _INFO
    assert {item.id for item in cluster.member_findings} == {item.id for item in originals}
    assert "promoted" in cluster.grouping_reason
    assert cluster.occurrences == 2
    logged = {row.finding_id: row for row in result.grouping_log}
    assert logged[originals[0].id].cluster_id == cluster.id
    assert logged[originals[1].id].reason == cluster.grouping_reason


def test_wave_push_not_promoted_without_wave_state_evidence() -> None:
    graph, taxonomy, ranks, scoring = _deps()
    originals = [
        finding(rule_id="R-001", concept_id=_R001, t_ms=480_000, info_age_ms=10_000),
        finding(rule_id="R-001", concept_id=_R001, t_ms=720_000, info_age_ms=12_000),
    ]
    result = cluster_findings(
        originals, graph=graph, taxonomy=taxonomy, ranks=ranks, scoring=scoring
    )
    assert len(result.clusters) == 1
    assert result.clusters[0].root_concept_id == _R001
    assert "standalone" in result.clusters[0].grouping_reason


def test_suppressed_r003_attaches_and_is_not_a_focus_cluster() -> None:
    graph, taxonomy, ranks, scoring = _deps()
    r001 = finding(rule_id="R-001", concept_id=_R001, t_ms=500_000, info_age_ms=80_000)
    r003 = finding(
        rule_id="R-003",
        concept_id=_R003,
        t_ms=500_000,
        ward_count=0,
        suppressed=True,
        suppressed_by="R-001",
    )
    extra = finding(rule_id="R-001", concept_id=_R001, t_ms=800_000, info_age_ms=70_000)
    result = cluster_findings(
        [r001, r003, extra], graph=graph, taxonomy=taxonomy, ranks=ranks, scoring=scoring
    )
    assert len(result.clusters) == 1
    cluster = result.clusters[0]
    assert r003.id in {item.id for item in cluster.suppressed_related}
    assert r003.id in {item.id for item in cluster.all_findings()}
    assert r003.id not in {item.id for item in cluster.member_findings}
    roles = {row.finding_id: row.role for row in result.grouping_log}
    assert roles[r003.id] == "suppressed_related"


def test_single_finding_stays_standalone_cluster() -> None:
    graph, taxonomy, ranks, scoring = _deps()
    one = finding(
        rule_id="R-010",
        concept_id="VISION.DENIAL.NO_CONTROL_WARDS",
        t_ms=600_000,
        outcome="NONE",
    )
    result = cluster_findings([one], graph=graph, taxonomy=taxonomy, ranks=ranks, scoring=scoring)
    assert len(result.clusters) == 1
    assert result.clusters[0].root_concept_id == "VISION.DENIAL.NO_CONTROL_WARDS"
    assert result.clusters[0].occurrences == 1


def test_strengths_are_separate_clusters() -> None:
    graph, taxonomy, ranks, scoring = _deps()
    strength = finding(
        rule_id="P-001",
        concept_id="STRENGTH.CLEAN_LANE_PHASE",
        t_ms=840_000,
        outcome="NONE",
        gold_equivalent=50.0,
    )
    mistake = finding(rule_id="R-010", concept_id="VISION.DENIAL.NO_CONTROL_WARDS", t_ms=100_000)
    result = cluster_findings(
        [strength, mistake], graph=graph, taxonomy=taxonomy, ranks=ranks, scoring=scoring
    )
    assert {cluster.is_strength for cluster in result.clusters} == {True, False}
