"""C.1 coaching episode types.

A CoachingEpisode is a TEMPORAL AND FACTUAL CONTEXT CONTAINER.

It does not claim that one finding caused another, that a decision was good
or bad, that a player should have done something else, a root cause, a
counterfactual, or a coaching priority.

Temporal proximity means only temporal proximity (TEMPORAL_COPRESENCE).
It does not imply CAUSAL_RELATION.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from riftlens.domain.enums import FactKind, GamePhase, Source
from riftlens.domain.fact import Provenance

COACHING_EPISODE_SCHEMA_VERSION = "c1.0"
EPISODE_GROUPING_SEMANTICS = "TEMPORAL_COPRESENCE"
EPISODE_PRODUCER = "c1_episode_builder"
EPISODE_PRODUCER_VERSION = 1

_QUARANTINED_PAYLOAD_KEYS = frozenset({"goldPerSecond", "healthRegen"})


class SnapshotPoint(StrEnum):
    """Named sample along an episode. Not a judgement of play quality."""

    BEFORE = "BEFORE"
    ANCHOR = "ANCHOR"
    AFTER = "AFTER"


class FindingAssociation(StrEnum):
    """How a Finding relates to an episode. Temporal only — never causal."""

    ANCHOR = "ANCHOR"
    TEMPORALLY_ASSOCIATED = "TEMPORALLY_ASSOCIATED"


class ContextGapStatus(StrEnum):
    """Why a contextual field is missing or unsafe to treat as exact."""

    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"
    INFERRED_ONLY = "INFERRED_ONLY"
    COARSE = "COARSE"


class ResolutionStatus(StrEnum):
    """Whether a finding's measurable firing condition still held afterward.

    RESOLVED means the measurable condition stopped being true.
    It does not mean the original decision was correct, that play was
    optimal, or that consequences were reversed.
    """

    RESOLVED = "RESOLVED"
    PERSISTED = "PERSISTED"
    NOT_EVALUATED = "NOT_EVALUATED"
    UNKNOWN = "UNKNOWN"


class ContextOrigin(StrEnum):
    """C.1 classification mapped onto existing Source/provenance."""

    GST_FACT = "GST_FACT"
    GST_DERIVED = "GST_DERIVED"
    FEATURE = "FEATURE"
    INFERENCE = "INFERENCE"
    UNAVAILABLE = "UNAVAILABLE"


def origin_for_source(source: Source) -> ContextOrigin:
    """Return the C.1 origin for an existing Source. Visual sources are rejected."""
    if source in {Source.VISUAL, Source.VISUAL_INFERRED, Source.CV}:
        raise ValueError("C.1 must not consume visual or CV sources")
    if source in {Source.RIOT_TIMELINE, Source.RIOT_MATCH}:
        return ContextOrigin.GST_FACT
    if source is Source.DERIVED:
        return ContextOrigin.FEATURE
    if source is Source.USER:
        return ContextOrigin.INFERENCE
    return ContextOrigin.GST_DERIVED


@dataclass(frozen=True)
class EpisodeBuilderConfig:
    """Context-retrieval windows. These are not gameplay truth."""

    pre_context_ms: int = 60_000
    post_context_ms: int = 30_000
    merge_gap_ms: int = 5_000
    r006_unspent_gold_min: int = 1300
    r007_hp_fraction_max: float = 0.42
    r007_unspent_gold_min: int = 1150

    def __post_init__(self) -> None:
        for name in ("pre_context_ms", "post_context_ms", "merge_gap_ms"):
            value = int(getattr(self, name))
            if value < 0:
                raise ValueError(f"{name} must be >= 0")


@dataclass(frozen=True)
class ContextualValue:
    """One optional sampled field with provenance. ``value`` may be None (UNKNOWN)."""

    value: int | float | str | bool | None
    origin: ContextOrigin
    source: Source | None
    confidence: float | None
    basis: str
    t_ms: int | None = None
    exact: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-stable dict. Assumes fields are serializable."""
        return {
            "value": self.value,
            "origin": self.origin.value,
            "source": None if self.source is None else self.source.value,
            "confidence": self.confidence,
            "basis": self.basis,
            "t_ms": self.t_ms,
            "exact": self.exact,
        }


