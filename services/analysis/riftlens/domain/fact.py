from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from riftlens.domain.enums import FactKind, Source

SubjectKind = Literal["participant", "team", "lane", "neutral", "global"]


@dataclass(frozen=True)
class SubjectRef:
    kind: SubjectKind
    id: int | str | None = None


@dataclass(frozen=True)
class Provenance:
    producer: str
    producer_version: int
    upstream: tuple[str, ...] = ()


@dataclass(frozen=True)
class Fact:
    t_ms: int
    kind: FactKind
    subject: SubjectRef
    payload: Mapping[str, Any]
    source: Source
    confidence: float
    provenance: Provenance

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in 0..1")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
