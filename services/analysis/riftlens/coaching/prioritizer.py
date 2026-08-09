from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from riftlens.coaching.data import RankRelevanceTable, ScoringConfig
from riftlens.domain.enums import IssueType
from riftlens.domain.review import FindingCluster


@dataclass(frozen=True)
class PrioritizedSet:
    focus: tuple[FindingCluster, ...]
    secondary: tuple[FindingCluster, ...]
    strengths: tuple[FindingCluster, ...]


def prioritize(
    clusters: Sequence[FindingCluster],
    *,
    rank: str,
    scoring: ScoringConfig,
    ranks: RankRelevanceTable,
) -> PrioritizedSet:
    """Select 3 focus, ≤5 secondary, and 2–3 strengths with diversity + rank gates."""
    mistakes = [item for item in clusters if not item.is_strength]
    strengths = [item for item in clusters if item.is_strength]
    focus = _select_focus(mistakes, rank=rank, scoring=scoring, ranks=ranks)
    focus_ids = {item.id for item in focus}
    leftover = sorted(
        (item for item in mistakes if item.id not in focus_ids),
        key=_mistake_key,
        reverse=True,
    )
    secondary = tuple(leftover[: scoring.secondary_cap])
    picked_strengths = _select_strengths(strengths, scoring)
    return PrioritizedSet(focus=tuple(focus), secondary=secondary, strengths=picked_strengths)


def _select_focus(
    clusters: Sequence[FindingCluster],
    *,
    rank: str,
    scoring: ScoringConfig,
    ranks: RankRelevanceTable,
) -> list[FindingCluster]:
    remaining = list(clusters)
    selected: list[FindingCluster] = []
    below_gold = ranks.is_below_gold(rank, scoring.below_gold_tiers)
    while len(selected) < scoring.focus_count and remaining:
        pick = _next_focus(remaining, selected, scoring)
        if pick is None:
            break
        remaining.remove(pick)
        selected.append(pick)
    if below_gold:
        selected = _enforce_rank_constraint(selected, remaining, scoring.focus_count)
    return selected[: scoring.focus_count]


def _next_focus(
    remaining: Sequence[FindingCluster],
    selected: Sequence[FindingCluster],
    scoring: ScoringConfig,
) -> FindingCluster | None:
    if not remaining:
        return None
    domains = [item.domain for item in selected]
    other_exists = any(item.domain not in set(domains) for item in remaining) if domains else False
    best: tuple[float, FindingCluster] | None = None
    for cluster in remaining:
        count = domains.count(cluster.domain)
        if count >= 2 and other_exists:
            continue
        dominates = _dominates(cluster.domain, remaining, selected, scoring)
        if count == 1 and other_exists and not dominates:
            continue
        score = cluster.impact_score
        if count >= 1:
            score *= scoring.diversity_penalty
        if best is None or score > best[0]:
            best = (score, cluster)
    if best is not None:
        return best[1]
    return max(remaining, key=_mistake_key)


def _dominates(
    domain: str,
    remaining: Sequence[FindingCluster],
    selected: Sequence[FindingCluster],
    scoring: ScoringConfig,
) -> bool:
    pool = [*remaining, *selected]
    best_here = max((item.impact_score for item in pool if item.domain == domain), default=0.0)
    best_other = max((item.impact_score for item in pool if item.domain != domain), default=0.0)
    if best_other <= 0:
        return True
    return best_here > scoring.domain_dominance_ratio * best_other


def _enforce_rank_constraint(
    selected: list[FindingCluster],
    remaining: Sequence[FindingCluster],
    focus_count: int,
) -> list[FindingCluster]:
    def is_local(item: FindingCluster) -> bool:
        return item.issue_type in {IssueType.MECHANICAL, IssueType.TACTICAL}

    local = [item for item in selected if is_local(item)]
    if len(local) >= 2 or len(selected) < focus_count:
        return selected
    replacement = next((item for item in remaining if is_local(item)), None)
    if replacement is None:
        return selected
    strategic = [item for item in selected if item.issue_type is IssueType.STRATEGIC]
    if not strategic:
        return selected
    victim = min(strategic, key=_mistake_key)
    return [replacement if item.id == victim.id else item for item in selected]


def _select_strengths(
    clusters: Sequence[FindingCluster], scoring: ScoringConfig
) -> tuple[FindingCluster, ...]:
    ordered = sorted(clusters, key=_strength_key, reverse=True)
    if not ordered:
        return ()
    count = min(max(scoring.strength_min, 1), scoring.strength_max, len(ordered))
    if len(ordered) >= scoring.strength_min:
        count = min(scoring.strength_max, len(ordered))
    picked = list(ordered[:count])
    if picked and not _has_timestamped(picked):
        stamped = next((item for item in ordered if _has_timestamped([item])), None)
        if stamped is not None and stamped.id not in {item.id for item in picked}:
            picked[-1] = stamped
    return tuple(picked)


def _has_timestamped(clusters: Sequence[FindingCluster]) -> bool:
    return any(item.exemplar.t_ms > 0 for item in clusters)


def _mistake_key(cluster: FindingCluster) -> tuple[float, float, int, str]:
    return (cluster.impact_score, cluster.gold_equivalent, cluster.occurrences, cluster.id)


def _strength_key(cluster: FindingCluster) -> tuple[float, float, int, str]:
    stamped = 1 if cluster.exemplar.t_ms > 0 else 0
    return (cluster.confidence, stamped, cluster.occurrences, cluster.id)
