from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace

from riftlens.analysis.rules.models import RuleDefinition
from riftlens.domain.finding import Finding

DEFAULT_CONFIDENCE_FLOOR = 0.35
_SUPPRESS_WINDOW_MS = 1_000


def postprocess(
    findings: Sequence[Finding],
    rules: Sequence[RuleDefinition],
    *,
    min_confidence: float = DEFAULT_CONFIDENCE_FLOOR,
) -> list[Finding]:
    """Apply cooldown, per-match caps, suppression marks, then the confidence floor.

    Suppression marks findings rather than deleting them. Assumes findings are
    already stamped with rule id/version.
    """
    by_id = {rule.id: rule for rule in rules}
    limited = _apply_caps(findings, by_id)
    marked = _apply_suppression(limited, by_id)
    return [item for item in marked if item.confidence >= min_confidence]


def _apply_caps(
    findings: Sequence[Finding], rules: dict[str, RuleDefinition]
) -> list[Finding]:
    kept: list[Finding] = []
    last_kept: dict[str, int] = {}
    counts: dict[str, int] = defaultdict(int)
    ordered = sorted(findings, key=lambda item: (item.t_ms, item.rule_id, item.id))
    for finding in ordered:
        rule = rules.get(finding.rule_id)
        if rule is None:
            kept.append(finding)
            continue
        cooldown = rule.cooldown_ms
        if cooldown > 0 and finding.rule_id in last_kept:
            if finding.t_ms - last_kept[finding.rule_id] < cooldown:
                continue
        cap = rule.max_findings_per_match
        if cap is not None and counts[finding.rule_id] >= cap:
            continue
        kept.append(finding)
        last_kept[finding.rule_id] = finding.t_ms
        counts[finding.rule_id] += 1
    return kept


def _apply_suppression(
    findings: Sequence[Finding], rules: dict[str, RuleDefinition]
) -> list[Finding]:
    by_rule: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        by_rule[finding.rule_id].append(finding)
    suppressed_at: dict[str, list[Finding]] = {}
    for finding in findings:
        rule = rules.get(finding.rule_id)
        if rule is None or not rule.suppressed_by:
            continue
        for stronger_id in rule.suppressed_by:
            rivals = by_rule.get(stronger_id, [])
            rival = _nearest(finding.t_ms, rivals)
            if rival is None:
                continue
            if abs(rival.t_ms - finding.t_ms) > _SUPPRESS_WINDOW_MS:
                continue
            suppressed_at.setdefault(finding.id, []).append(rival)
    out: list[Finding] = []
    for finding in findings:
        rivals = suppressed_at.get(finding.id, [])
        if not rivals:
            out.append(finding)
            continue
        winner = min(rivals, key=lambda item: (abs(item.t_ms - finding.t_ms), item.rule_id))
        out.append(replace(finding, suppressed=True, suppressed_by=winner.rule_id))
    return out


def _nearest(t_ms: int, findings: Sequence[Finding]) -> Finding | None:
    if not findings:
        return None
    return min(findings, key=lambda item: (abs(item.t_ms - t_ms), item.rule_id, item.id))
