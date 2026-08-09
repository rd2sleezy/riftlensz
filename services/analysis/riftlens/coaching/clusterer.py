from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace

from riftlens.coaching.causal_tests import CausalTestContext, get_causal_test, import_causal_tests
from riftlens.coaching.data import (
    CausalGraph,
    CauseSpec,
    RankRelevanceTable,
    ScoringConfig,
    TaxonomyIndex,
)
from riftlens.domain.estimate import combine
from riftlens.domain.finding import Finding
from riftlens.domain.ids import new_ulid
from riftlens.domain.review import FindingCluster, GroupingDecision, severity_rank, unique_findings


@dataclass(frozen=True)
class ClusterResult:
    clusters: tuple[FindingCluster, ...]
    grouping_log: tuple[GroupingDecision, ...]


def cluster_findings(
    findings: Sequence[Finding],
    *,
    graph: CausalGraph,
    taxonomy: TaxonomyIndex,
    ranks: RankRelevanceTable,
    scoring: ScoringConfig,
) -> ClusterResult:
    """Group findings into root-cause clusters without deleting originals (§6.3)."""
    import_causal_tests()
    below, strengths, suppressed, active = _partition(findings, scoring)
    promoted, used = _promote_symptoms(active, findings, graph, taxonomy, ranks, scoring)
    standalones = _standalone_clusters(
        active, used, taxonomy, ranks, scoring, is_strength=False
    )
    strength_clusters = _standalone_clusters(
        strengths, set(), taxonomy, ranks, scoring, is_strength=True
    )
    merged = _merge_by_root((*promoted, *standalones, *strength_clusters), scoring)
    attached = _attach_suppressed(merged, suppressed, scoring)
    log = _build_log(findings, below, attached)
    return ClusterResult(clusters=tuple(attached), grouping_log=tuple(log))


def _partition(
    findings: Sequence[Finding],
    scoring: ScoringConfig,
) -> tuple[list[Finding], list[Finding], list[Finding], list[Finding]]:
    below: list[Finding] = []
    strengths: list[Finding] = []
    suppressed: list[Finding] = []
    active: list[Finding] = []
    for item in findings:
        if item.confidence < scoring.confidence_floor:
            below.append(item)
            continue
        if _is_strength(item):
            strengths.append(item)
            continue
        if item.suppressed:
            suppressed.append(item)
            continue
        active.append(item)
    return below, strengths, suppressed, active


def _promote_symptoms(
    active: Sequence[Finding],
    all_findings: Sequence[Finding],
    graph: CausalGraph,
    taxonomy: TaxonomyIndex,
    ranks: RankRelevanceTable,
    scoring: ScoringConfig,
) -> tuple[list[FindingCluster], set[str]]:
    grouped = _group_by_concept(active)
    clusters: list[FindingCluster] = []
    used: set[str] = set()
    for concept_id, members in grouped.items():
        if len(members) < 2:
            continue
        cause = _best_passing_cause(concept_id, members, all_findings, graph)
        if cause is None:
            continue
        extras = [item for item in active if item.concept_id == cause.concept_id]
        cluster = _make_cluster(
            root_concept_id=cause.concept_id,
            members=unique_findings((*members, *extras)),
            symptoms=tuple(members),
            causes=tuple(extras),
            taxonomy=taxonomy,
            ranks=ranks,
            scoring=scoring,
            reason=(
                f"promoted {concept_id} via {cause.test} "
                f"(strength={cause.strength}: {cause.description})"
            ),
            contributing=tuple(
                spec.concept_id
                for spec in graph.causes_for(concept_id)
                if spec.concept_id != cause.concept_id
            ),
        )
        clusters.append(cluster)
        used.update(item.id for item in cluster.member_findings)
    return clusters, used


def _best_passing_cause(
    concept_id: str,
    members: Sequence[Finding],
    all_findings: Sequence[Finding],
    graph: CausalGraph,
) -> CauseSpec | None:
    passing: list[CauseSpec] = []
    for spec in graph.causes_for(concept_id):
        test = get_causal_test(spec.test)
        ctx = CausalTestContext(
            symptom_concept_id=concept_id,
            symptom_findings=tuple(members),
            all_findings=tuple(all_findings),
            params=spec.params,
        )
        if test(ctx):
            passing.append(spec)
    if not passing:
        return None
    return max(passing, key=lambda item: (item.strength, item.concept_id))