@dataclass(frozen=True)
class FactRef:
    """Lightweight GST fact pointer. Not a second evidence stream."""

    t_ms: int
    kind: FactKind
    subject_kind: str
    subject_id: int | str | None
    source: Source
    confidence: float
    producer: str
    producer_version: int
    payload: Mapping[str, Any]
    origin: ContextOrigin

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-stable dict. Assumes payload values are serializable."""
        return {
            "t_ms": self.t_ms,
            "kind": self.kind.value,
            "subject_kind": self.subject_kind,
            "subject_id": self.subject_id,
            "source": self.source.value,
            "confidence": self.confidence,
            "producer": self.producer,
            "producer_version": self.producer_version,
            "payload": dict(self.payload),
            "origin": self.origin.value,
        }


@dataclass(frozen=True)
class FindingRef:
    """Pointer to an existing Finding. Evidence stays on the Finding."""

    finding_id: str
    association: FindingAssociation
    rule_id: str
    concept_id: str
    t_ms: int
    t_end_ms: int | None
    suppressed: bool
    suppressed_by: str | None
    evidence_labels: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-stable dict. Assumes ids are strings."""
        return {
            "finding_id": self.finding_id,
            "association": self.association.value,
            "rule_id": self.rule_id,
            "concept_id": self.concept_id,
            "t_ms": self.t_ms,
            "t_end_ms": self.t_end_ms,
            "suppressed": self.suppressed,
            "suppressed_by": self.suppressed_by,
            "evidence_labels": list(self.evidence_labels),
        }


@dataclass(frozen=True)
class FightWindowRef:
    """Derived fight cluster overlapping the episode. Source is always DERIVED."""

    t_start: int
    t_end: int
    participant_ids: tuple[int, ...]
    origin: ContextOrigin = ContextOrigin.FEATURE
    source: Source = Source.DERIVED
    basis: str = "analysis.features.fights.segment_fights"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-stable dict. Assumes participant ids are ints."""
        return {
            "t_start": self.t_start,
            "t_end": self.t_end,
            "participant_ids": list(self.participant_ids),
            "origin": self.origin.value,
            "source": self.source.value,
            "basis": self.basis,
        }


@dataclass(frozen=True)
class ParticipantStateSample:
    """Deterministic participant state at BEFORE / ANCHOR / AFTER."""

    point: SnapshotPoint
    t_ms: int
    participant_id: int
    phase: GamePhase
    level: ContextualValue | None = None
    xp: ContextualValue | None = None
    current_gold: ContextualValue | None = None
    total_gold: ContextualValue | None = None
    unspent_gold: ContextualValue | None = None
    cs: ContextualValue | None = None
    hp_fraction: ContextualValue | None = None
    position_x: ContextualValue | None = None
    position_y: ContextualValue | None = None
    zone: ContextualValue | None = None
    alive: ContextualValue | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-stable dict. Assumes nested values implement to_dict."""
        return {
            "point": self.point.value,
            "t_ms": self.t_ms,
            "participant_id": self.participant_id,
            "phase": self.phase.value,
            "level": None if self.level is None else self.level.to_dict(),
            "xp": None if self.xp is None else self.xp.to_dict(),
            "current_gold": None if self.current_gold is None else self.current_gold.to_dict(),
            "total_gold": None if self.total_gold is None else self.total_gold.to_dict(),
            "unspent_gold": None if self.unspent_gold is None else self.unspent_gold.to_dict(),
            "cs": None if self.cs is None else self.cs.to_dict(),
            "hp_fraction": None if self.hp_fraction is None else self.hp_fraction.to_dict(),
            "position_x": None if self.position_x is None else self.position_x.to_dict(),
            "position_y": None if self.position_y is None else self.position_y.to_dict(),
            "zone": None if self.zone is None else self.zone.to_dict(),
            "alive": None if self.alive is None else self.alive.to_dict(),
        }


