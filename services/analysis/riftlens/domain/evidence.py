from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from riftlens.domain.enums import EvidenceKind, Source
from riftlens.domain.fact import Provenance


@dataclass(frozen=True)
class Evidence:
    """One cited reason a finding fired. Assumes ``value`` is JSON-serializable."""

    kind: EvidenceKind
    label: str
    value: Mapping[str, Any] | Sequence[Any] | str | int | float | bool | None
    source: Source
    t_ms: int | None = None
    confidence: float | None = None
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("evidence confidence must be in 0..1")