def _standalone_clusters(
    findings: Sequence[Finding],
    used: set[str],
    taxonomy: TaxonomyIndex,
    ranks: RankRelevanceTable,
    scoring: ScoringConfig,
    *,
    is_strength: bool,
) -> list[FindingCluster]:
    remaining = [item for item in findings if item.id not in used]
    clusters: list[FindingCluster] = []
    for concept_id, members in _group_by_concept(remaining).items():
        cluster = _make_cluster(
            root_concept_id=concept_id,
            members=tuple(members),
            symptoms=tuple(members),
            causes=(),
            taxonomy=taxonomy,
            ranks=ranks,
            scoring=scoring,
            reason=(
                "strength concept group"
                if is_strength
                else f"standalone symptom {concept_id} (no passing cause test)"
            ),
            contributing=(),
            is_strength=is_strength,
        )
        clusters.append(cluster)
    return clusters


def _merge_by_root(
    clusters: Sequence[FindingCluster], scoring: ScoringConfig
) -> list[FindingCluster]:
    by_root: dict[tuple[str, bool], list[FindingCluster]] = defaultdict(list)
    for cluster in clusters:
        by_root[(cluster.root_concept_id, cluster.is_strength)].append(cluster)
    merged: list[FindingCluster] = []
    for group in by_root.values():
        if len(group) == 1:
            merged.append(group[0])
            continue
        members = unique_findings([item for cluster in group for item in cluster.member_findings])
        symptoms = unique_findings([item for cluster in group for item in cluster.symptom_findings])
        causes = unique_findings([item for cluster in group for item in cluster.cause_findings])
        head = group[0]
        merged.append(
            replace(
                head,
                id=new_ulid(),
                member_findings=members,
                symptom_findings=symptoms,
                cause_findings=causes,
                exemplar=_pick_exemplar(members),
                occurrences=_occurrence_count(members, scoring),
                grouping_reason=head.grouping_reason + "; merged shared root-cause concept",
                contributing_causes=tuple(
                    dict.fromkeys(item for cluster in group for item in cluster.contributing_causes)
                ),
            )
        )
    return merged


def _attach_suppressed(
    clusters: Sequence[FindingCluster],
    suppressed: Sequence[Finding],
    scoring: ScoringConfig,
) -> list[FindingCluster]:
    attached: dict[str, list[Finding]] = defaultdict(list)
    for item in suppressed:
        target = _best_host(item, clusters, scoring.incident_window_ms)
        if target is None:
            continue
        attached[target.id].append(item)
    out: list[FindingCluster] = []
    for cluster in clusters:
        extras = tuple(attached.get(cluster.id, ()))
        if not extras:
            out.append(cluster)
            continue
        related = unique_findings((*cluster.suppressed_related, *extras))
        out.append(replace(cluster, suppressed_related=related))
    return out


def _best_host(
    item: Finding, clusters: Sequence[FindingCluster], window_ms: int
) -> FindingCluster | None:
    scored: list[tuple[int, int, str, FindingCluster]] = []
    for cluster in clusters:
        if cluster.is_strength:
            continue
        for member in cluster.member_findings:
            delta = abs(member.t_ms - item.t_ms)
            if item.suppressed_by == member.rule_id and delta <= window_ms:
                scored.append((0, delta, cluster.id, cluster))
            elif delta <= window_ms:
                scored.append((1, delta, cluster.id, cluster))
    if not scored:
        return None
    scored.sort(key=lambda row: (row[0], row[1], row[2]))
    return scored[0][3]


