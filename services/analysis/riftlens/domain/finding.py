from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from riftlens.domain.enums import Severity
from riftlens.domain.evidence import Evidence


@dataclass(frozen=True)
class Finding:
    """A rule firing with mandatory evidence. Construct via ``RuleContext.finding`` in analysis."""

    id: str
    rule_id: str
    rule_version: int
    concept_id: str
    t_ms: int
    severity: Severity
    confidence: float
    title: str
    evidence: tuple[Evidence, ...]
    t_end_ms: int | None = None
    gold_equivalent: float | None = None
    outcome: str | None = None
    map_x: int | None = None
    map_y: int | None = None
    explanation: str | None = None
    alternative: str | None = None
    explanation_source: str = "TEMPLATE"
    suppressed: bool = False
    suppressed_by: str | None = None

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError("Finding requires at least one Evidence item")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in 0..1")


def require_evidence(evidence: Sequence[Evidence]) -> tuple[Evidence, ...]:
    """Return a non-empty evidence tuple. Raises ``ValueError`` when empty."""
    items = tuple(evidence)
    if not items:
        raise ValueError("Finding requires at least one Evidence item")
    return items
