from __future__ import annotations

from riftlens.analysis.features._query import (
    bracket,
    exact_frame,
    facts_for,
    frame_confidence,
    interval_frac,
)
from riftlens.domain.enums import FactKind
from riftlens.domain.estimate import Estimate, combine
from riftlens.domain.fact import Fact
from riftlens.domain.ports import PatchData
from riftlens.domain.timeline import GameStateTimeline


def unspent_gold(gst: GameStateTimeline, pid: int, t_ms: int, patch: PatchData) -> Estimate[int]:
    """Return reconstructed ``currentGold`` at ``t_ms``.

    Anchors at bracketing GOLD frames. Between frames: patch passive gold (not
    timeline ``goldPerSecond`` — that unit is quarantined), CS-gold from CS
    deltas × patch minion values, minus ITEM_PURCHASED costs, plus ITEM_SOLD
    refunds. Unexplained residual to the next frame is blended in and penalizes
    confidence. Assumes GOLD/CS facts exist for ``pid``.
    """
    gold_facts = facts_for(gst, FactKind.GOLD, pid)
    exact = exact_frame(gold_facts, t_ms)
    if exact is not None:
        current = exact.payload.get("currentGold")
        if current is None:
            return Estimate(value=0, confidence=0.1, basis="gold frame missing currentGold")
        value = int(current)
        return Estimate(
            value=value,
            confidence=1.0,
            lo=value,
            hi=value,
            basis=f"frame currentGold t={t_ms}",
        )
    left, right = bracket(gold_facts, t_ms)
    if left is None and right is None:
        return Estimate(value=0, confidence=0.0, basis="no GOLD facts")
    if left is None:
        return _endpoint(right, t_ms, side="before first gold frame")
    if right is None:
        return _forward_open(gst, pid, left, t_ms, patch)
    return _between_frames(gst, pid, left, right, t_ms, patch)


def _between_frames(
    gst: GameStateTimeline,
    pid: int,
    left: Fact,
    right: Fact,
    t_ms: int,
    patch: PatchData,
) -> Estimate[int]:
    right_gold = int(right.payload.get("currentGold") or 0)
    frac = interval_frac(left.t_ms, right.t_ms, t_ms)
    predicted_t, missing = _integrate(gst, pid, left, left.t_ms, t_ms, patch)
    predicted_right, right_missing = _integrate(gst, pid, left, left.t_ms, right.t_ms, patch)
    residual = float(right_gold - predicted_right)
    value = int(round(predicted_t + residual * frac))
    decay = frame_confidence(frac)
    penalty = max(0.4, 1.0 - abs(residual) / 400.0)
    if missing or right_missing:
        penalty *= 0.7
    confidence = combine([decay, penalty])
    pad = int(max(80.0, abs(residual) * 0.75 + 40.0))
    return Estimate(
        value=value,
        confidence=confidence,
        lo=value - pad,
        hi=value + pad,
        basis=f"reconstructed between {left.t_ms},{right.t_ms} residual={residual:.1f}",
    )


def _forward_open(
    gst: GameStateTimeline, pid: int, left: Fact, t_ms: int, patch: PatchData
) -> Estimate[int]:
    predicted, missing = _integrate(gst, pid, left, left.t_ms, t_ms, patch)
    value = int(round(predicted))
    dt = abs(t_ms - left.t_ms)
    confidence = max(0.2, 0.9 - dt / 180_000.0)
    if missing:
        confidence *= 0.7
    pad = 150
    return Estimate(
        value=value,
        confidence=confidence,
        lo=value - pad,
        hi=value + pad,
        basis=f"forward from last gold frame t={left.t_ms}",
    )


def _integrate(
    gst: GameStateTimeline,
    pid: int,
    left: Fact,
    start_ms: int,
    end_ms: int,
    patch: PatchData,
) -> tuple[float, bool]:
    gold = float(left.payload.get("currentGold") or 0)
    missing = False
    gold += _passive(left, start_ms, end_ms, patch)
    cs_gold, cs_missing = _cs_gold(gst, pid, left.t_ms, start_ms, end_ms, patch)
    missing = missing or cs_missing
    gold += cs_gold
    spent, spend_missing = _item_delta(gst, pid, start_ms, end_ms, patch)
    missing = missing or spend_missing
    return gold + spent, missing


def _passive(left: Fact, start_ms: int, end_ms: int, patch: PatchData) -> float:
    raw_gps = left.payload.get("goldPerSecond")
    rate = patch.gold_per_second_rate(int(raw_gps)) if raw_gps is not None else None
    if rate is not None:
        return rate * max(0, end_ms - start_ms)
    # goldPerSecond unit unverified → ignore the frame field; use patch passive.
    return patch.passive_gold(start_ms, end_ms)


def _cs_gold(
    gst: GameStateTimeline,
    pid: int,
    left_frame_ms: int,
    start_ms: int,
    end_ms: int,
    patch: PatchData,
) -> tuple[float, bool]:
    cs_facts = facts_for(gst, FactKind.CS, pid)
    left_cs = next((fact for fact in cs_facts if fact.t_ms == left_frame_ms), None)
    right_cs = next((fact for fact in cs_facts if fact.t_ms > left_frame_ms), None)
    lane_value = patch.average_cs_gold(jungle=False)
    jungle_value = patch.average_cs_gold(jungle=True)
    if left_cs is None or right_cs is None or lane_value is None or jungle_value is None:
        return 0.0, True
    span = right_cs.t_ms - left_cs.t_ms
    if span <= 0:
        return 0.0, False
    frac = interval_frac(left_cs.t_ms, right_cs.t_ms, end_ms) - interval_frac(
        left_cs.t_ms, right_cs.t_ms, start_ms
    )
    d_lane = int(right_cs.payload.get("minionsKilled") or 0) - int(
        left_cs.payload.get("minionsKilled") or 0
    )
    d_jungle = int(right_cs.payload.get("jungleMinionsKilled") or 0) - int(
        left_cs.payload.get("jungleMinionsKilled") or 0
    )
    return (d_lane * lane_value + d_jungle * jungle_value) * frac, False


def _item_delta(
    gst: GameStateTimeline, pid: int, start_ms: int, end_ms: int, patch: PatchData
) -> tuple[float, bool]:
    from riftlens.analysis.features._query import subject

    missing = False
    delta = 0.0
    purchases = [
        fact
        for fact in gst.facts(kind=FactKind.ITEM_PURCHASED, subject=subject(pid))
        if start_ms < fact.t_ms <= end_ms
    ]
    sells = [
        fact
        for fact in gst.facts(kind=FactKind.ITEM_SOLD, subject=subject(pid))
        if start_ms < fact.t_ms <= end_ms
    ]
    for fact in purchases:
        item_id = int(fact.payload.get("itemId") or 0)
        cost = patch.item_purchase_cost(item_id)
        if cost is None:
            missing = True
            continue
        delta -= float(cost)
    for fact in sells:
        item_id = int(fact.payload.get("itemId") or 0)
        refund = patch.item_sell_value(item_id)
        if refund is None:
            missing = True
            continue
        delta += float(refund)
    return delta, missing


def _endpoint(fact: Fact | None, t_ms: int, *, side: str) -> Estimate[int]:
    if fact is None:
        return Estimate(value=0, confidence=0.0, basis=side)
    current = int(fact.payload.get("currentGold") or 0)
    return Estimate(
        value=current,
        confidence=0.35,
        lo=current - 200,
        hi=current + 200,
        basis=f"clamped {side} t={fact.t_ms} queried t={t_ms}",
    )
