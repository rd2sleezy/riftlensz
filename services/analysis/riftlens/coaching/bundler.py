from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from riftlens.domain.finding import Finding
from riftlens.domain.review import CoachingItem, Review, format_mmss


class ReviewContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    champion: str
    role: str
    rank: str
    patch: str
    result: str | None
    duration_ms: int


class ItemContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept: str
    title: str
    occurrences: int
    impact: float
    issue_type: str


class EvidenceSnippet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: Any
    t_ms: int | None = None
    confidence: float | None = None
    source: str
    inferred: bool = False


class FindingSnippet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t_mmss: str
    t_ms: int
    severity: str
    confidence: float
    rule_id: str
    concept_id: str
    suppressed: bool = False
    evidence: list[EvidenceSnippet] = Field(default_factory=list)


class AllowedValues(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numbers: list[float] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)
    timestamps: list[str] = Field(default_factory=list)


class EvidenceBundle(BaseModel):
    """Strict LLM-facing payload. Narration may only cite these values (H.11)."""

    model_config = ConfigDict(extra="forbid")

    review_context: ReviewContext
    item: ItemContext
    findings: list[FindingSnippet]
    allowed_values: AllowedValues
    template_explanation: str


def bundle_item(
    review: Review,
    item: CoachingItem,
    findings: Sequence[Finding],
) -> EvidenceBundle:
    """Build an EvidenceBundle from structured findings only. No new gameplay facts."""
    snippets = [_finding_snippet(finding) for finding in findings]
    allowed = _allowed_values(review, item, snippets)
    return EvidenceBundle(
        review_context=ReviewContext(
            champion=review.champion,
            role=review.role.value,
            rank=review.rank,
            patch=review.patch,
            result=review.result,
            duration_ms=review.duration_ms,
        ),
        item=ItemContext(
            concept=item.root_concept_id,
            title=item.title,
            occurrences=item.occurrences,
            impact=item.impact_score,
            issue_type=item.issue_type.value,
        ),
        findings=snippets,
        allowed_values=allowed,
        template_explanation=item.body,
    )


def bundle_review(review: Review) -> list[EvidenceBundle]:
    """Return one bundle per coaching item. Assumes ``review.findings`` are originals."""
    by_id = {item.id: item for item in review.findings}
    bundles: list[EvidenceBundle] = []
    for item in (*review.focus_items, *review.secondary_items, *review.strengths):
        linked = [by_id[fid] for fid in item.finding_ids if fid in by_id]
        bundles.append(bundle_item(review, item, linked))
    return bundles


def _finding_snippet(finding: Finding) -> FindingSnippet:
    evidence = [
        EvidenceSnippet(
            label=item.label,
            value=item.value,
            t_ms=item.t_ms,
            confidence=item.confidence,
            source=item.source.value,
            inferred=item.source.value == "DERIVED"
            or (item.confidence is not None and item.confidence < 0.85),
        )
        for item in finding.evidence
    ]
    return FindingSnippet(
        t_mmss=format_mmss(finding.t_ms),
        t_ms=finding.t_ms,
        severity=finding.severity.value,
        confidence=finding.confidence,
        rule_id=finding.rule_id,
        concept_id=finding.concept_id,
        suppressed=finding.suppressed,
        evidence=evidence,
    )


def _allowed_values(
    review: Review, item: CoachingItem, snippets: Sequence[FindingSnippet]
) -> AllowedValues:
    numbers: set[float] = {
        float(item.occurrences),
        float(item.impact_score),
        float(item.confidence),
    }
    if item.gold_equivalent is not None:
        numbers.add(float(item.gold_equivalent))
    names = {review.champion, review.role.value, item.root_concept_id, item.title}
    timestamps = {format_mmss(stamp) for stamp in item.evidence_timestamps_ms}
    _collect_tokens(snippets, numbers, names, timestamps)
    return AllowedValues(
        numbers=sorted(numbers),
        names=sorted(names),
        timestamps=sorted(timestamps),
    )


def _collect_tokens(
    snippets: Sequence[FindingSnippet],
    numbers: set[float],
    names: set[str],
    timestamps: set[str],
) -> None:
    for snippet in snippets:
        numbers.add(float(snippet.confidence))
        numbers.add(float(snippet.t_ms))
        timestamps.add(snippet.t_mmss)
        names.add(snippet.rule_id)
        names.add(snippet.concept_id)
        for evidence in snippet.evidence:
            _walk_value(evidence.value, numbers, names, timestamps)
            if evidence.t_ms is not None:
                numbers.add(float(evidence.t_ms))
                timestamps.add(format_mmss(evidence.t_ms))


def _walk_value(
    value: object, numbers: set[float], names: set[str], timestamps: set[str]
) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int | float):
        numbers.add(float(value))
        return
    if isinstance(value, str):
        if value:
            names.add(value)
        return
    if isinstance(value, Mapping):
        for inner in value.values():
            _walk_value(inner, numbers, names, timestamps)
        return
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        for inner in value:
            _walk_value(inner, numbers, names, timestamps)
