from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from riftlens.coaching.data import RankRelevanceTable, ScoringConfig, TaxonomyIndex
from riftlens.domain.finding import Finding
from riftlens.domain.review import FindingCluster


def score_clusters(
    clusters: Sequence[FindingCluster],
    *,
    rank: str,
    scoring: ScoringConfig,
    ranks: RankRelevanceTable,
    taxonomy: TaxonomyIndex,
) -> list[FindingCluster]:
    """Return clusters with Impact filled from data-file terms (§6.4)."""
    scored: list[FindingCluster] = []
    for cluster in clusters:
        gold = _gold_equivalent(cluster, scoring)
        frequency = max(1, cluster.occurrences) ** scoring.frequency_exponent
        teachability = taxonomy.teachability(cluster.root_concept_id)
        relevance = ranks.relevance(cluster.root_concept_id, rank)
        confidence = max(scoring.confidence_floor, min(1.0, cluster.confidence))
        impact = gold * frequency * teachability * relevance * confidence
        scored.append(
            replace(
                cluster,
                gold_equivalent=min(gold, scoring.max_gold_equivalent),
                impact_score=impact,
                confidence=confidence,
            )
        )
    return scored


def _gold_equivalent(cluster: FindingCluster, scoring: ScoringConfig) -> float:
    total = 0.0
    for item in cluster.member_findings:
        total += _finding_gold(item, scoring)
    if total <= 0:
        total = scoring.gold_floor_for_zero
    return min(total, scoring.max_gold_equivalent)


def _finding_gold(item: Finding, scoring: ScoringConfig) -> float:
    if item.gold_equivalent is not None:
        return max(0.0, float(item.gold_equivalent))
    outcome = (item.outcome or "NONE").upper()
    base = float(scoring.outcome_gold.get(outcome, scoring.outcome_gold.get("NONE", 40.0)))
    extra = _unspent_from_evidence(item) * scoring.unspent_gold_weight
    return max(0.0, base + extra)


def _unspent_from_evidence(item: Finding) -> float:
    for evidence in item.evidence:
        payload = evidence.value
        if not isinstance(payload, Mapping):
            continue
        for key in ("unspent", "unspent_gold", "currentGold", "gold"):
            raw = payload.get(key)
            parsed = _as_float(raw)
            if parsed is not None and parsed >= 0:
                return parsed
    return 0.0


def _as_float(raw: Any) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int | float):
        return float(raw)
    return None


def cost_summary(cluster: FindingCluster) -> str:
    """Return a short gold/death cost string from clustered findings only."""
    deaths = sum(1 for item in cluster.member_findings if (item.outcome or "").upper() == "DEATH")
    gold = int(round(cluster.gold_equivalent))
    if deaths:
        return f"~{gold:,} gold and {deaths} death{'s' if deaths != 1 else ''}"
    return f"~{gold:,} gold"
