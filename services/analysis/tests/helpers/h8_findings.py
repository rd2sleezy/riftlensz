from __future__ import annotations

from collections.abc import Mapping

from riftlens.domain.enums import EvidenceKind, Severity, Source
from riftlens.domain.evidence import Evidence
from riftlens.domain.finding import Finding
from riftlens.domain.ids import new_ulid


def evidence(
    label: str,
    value: Mapping[str, object] | int | float | str | bool | None,
    *,
    t_ms: int,
    inferred: bool = False,
    confidence: float = 1.0,
) -> Evidence:
    """Return one evidence item. Assumes ``value`` is JSON-serializable."""
    return Evidence(
        kind=EvidenceKind.SERIES if inferred else EvidenceKind.FACT,
        label=label,
        value=value,
        source=Source.DERIVED if inferred else Source.RIOT_TIMELINE,
        t_ms=t_ms,
        confidence=confidence,
    )


def finding(
    *,
    rule_id: str,
    concept_id: str,
    t_ms: int,
    confidence: float = 0.9,
    severity: Severity = Severity.HIGH,
    title: str | None = None,
    gold_equivalent: float | None = 400.0,
    outcome: str | None = "DEATH",
    suppressed: bool = False,
    suppressed_by: str | None = None,
    explanation: str = "template explanation",
    extra_evidence: tuple[Evidence, ...] = (),
    info_age_ms: int | None = None,
    ward_count: int | None = None,
) -> Finding:
    """Return a synthetic Finding for H.8 clustering tests. Not a second rule system."""
    items = [
        evidence("event", {"t_ms": t_ms, "rule_id": rule_id}, t_ms=t_ms),
    ]
    if info_age_ms is not None:
        items.append(
            evidence(
                "jungler info age",
                {
                    "age_ms": info_age_ms,
                    "interpretation": "inferred from non-omniscient observations",
                },
                t_ms=t_ms,
                inferred=True,
                confidence=0.8,
            )
        )
    if ward_count is not None:
        items.append(
            evidence(
                "wards in lookback",
                {"count": ward_count, "lookback_ms": 90_000},
                t_ms=t_ms,
            )
        )
    items.extend(extra_evidence)
    return Finding(
        id=new_ulid(),
        rule_id=rule_id,
        rule_version=1,
        concept_id=concept_id,
        t_ms=t_ms,
        severity=severity,
        confidence=confidence,
        title=title or rule_id,
        evidence=tuple(items),
        gold_equivalent=gold_equivalent,
        outcome=outcome,
        explanation=explanation,
        alternative="do the checkable habit instead",
        suppressed=suppressed,
        suppressed_by=suppressed_by,
    )
