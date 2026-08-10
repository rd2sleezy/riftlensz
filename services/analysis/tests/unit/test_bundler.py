from __future__ import annotations

from riftlens.coaching.bundler import bundle_item
from riftlens.coaching.clusterer import cluster_findings
from riftlens.coaching.data import (
    load_causal_graph,
    load_checks,
    load_rank_relevance,
    load_scoring,
    load_taxonomy_index,
)
from riftlens.coaching.items import coaching_items_from_clusters
from riftlens.coaching.scoring import score_clusters
from riftlens.domain.enums import Role
from riftlens.domain.review import Review
from tests.helpers.h8_findings import finding


def test_bundle_only_contains_structured_finding_evidence() -> None:
    scoring = load_scoring()
    taxonomy = load_taxonomy_index()
    ranks = load_rank_relevance(unranked_treats_as=scoring.unranked_treats_as)
    checks = load_checks()
    graph = load_causal_graph()
    originals = [
        finding(
            rule_id="R-001",
            concept_id="RISK.DEATH_CAUSE.UNSEEN_JUNGLER",
            t_ms=480_000,
            info_age_ms=70_000,
        ),
        finding(
            rule_id="R-001",
            concept_id="RISK.DEATH_CAUSE.UNSEEN_JUNGLER",
            t_ms=900_000,
            info_age_ms=80_000,
        ),
    ]
    clustered = cluster_findings(
        originals, graph=graph, taxonomy=taxonomy, ranks=ranks, scoring=scoring
    )
    scored = score_clusters(
        clustered.clusters, rank="SILVER", scoring=scoring, ranks=ranks, taxonomy=taxonomy
    )
    items = coaching_items_from_clusters(
        scored, checks=checks, scoring=scoring, is_focus=True, is_strength=False
    )
    review = Review(
        id="01H8REVIEWNULLEXAMPLE000001",
        player_id="01H8PLAYERLOCALEXAMPLE00001",
        match_id="SYNTH",
        participant_id=1,
        champion="Ahri",
        role=Role.MIDDLE,
        rank="SILVER",
        patch="12.4",
        duration_ms=1_800_000,
        result="LOSS",
        rule_pack_version="1",
        engine_version="0.1.0",
        llm_provider="null",
        status="COMPLETE",
        summary_text="test",
        findings=tuple(originals),
        clusters=tuple(scored),
        grouping_log=clustered.grouping_log,
        focus_items=tuple(items),
        secondary_items=(),
        strengths=(),
        metrics=(),
        created_at=1,
        completed_at=1,
    )
    bundle = bundle_item(review, items[0], originals)
    assert bundle.template_explanation
    assert bundle.item.occurrences == 2
    labels = {ev.label for snip in bundle.findings for ev in snip.evidence}
    assert "jungler info age" in labels
    inferred = [ev for snip in bundle.findings for ev in snip.evidence if ev.inferred]
    assert inferred
    assert all(ev.source == "DERIVED" for ev in inferred)
    assert 480_000.0 in bundle.allowed_values.numbers
    assert "Ahri" in bundle.allowed_values.names
    assert "8:00" in bundle.allowed_values.timestamps
