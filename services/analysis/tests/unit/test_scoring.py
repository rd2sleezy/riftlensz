from __future__ import annotations

from riftlens.coaching.clusterer import cluster_findings
from riftlens.coaching.data import load_rank_relevance, load_scoring, load_taxonomy_index
from riftlens.coaching.scoring import score_clusters
from tests.helpers.h8_findings import finding


def test_impact_uses_data_file_terms_not_python_constants() -> None:
    scoring = load_scoring()
    taxonomy = load_taxonomy_index()
    ranks = load_rank_relevance(unranked_treats_as=scoring.unranked_treats_as)
    from riftlens.coaching.data import load_causal_graph

    graph = load_causal_graph()
    items = [
        finding(
            rule_id="R-002",
            concept_id="ECONOMY.SPENDING.UNSPENT_AT_DEATH",
            t_ms=400_000,
            gold_equivalent=1000.0,
            confidence=0.8,
        ),
        finding(
            rule_id="R-002",
            concept_id="ECONOMY.SPENDING.UNSPENT_AT_DEATH",
            t_ms=800_000,
            gold_equivalent=1000.0,
            confidence=0.8,
        ),
    ]
    clustered = cluster_findings(
        items, graph=graph, taxonomy=taxonomy, ranks=ranks, scoring=scoring
    )
    scored = score_clusters(
        clustered.clusters, rank="IRON", scoring=scoring, ranks=ranks, taxonomy=taxonomy
    )
    cluster = scored[0]
    gold = 2000.0
    freq = 2 ** scoring.frequency_exponent
    teach = taxonomy.teachability("ECONOMY.SPENDING.UNSPENT_AT_DEATH")
    rel = ranks.relevance("ECONOMY.SPENDING.UNSPENT_AT_DEATH", "IRON")
    expected = gold * freq * teach * rel * 0.8
    assert cluster.gold_equivalent == gold
    assert abs(cluster.impact_score - expected) < 1e-6


def test_missing_gold_equivalent_uses_outcome_table() -> None:
    scoring = load_scoring()
    item = finding(
        rule_id="R-018",
        concept_id="RISK.DEATH_CAUSE.LOCATION_CLUSTER",
        t_ms=100_000,
        gold_equivalent=None,
        outcome="DEATH",
    )
    from riftlens.coaching.scoring import _finding_gold

    assert _finding_gold(item, scoring) == scoring.outcome_gold["DEATH"]
