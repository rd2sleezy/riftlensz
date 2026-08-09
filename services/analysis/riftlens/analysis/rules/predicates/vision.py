from __future__ import annotations

from riftlens.analysis.features._query import facts_for
from riftlens.analysis.rules.context import RuleContext
from riftlens.analysis.rules.predicates._common import (
    combine_conf,
    constant_int,
    control_ward_ids,
    elite_monster_type,
    emit,
    fact_ev,
    item_id_of,
    mmss,
    reset_times,
    trinket_available,
    wards_placed,
)
from riftlens.analysis.rules.registry import register_rule
from riftlens.domain.enums import FactKind, Role
from riftlens.domain.finding import Finding

_VISION_ROLES = frozenset({Role.JUNGLE, Role.UTILITY})


@register_rule("rules.vision.no_ward_pre_objective")
def no_ward_pre_objective(ctx: RuleContext) -> Finding | None:
    """R-009: zero WARD_PLACED in the 75 s before a major objective contest."""
    lookback = int(ctx.params.lookback_ms)
    if wards_placed(ctx.gst, ctx.subject_pid, ctx.t_ms - lookback, ctx.t_ms):
        return None
    cd = constant_int(ctx.patch, "trinket_ward_cooldown_ms", 240_000)
    available, last_ward = trinket_available(ctx.gst, ctx.subject_pid, ctx.t_ms, cd)
    role = ctx.gst.role_of(ctx.subject_pid)
    if role not in _VISION_ROLES and not available:
        return None
    monster = "UNKNOWN"
    for fact in ctx.gst.facts(kind=FactKind.ELITE_MONSTER_KILL):
        if fact.t_ms == ctx.t_ms:
            monster = elite_monster_type(fact)
            break
    confidence = 0.8 if role in _VISION_ROLES else 0.55
    return emit(
        ctx,
        confidence=combine_conf(confidence, 0.9 if available else 0.7),
        evidence=[
            fact_ev("objective contest", {"type": monster, "t_ms": ctx.t_ms}, t_ms=ctx.t_ms),
            fact_ev("wards in lookback", {"count": 0, "lookback_ms": lookback}, t_ms=ctx.t_ms),
            fact_ev(
                "trinket model",
                {
                    "available": available,
                    "last_ward_ms": last_ward,
                    "limitation": "we can see when you warded, not where",
                },
                t_ms=ctx.t_ms,
                inferred=True,
                confidence=0.7,
            ),
        ],
        bindings={"monster": monster, "lookback_s": lookback // 1000, "role": role.value},
        severity_bindings={"vision_role": 1 if role in _VISION_ROLES else 0},
    )


@register_rule("rules.vision.no_control_wards")
def no_control_wards(ctx: RuleContext) -> Finding | None:
    """R-010: control wards bought / resets < 0.4 after 8:00, with ≥3 resets."""
    if ctx.t_ms < int(ctx.params.min_game_time_ms):
        return None
    gap = constant_int(ctx.patch, "reset_cluster_gap_ms", 12_000)
    min_t = int(ctx.params.min_game_time_ms)
    resets = [t_ms for t_ms in reset_times(ctx.gst, ctx.subject_pid, gap) if t_ms >= min_t]
    if len(resets) < int(ctx.params.min_resets):
        return None
    ids = control_ward_ids(ctx.patch)
    bought = 0
    for fact in facts_for(ctx.gst, FactKind.ITEM_PURCHASED, ctx.subject_pid):
        if fact.t_ms < int(ctx.params.min_game_time_ms):
            continue
        if item_id_of(fact) in ids:
            bought += 1
    ratio = bought / len(resets)
    if ratio >= float(ctx.params.ratio_max):
        return None
    return emit(
        ctx,
        confidence=0.9,
        evidence=[
            fact_ev("resets after 8:00", [mmss(t) for t in resets], t_ms=ctx.t_ms),
            fact_ev("control wards bought", bought, t_ms=ctx.t_ms),
            fact_ev("control ward / reset ratio", round(ratio, 3), t_ms=ctx.t_ms),
            fact_ev("control ward item ids", sorted(ids), t_ms=ctx.t_ms),
        ],
        bindings={"resets": len(resets), "bought": bought, "ratio": round(ratio, 2)},
    )
