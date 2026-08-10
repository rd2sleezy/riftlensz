from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from riftlens.coaching.data import CheckCopy, ScoringConfig, check_for
from riftlens.coaching.scoring import cost_summary
from riftlens.domain.finding import Finding
from riftlens.domain.ids import new_ulid
from riftlens.domain.review import CoachingItem, FindingCluster, certainty_bucket, format_mmss

_TEMPLATES = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parent / "templates")),
    undefined=StrictUndefined,
    autoescape=select_autoescape(default=False),
    trim_blocks=True,
    lstrip_blocks=True,
)


def coaching_items_from_clusters(
    clusters: Sequence[FindingCluster],
    *,
    checks: Mapping[str, CheckCopy],
    scoring: ScoringConfig,
    is_focus: bool,
    is_strength: bool,
    rank_start: int = 1,
) -> list[CoachingItem]:
    """Render CoachingItems from already-selected clusters. Assumes scores are filled."""
    items: list[CoachingItem] = []
    for offset, cluster in enumerate(clusters):
        items.append(
            _item_from_cluster(
                cluster,
                checks=checks,
                scoring=scoring,
                rank=rank_start + offset,
                is_focus=is_focus,
                is_strength=is_strength,
            )
        )
    return items


def _item_from_cluster(
    cluster: FindingCluster,
    *,
    checks: Mapping[str, CheckCopy],
    scoring: ScoringConfig,
    rank: int,
    is_focus: bool,
    is_strength: bool,
) -> CoachingItem:
    copy = check_for(checks, cluster.root_concept_id)
    title = _clip_title(copy.title, scoring)
    certainty = certainty_bucket(cluster.confidence)
    exemplar = cluster.exemplar
    explanation = (exemplar.explanation or "").strip()
    alternative = (exemplar.alternative or "").strip()
    template = "strength_item.j2" if is_strength else "focus_item.j2"
    body = _TEMPLATES.get_template(template).render(
        certainty=certainty,
        occurrences=cluster.occurrences,
        cost_summary=cost_summary(cluster),
        exemplar_mmss=format_mmss(exemplar.t_ms),
        exemplar_t_ms=exemplar.t_ms,
        explanation=explanation,
        alternative=alternative if not is_strength else "",
        uncertainty_note=_uncertainty_note(cluster),
    ).strip()
    finding_ids = tuple(item.id for item in cluster.all_findings())
    stamps = cluster.timestamps_ms()[: scoring.exemplar_clip_count]
    return CoachingItem(
        id=new_ulid(),
        root_concept_id=cluster.root_concept_id,
        rank=rank,
        is_focus=is_focus,
        is_strength=is_strength,
        issue_type=cluster.issue_type,
        impact_score=cluster.impact_score,
        gold_equivalent=cluster.gold_equivalent,
        occurrences=cluster.occurrences,
        confidence=cluster.confidence,
        title=title,
        body=body,
        the_fix=copy.the_fix if not is_strength else copy.the_fix,
        next_game_check=copy.next_game_check,
        exemplar_finding_id=exemplar.id,
        finding_ids=finding_ids,
        evidence_timestamps_ms=stamps,
        grouping_reason=cluster.grouping_reason,
        certainty=certainty,
        cluster_id=cluster.id,
        cost_summary=cost_summary(cluster),
    )


def _clip_title(title: str, scoring: ScoringConfig) -> str:
    words = [part for part in title.strip().split() if part]
    if len(words) > scoring.max_title_words:
        words = words[: scoring.max_title_words]
    if len(words) < scoring.min_title_words:
        return title.strip()
    return " ".join(words)


def _uncertainty_note(cluster: FindingCluster) -> str:
    inferred = [
        evidence
        for finding in cluster.all_findings()
        for evidence in finding.evidence
        if evidence.source.value == "DERIVED" or (
            evidence.confidence is not None and evidence.confidence < 0.85
        )
    ]
    if not inferred:
        return ""
    return (
        "Some cited signals are inferred (info age, unspent gold between frames, "
        "trinket models) and are not deterministic facts."
    )


def evidence_labels(finding: Finding) -> list[tuple[str, object]]:
    """Return (label, value) pairs for bundling. Assumes evidence is non-empty."""
    return [(item.label, item.value) for item in finding.evidence]
