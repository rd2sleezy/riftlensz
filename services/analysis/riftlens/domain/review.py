from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from riftlens.domain.enums import IssueType, Role, Severity
from riftlens.domain.finding import Finding

GroupingRole = Literal[
    "standalone",
    "symptom",
    "root_cause",
    "cause_member",
    "merged",
    "suppressed_related",
    "deduped",
    "strength",
    "below_confidence",
]


@dataclass(frozen=True)
class GroupingDecision:
    """One traceable assignment of a finding into a cluster (or an explicit skip)."""

    finding_id: str
    concept_id: str
    cluster_id: str | None
    role: GroupingRole
    reason: str
    extra: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class MetricSnapshot:
    """Match-level metric copy for a Review. Assumes analysis already computed values."""

    metric_id: str
    value: float
    unit: str
    phase: str | None
    confidence: float
    baseline_percentile: float | None = None
    sample_context: str = ""
    detail: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class FindingCluster:
    """Findings that share a root cause or a single honest symptom concept (§6.3)."""

    id: str
    root_concept_id: str
    domain: str
    issue_type: IssueType
    member_findings: tuple[Finding, ...]
    symptom_findings: tuple[Finding, ...]
    cause_findings: tuple[Finding, ...]
    suppressed_related: tuple[Finding, ...]
    exemplar: Finding
    occurrences: int
    confidence: float
    gold_equivalent: float
    impact_score: float
    grouping_reason: str
    contributing_causes: tuple[str, ...] = ()
    is_strength: bool = False

    def all_findings(self) -> tuple[Finding, ...]:
        """Return members plus suppressed-related findings without dropping evidence."""
        seen: set[str] = set()
        out: list[Finding] = []
        for item in (*self.member_findings, *self.suppressed_related):
            if item.id in seen:
                continue
            seen.add(item.id)
            out.append(item)
        return tuple(out)

    def timestamps_ms(self) -> tuple[int, ...]:
        """Return sorted unique game-clock timestamps for VOD linking later."""
        stamps = {item.t_ms for item in self.all_findings()}
        return tuple(sorted(stamps))


@dataclass(frozen=True)
class CoachingItem:
    """A scored cluster turned into one coaching point (§6.8 / §9.4)."""

    id: str
    root_concept_id: str
    rank: int
    is_focus: bool
    is_strength: bool
    issue_type: IssueType
    impact_score: float
    gold_equivalent: float | None
    occurrences: int
    confidence: float
    title: str
    body: str
    the_fix: str | None
    next_game_check: str | None
    exemplar_finding_id: str | None
    finding_ids: tuple[str, ...]
    evidence_timestamps_ms: tuple[int, ...]
    grouping_reason: str
    certainty: str
    cluster_id: str
    cost_summary: str
    explanation_source: str = "TEMPLATE"
    llm_fallback: bool = False


@dataclass(frozen=True)
class Review:
    """Full deterministic coaching deliverable. Findings are the H.6/H.7 originals."""

    id: str
    player_id: str
    match_id: str
    participant_id: int
    champion: str
    role: Role
    rank: str
    patch: str
    duration_ms: int
    result: str | None
    rule_pack_version: str
    engine_version: str
    llm_provider: str
    status: str
    summary_text: str | None
    findings: tuple[Finding, ...]
    clusters: tuple[FindingCluster, ...]
    grouping_log: tuple[GroupingDecision, ...]
    focus_items: tuple[CoachingItem, ...]
    secondary_items: tuple[CoachingItem, ...]
    strengths: tuple[CoachingItem, ...]
    metrics: tuple[MetricSnapshot, ...]
    created_at: int
    completed_at: int | None
    unpaired_match_timeline: bool = False
    overall_scores: Mapping[str, float] | None = None
    llm_model: str | None = None
    llm_prompt_version: str | None = None
    llm_fallback: bool = False

    def finding_by_id(self, finding_id: str) -> Finding | None:
        """Return a preserved original finding, including suppressed ones."""
        for item in self.findings:
            if item.id == finding_id:
                return item
        return None


def certainty_bucket(confidence: float) -> str:
    """Return §6.7 certainty key. Assumes confidence is in 0..1."""
    if confidence >= 0.85:
        return "certain"
    if confidence >= 0.6:
        return "likely"
    return "looks_like"


def severity_rank(severity: Severity) -> int:
    """Return a higher number for worse severity. Assumes a known Severity."""
    order = {
        Severity.LOW: 1,
        Severity.MEDIUM: 2,
        Severity.HIGH: 3,
        Severity.CRITICAL: 4,
    }
    return order[severity]


def format_mmss(t_ms: int) -> str:
    """Return ``m:ss`` / ``mm:ss`` from game-clock milliseconds."""
    total_s = max(0, int(t_ms)) // 1000
    minutes, seconds = divmod(total_s, 60)
    return f"{minutes}:{seconds:02d}"


def unique_findings(items: Sequence[Finding]) -> tuple[Finding, ...]:
    """Return findings de-duplicated by id, preserving first-seen order."""
    seen: set[str] = set()
    out: list[Finding] = []
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        out.append(item)
    return tuple(out)