@dataclass(frozen=True)
class ContextGap:
    """An important field C.1 could not establish as a safe exact fact."""

    field: str
    status: ContextGapStatus
    reason: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-stable dict. Assumes field/reason are strings."""
        return {"field": self.field, "status": self.status.value, "reason": self.reason}


@dataclass(frozen=True)
class ConditionResolution:
    """Post-window check of a finding's measurable firing condition.

    RESOLVED is not a coaching judgement. Unsupported rules stay NOT_EVALUATED.
    """

    finding_id: str
    status: ResolutionStatus
    resolver: str
    window_start_ms: int
    window_end_ms: int
    evaluated_at_ms: int | None
    confidence: float | None
    fact_refs: tuple[FactRef, ...]
    note: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-stable dict. Assumes fact_refs are serializable."""
        return {
            "finding_id": self.finding_id,
            "status": self.status.value,
            "resolver": self.resolver,
            "window_start_ms": self.window_start_ms,
            "window_end_ms": self.window_end_ms,
            "evaluated_at_ms": self.evaluated_at_ms,
            "confidence": self.confidence,
            "fact_refs": [item.to_dict() for item in self.fact_refs],
            "note": self.note,
        }


@dataclass(frozen=True)
class CoachingEpisode:
    """Versioned temporal context around one or more Findings.

    Grouping is TEMPORAL_COPRESENCE only. This object never encodes causality,
    decision quality, recommendations, or coaching priority.
    """

    id: str
    schema_version: str
    match_id: str
    participant_id: int
    start_ms: int
    end_ms: int
    phase: GamePhase
    findings: tuple[FindingRef, ...]
    fact_refs: tuple[FactRef, ...]
    samples: tuple[ParticipantStateSample, ...]
    fights: tuple[FightWindowRef, ...]
    gaps: tuple[ContextGap, ...]
    resolutions: tuple[ConditionResolution, ...]
    provenance: Provenance
    grouping: str = EPISODE_GROUPING_SEMANTICS
    anchor_timestamps_ms: tuple[int, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-stable dict suitable for golden tests. Not persisted in C.1."""
        return {
            "id": self.id,
            "schema_version": self.schema_version,
            "match_id": self.match_id,
            "participant_id": self.participant_id,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "phase": self.phase.value,
            "grouping": self.grouping,
            "anchor_timestamps_ms": list(self.anchor_timestamps_ms),
            "findings": [item.to_dict() for item in self.findings],
            "fact_refs": [item.to_dict() for item in self.fact_refs],
            "samples": [item.to_dict() for item in self.samples],
            "fights": [item.to_dict() for item in self.fights],
            "gaps": [item.to_dict() for item in self.gaps],
            "resolutions": [item.to_dict() for item in self.resolutions],
            "provenance": {
                "producer": self.provenance.producer,
                "producer_version": self.provenance.producer_version,
                "upstream": list(self.provenance.upstream),
            },
        }


def sanitize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of ``payload`` without quarantined timeline fields."""
    return {key: value for key, value in payload.items() if key not in _QUARANTINED_PAYLOAD_KEYS}


def finding_window(
    t_ms: int,
    t_end_ms: int | None,
    duration_ms: int,
    config: EpisodeBuilderConfig,
) -> tuple[int, int]:
    """Return clamped [start, end] context bounds for one finding timestamp."""
    duration = max(0, int(duration_ms))
    anchor_end = t_ms if t_end_ms is None else max(t_ms, t_end_ms)
    start = max(0, t_ms - config.pre_context_ms)
    end = min(duration, anchor_end + config.post_context_ms)
    if start > end:
        return end, end
    return start, end


def episode_id(
    match_id: str,
    participant_id: int,
    start_ms: int,
    end_ms: int,
    anchor_finding_ids: Sequence[str],
) -> str:
    """Return a stable sha256 episode id. Assumes integer millisecond bounds."""
    payload = json.dumps(
        {
            "schema_version": COACHING_EPISODE_SCHEMA_VERSION,
            "match_id": match_id,
            "participant_id": participant_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "anchor_finding_ids": list(anchor_finding_ids),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"c1e_{digest}"
