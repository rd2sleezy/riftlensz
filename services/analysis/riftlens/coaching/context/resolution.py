"""Conservative post-window condition resolvers.

RESOLVED means the measurable firing condition stopped being true in the
post-context window. It does not mean the original decision was correct.

Unsupported rules fail closed to NOT_EVALUATED. Ambiguous GST fails closed
to UNKNOWN. Visual, fog, wave, and positioning conditions are never resolved.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from riftlens.analysis.features._query import facts_for
from riftlens.coaching.context.models import (
    ConditionResolution,
    EpisodeBuilderConfig,
    FactRef,
    ResolutionStatus,
    origin_for_source,
    sanitize_payload,
)
from riftlens.domain.enums import FactKind
from riftlens.domain.fact import Fact
from riftlens.domain.finding import Finding
from riftlens.domain.ports import PatchData
from riftlens.domain.timeline import GameStateTimeline

_RESOLUTION_NOTE = (
    "RESOLVED means the measurable condition stopped being true. "
    "It does not mean the original decision was correct."
)
_UNSUPPORTED_NOTE = (
    "No conservative GST proof is defined for this rule. "
    "C.1 does not infer vision, fog, wave state, or decision quality."
)


def resolve_conditions(
    gst: GameStateTimeline,
    findings: Sequence[Finding],
    *,
    participant_id: int,
    window_start_ms: int,
    window_end_ms: int,
    config: EpisodeBuilderConfig,
    patch: PatchData | None,
) -> tuple[ConditionResolution, ...]:
    """Return one resolution row per finding. Assumes windows are clamped."""
    del patch
    return tuple(
        _resolve_one(
            gst,
            item,
            participant_id=participant_id,
            window_start_ms=window_start_ms,
            window_end_ms=window_end_ms,
            config=config,
        )
        for item in findings
    )


def _resolve_one(
    gst: GameStateTimeline,
    item: Finding,
    *,
    participant_id: int,
    window_start_ms: int,
    window_end_ms: int,
    config: EpisodeBuilderConfig,
) -> ConditionResolution:
    post_start = max(window_start_ms, item.t_ms + 1)
    post_end = window_end_ms
    if item.rule_id == "R-006":
        return _resolve_dead_gold(
            gst,
            item,
            participant_id=participant_id,
            post_start=post_start,
            post_end=post_end,
            threshold=config.r006_unspent_gold_min,
        )
    if item.rule_id == "R-007":
        return _resolve_low_hp_high_gold(
            gst,
            item,
            participant_id=participant_id,
            post_start=post_start,
            post_end=post_end,
            hp_max=config.r007_hp_fraction_max,
            gold_min=config.r007_unspent_gold_min,
        )
    return _blank(
        item,
        status=ResolutionStatus.NOT_EVALUATED,
        resolver="none",
        post_start=post_start,
        post_end=post_end,
        note=_UNSUPPORTED_NOTE,
    )


def _resolve_dead_gold(
    gst: GameStateTimeline,
    item: Finding,
    *,
    participant_id: int,
    post_start: int,
    post_end: int,
    threshold: int,
) -> ConditionResolution:
    """R-006: unspent gold above threshold. Prove spend or later frame gold."""
    used_threshold = _threshold_from_evidence(item) or threshold
    purchase = _first_purchase(gst, participant_id, post_start, post_end)
    if purchase is not None:
        return _blank(
            item,
            status=ResolutionStatus.RESOLVED,
            resolver="r006_unspent_gold_purchase",
            post_start=post_start,
            post_end=post_end,
            evaluated_at_ms=purchase.t_ms,
            confidence=purchase.confidence,
            fact_refs=(_fact_ref(purchase),),
        )
    gold = _exact_gold_in_window(gst, participant_id, post_start, post_end)
    if gold is None:
        return _blank(
            item,
            status=ResolutionStatus.UNKNOWN,
            resolver="r006_unspent_gold_frame",
            post_start=post_start,
            post_end=post_end,
            note="No exact GOLD frame or purchase in the post-context window.",
        )
    fact, current = gold
    status = (
        ResolutionStatus.RESOLVED if current < used_threshold else ResolutionStatus.PERSISTED
    )
    return _blank(
        item,
        status=status,
        resolver="r006_unspent_gold_frame",
        post_start=post_start,
        post_end=post_end,
        evaluated_at_ms=fact.t_ms,
        confidence=fact.confidence,
        fact_refs=(_fact_ref(fact),),
    )


def _resolve_low_hp_high_gold(
    gst: GameStateTimeline,
    item: Finding,
    *,
    participant_id: int,
    post_start: int,
    post_end: int,
    hp_max: float,
    gold_min: int,
) -> ConditionResolution:
    """R-007: low HP ∧ high gold ∧ no recent shop. Any conjunct falsified → RESOLVED."""
    purchase = _first_purchase(gst, participant_id, post_start, post_end)
    if purchase is not None:
        return _blank(
            item,
            status=ResolutionStatus.RESOLVED,
            resolver="r007_purchase",
            post_start=post_start,
            post_end=post_end,
            evaluated_at_ms=purchase.t_ms,
            confidence=purchase.confidence,
            fact_refs=(_fact_ref(purchase),),
        )
    health = _exact_hp_fraction(gst, participant_id, post_start, post_end)
    gold = _exact_gold_in_window(gst, participant_id, post_start, post_end)
    refs = _optional_refs(health, gold)
    if health is not None and health[1] > hp_max:
        return _blank(
            item,
            status=ResolutionStatus.RESOLVED,
            resolver="r007_hp_frame",
            post_start=post_start,
            post_end=post_end,
            evaluated_at_ms=health[0].t_ms,
            confidence=health[0].confidence,
            fact_refs=refs,
        )
    if gold is not None and gold[1] < gold_min:
        return _blank(
            item,
            status=ResolutionStatus.RESOLVED,
            resolver="r007_gold_frame",
            post_start=post_start,
            post_end=post_end,
            evaluated_at_ms=gold[0].t_ms,
            confidence=gold[0].confidence,
            fact_refs=refs,
        )
    if _still_low_and_rich(health, gold, hp_max, gold_min):
        assert health is not None and gold is not None
        return _blank(
            item,
            status=ResolutionStatus.PERSISTED,
            resolver="r007_hp_and_gold_frames",
            post_start=post_start,
            post_end=post_end,
            evaluated_at_ms=max(health[0].t_ms, gold[0].t_ms),
            confidence=min(health[0].confidence, gold[0].confidence),
            fact_refs=refs,
        )
    return _blank(
        item,
        status=ResolutionStatus.UNKNOWN,
        resolver="r007_exact_frames",
        post_start=post_start,
        post_end=post_end,
        note="No exact HEALTH/GOLD frames or purchase proving the conjuncts.",
        fact_refs=refs,
    )


def _still_low_and_rich(
    health: tuple[Fact, float] | None,
    gold: tuple[Fact, int] | None,
    hp_max: float,
    gold_min: int,
) -> bool:
    if health is None or gold is None:
        return False
    return health[1] <= hp_max and gold[1] >= gold_min


def _optional_refs(
    health: tuple[Fact, float] | None, gold: tuple[Fact, int] | None
) -> tuple[FactRef, ...]:
    refs: list[FactRef] = []
    if health is not None:
        refs.append(_fact_ref(health[0]))
    if gold is not None:
        refs.append(_fact_ref(gold[0]))
    return tuple(refs)


def _first_purchase(
    gst: GameStateTimeline, pid: int, start_ms: int, end_ms: int
) -> Fact | None:
    for item in facts_for(gst, FactKind.ITEM_PURCHASED, pid):
        if start_ms <= item.t_ms <= end_ms:
            return item
    return None


def _exact_gold_in_window(
    gst: GameStateTimeline, pid: int, start_ms: int, end_ms: int
) -> tuple[Fact, int] | None:
    for item in facts_for(gst, FactKind.GOLD, pid):
        if item.t_ms < start_ms or item.t_ms > end_ms:
            continue
        raw = item.payload.get("currentGold")
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            continue
        return item, int(raw)
    return None


def _exact_hp_fraction(
    gst: GameStateTimeline, pid: int, start_ms: int, end_ms: int
) -> tuple[Fact, float] | None:
    for item in facts_for(gst, FactKind.HEALTH, pid):
        if item.t_ms < start_ms or item.t_ms > end_ms:
            continue
        ratio = _hp_ratio(item.payload)
        if ratio is None:
            continue
        return item, ratio
    return None


def _hp_ratio(payload: Mapping[str, Any]) -> float | None:
    health = payload.get("health")
    maximum = payload.get("healthMax")
    if isinstance(health, bool) or isinstance(maximum, bool):
        return None
    if not isinstance(health, int | float) or not isinstance(maximum, int | float):
        return None
    if maximum <= 0:
        return None
    return float(health) / float(maximum)


def _threshold_from_evidence(item: Finding) -> int | None:
    for evidence in item.evidence:
        payload = evidence.value
        if not isinstance(payload, Mapping):
            continue
        raw = payload.get("threshold")
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            continue
        return int(raw)
    return None


def _fact_ref(fact: Fact) -> FactRef:
    return FactRef(
        t_ms=fact.t_ms,
        kind=fact.kind,
        subject_kind=fact.subject.kind,
        subject_id=fact.subject.id,
        source=fact.source,
        confidence=fact.confidence,
        producer=fact.provenance.producer,
        producer_version=fact.provenance.producer_version,
        payload=sanitize_payload(fact.payload),
        origin=origin_for_source(fact.source),
    )


def _blank(
    item: Finding,
    *,
    status: ResolutionStatus,
    resolver: str,
    post_start: int,
    post_end: int,
    note: str = _RESOLUTION_NOTE,
    evaluated_at_ms: int | None = None,
    confidence: float | None = None,
    fact_refs: tuple[FactRef, ...] = (),
) -> ConditionResolution:
    return ConditionResolution(
        finding_id=item.id,
        status=status,
        resolver=resolver,
        window_start_ms=post_start,
        window_end_ms=post_end,
        evaluated_at_ms=evaluated_at_ms,
        confidence=confidence,
        fact_refs=fact_refs,
        note=note,
    )