def _make_cluster(
    *,
    root_concept_id: str,
    members: Sequence[Finding],
    symptoms: Sequence[Finding],
    causes: Sequence[Finding],
    taxonomy: TaxonomyIndex,
    ranks: RankRelevanceTable,
    scoring: ScoringConfig,
    reason: str,
    contributing: tuple[str, ...],
    is_strength: bool = False,
) -> FindingCluster:
    primary = unique_findings(members)
    exemplar = _pick_exemplar(primary)
    confidences = [item.confidence for item in primary]
    return FindingCluster(
        id=new_ulid(),
        root_concept_id=root_concept_id,
        domain=taxonomy.domain_of(root_concept_id),
        issue_type=ranks.issue_type(root_concept_id),
        member_findings=primary,
        symptom_findings=unique_findings(symptoms),
        cause_findings=unique_findings(causes),
        suppressed_related=(),
        exemplar=exemplar,
        occurrences=_occurrence_count(primary, scoring),
        confidence=_combine_confidence(confidences, scoring.confidence_mode),
        gold_equivalent=0.0,
        impact_score=0.0,
        grouping_reason=reason,
        contributing_causes=contributing,
        is_strength=is_strength,
    )


def _pick_exemplar(members: Sequence[Finding]) -> Finding:
    return max(
        members,
        key=lambda item: (
            severity_rank(item.severity),
            item.gold_equivalent or 0.0,
            item.confidence,
            -item.t_ms,
            item.id,
        ),
    )


def _occurrence_count(members: Sequence[Finding], scoring: ScoringConfig) -> int:
    ordered = sorted(members, key=lambda item: (item.rule_id, item.t_ms, item.id))
    count = 0
    last: dict[str, int] = {}
    for item in ordered:
        prev = last.get(item.rule_id)
        if prev is not None and item.t_ms - prev < scoring.dedup_window_ms:
            continue
        count += 1
        last[item.rule_id] = item.t_ms
    return max(1, count)


def _combine_confidence(values: Sequence[float], mode: str) -> float:
    if not values:
        return 0.0
    if mode == "product":
        return combine(values)
    return min(values)


def _group_by_concept(findings: Sequence[Finding]) -> dict[str, list[Finding]]:
    grouped: dict[str, list[Finding]] = defaultdict(list)
    for item in findings:
        grouped[item.concept_id].append(item)
    return dict(grouped)


def _is_strength(item: Finding) -> bool:
    return item.rule_id.startswith("P-") or item.concept_id.startswith("STRENGTH.")


def _decision(
    item: Finding, cluster_id: str | None, role: str, reason: str
) -> GroupingDecision:
    return GroupingDecision(
        finding_id=item.id,
        concept_id=item.concept_id,
        cluster_id=cluster_id,
        role=role,  # type: ignore[arg-type]
        reason=reason,
        extra={"rule_id": item.rule_id, "t_ms": item.t_ms, "suppressed_by": item.suppressed_by},
    )


def _build_log(
    originals: Sequence[Finding],
    below: Sequence[Finding],
    clusters: Sequence[FindingCluster],
) -> list[GroupingDecision]:
    log: list[GroupingDecision] = []
    seen: set[str] = set()
    for item in below:
        seen.add(item.id)
        log.append(_decision(item, None, "below_confidence", "confidence below scoring floor"))
    for cluster in clusters:
        for item in cluster.member_findings:
            if item.id in seen:
                continue
            seen.add(item.id)
            promoted = "promoted" in cluster.grouping_reason
            if cluster.is_strength:
                role = "strength"
            elif item.concept_id == cluster.root_concept_id and promoted:
                role = "root_cause" if item in cluster.cause_findings else "symptom"
            elif item.concept_id != cluster.root_concept_id:
                role = "symptom"
            else:
                role = "standalone"
            if item in cluster.cause_findings and promoted:
                role = "cause_member" if item.concept_id == cluster.root_concept_id else role
            log.append(_decision(item, cluster.id, role, cluster.grouping_reason))
        for item in cluster.suppressed_related:
            if item.id in seen:
                continue
            seen.add(item.id)
            note = f"H.6 suppressed_by={item.suppressed_by}; attached, not a separate point"
            log.append(_decision(item, cluster.id, "suppressed_related", note))
    for item in originals:
        if item.id in seen:
            continue
        if item.suppressed:
            reason = "H.6 suppressed with no host cluster"
            role = "suppressed_related"
        else:
            reason = "preserved unclustered"
            role = "standalone"
        log.append(_decision(item, None, role, reason))
    return log
