from __future__ import annotations

from riftlens.analysis.features._query import facts_for, subject
from riftlens.analysis.rules.context import RuleContext
from riftlens.analysis.rules.predicates._common import (
    assisting_ids,
    control_ward_ids,
    cs_at,
    emit,
    fact_ev,
    is_alive,
    item_id_of,
    mmss,
    pit_point,
    position_at,
    reset_times,
    subject_deaths,
    team_down_count,
    unspent_for_rule,
)
from riftlens.analysis.rules.registry import register_rule
from riftlens.domain.enums import FactKind
from riftlens.domain.fact import Fact
from riftlens.domain.finding import Finding
from riftlens.domain.geometry import distance


@register_rule("rules.positive.clean_lane_phase")
def clean_lane_phase(ctx: RuleContext) -> Finding | None:
    """P-001: CS diff ≥ +10 at 14:00 with ≤ 1 death."""
    mark = int(ctx.params.mark_ms)
    if ctx.gst.duration_ms < mark:
        return None
    opponent = ctx.gst.lane_opponent(ctx.subject_pid)
    if opponent is None:
        return None
    mine, c0 = cs_at(ctx.gst, ctx.subject_pid, mark)
    theirs, c1 = cs_at(ctx.gst, opponent, mark)
    diff = mine - theirs
    if diff < int(ctx.params.min_cs_diff):
        return None
    deaths = [item for item in subject_deaths(ctx.gst, ctx.subject_pid) if item.t_ms <= mark]
    if len(deaths) > int(ctx.params.max_deaths):
        return None
    return emit(
        ctx,
        confidence=min(c0, c1, 1.0),
        evidence=[
            fact_ev("CS at 14:00", {"subject": mine, "opponent": theirs, "diff": diff}, t_ms=mark),
            fact_ev("deaths before 14:00", len(deaths), t_ms=mark),
        ],
        bindings={"diff": diff, "deaths": len(deaths), "opponent": ctx.gst.champion_of(opponent)},
        t_ms=mark,
    )


@register_rule("rules.positive.efficient_resets")
def efficient_resets(ctx: RuleContext) -> Finding | None:
    """P-002: ≥3 resets spending ≥85% of pre-reset gold with ≤8 CS lost."""
    gap = int(ctx.params.reset_gap_ms)
    resets = reset_times(ctx.gst, ctx.subject_pid, gap)
    good: list[dict[str, object]] = []
    window = int(ctx.params.cs_window_ms)
    for t_ms in resets:
        gold = unspent_for_rule(ctx, ctx.subject_pid, max(0, t_ms - 1000))
        spent = _gold_spent_at_reset(ctx, t_ms, gap)
        if gold.value <= 0:
            continue
        spend_frac = spent / max(gold.value, 1)
        cs0, _ = cs_at(ctx.gst, ctx.subject_pid, t_ms)
        cs1, _ = cs_at(ctx.gst, ctx.subject_pid, t_ms + window)
        lost = max(0, int(ctx.params.expected_cs_in_window) - (cs1 - cs0))
        if spend_frac >= float(ctx.params.min_spend_frac) and lost <= int(ctx.params.max_cs_lost):
            good.append({"t_ms": t_ms, "spend_frac": round(spend_frac, 2), "cs_lost": lost})
    if len(good) < int(ctx.params.min_resets):
        return None
    return emit(
        ctx,
        confidence=0.8,
        evidence=[fact_ev("efficient resets", good, t_ms=ctx.t_ms)],
        bindings={"n": len(good), "example_mmss": mmss(_int_field(good[0]["t_ms"]))},
    )


@register_rule("rules.positive.objective_discipline")
def objective_discipline(ctx: RuleContext) -> Finding | None:
    """P-003: contest-weighted participation = 100% on ≥4 elite objectives."""
    team = ctx.gst.participants[ctx.subject_pid].team
    elites = list(ctx.gst.facts(kind=FactKind.ELITE_MONSTER_KILL))
    if len(elites) < int(ctx.params.min_objectives):
        return None
    contested = 0
    present = 0
    for fact in elites:
        down = team_down_count(ctx.gst, team, fact.t_ms, ctx.patch)
        if down >= 2:
            continue
        contested += 1
        if _present_for_objective(ctx, fact):
            present += 1
    if contested < int(ctx.params.min_objectives) or present != contested:
        return None
    return emit(
        ctx,
        confidence=0.85,
        evidence=[
            fact_ev("contestable objectives", contested, t_ms=ctx.t_ms),
            fact_ev("player present", present, t_ms=ctx.t_ms),
        ],
        bindings={"n": contested},
    )


@register_rule("rules.positive.vision_habit")
def vision_habit(ctx: RuleContext) -> Finding | None:
    """P-004: control ward on ≥80% of resets after 8:00."""
    gap = int(ctx.params.reset_gap_ms)
    start = int(ctx.params.min_game_time_ms)
    resets = [t_ms for t_ms in reset_times(ctx.gst, ctx.subject_pid, gap) if t_ms >= start]
    if len(resets) < int(ctx.params.min_resets):
        return None
    ids = control_ward_ids(ctx.patch)
    hits = 0
    for t_ms in resets:
        buys = [
            fact
            for fact in facts_for(ctx.gst, FactKind.ITEM_PURCHASED, ctx.subject_pid)
            if abs(fact.t_ms - t_ms) <= gap and item_id_of(fact) in ids
        ]
        if buys:
            hits += 1
    ratio = hits / len(resets)
    if ratio < float(ctx.params.ratio_min):
        return None
    return emit(
        ctx,
        confidence=0.9,
        evidence=[
            fact_ev("resets", len(resets), t_ms=ctx.t_ms),
            fact_ev("resets with control ward", hits, t_ms=ctx.t_ms),
            fact_ev("ratio", round(ratio, 3), t_ms=ctx.t_ms),
        ],
        bindings={"pct": round(100.0 * ratio), "resets": len(resets)},
    )


@register_rule("rules.positive.recovered_from_behind")
def recovered_from_behind(ctx: RuleContext) -> Finding | None:
    """P-005: gold deficit ≥ 1500 at some frame, ≤ 0 by 25:00 vs lane opponent or enemy avg."""
    mark = int(ctx.params.recover_by_ms)
    if ctx.gst.duration_ms < mark:
        return None
    opponent = ctx.gst.lane_opponent(ctx.subject_pid)
    if opponent is None:
        return None
    worst = 0
    worst_t = 0
    recovered = False
    for fact in ctx.gst.facts(kind=FactKind.GOLD, subject=subject(ctx.subject_pid)):
        if fact.t_ms > mark:
            break
        mine = int(fact.payload.get("totalGold") or 0)
        theirs_f = ctx.gst.nearest(FactKind.GOLD, fact.t_ms, "before", subject=subject(opponent))
        theirs = int((theirs_f.payload.get("totalGold") if theirs_f else 0) or 0)
        diff = mine - theirs
        if diff < worst:
            worst = diff
            worst_t = fact.t_ms
        if fact.t_ms >= mark - 60_000 and diff >= 0:
            recovered = True
    if worst > -int(ctx.params.min_deficit) or not recovered:
        return None
    return emit(
        ctx,
        confidence=0.9,
        evidence=[
            fact_ev("worst gold diff", {"diff": worst, "t_ms": worst_t}, t_ms=worst_t),
            fact_ev("gold diff by 25:00", ">= 0", t_ms=mark),
        ],
        bindings={"worst": worst, "worst_mmss": mmss(worst_t)},
        t_ms=mark,
    )


def _int_field(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise TypeError("expected int field")
    return raw


def _gold_spent_at_reset(ctx: RuleContext, t_ms: int, gap: int) -> int:
    total = 0
    for fact in facts_for(ctx.gst, FactKind.ITEM_PURCHASED, ctx.subject_pid):
        if abs(fact.t_ms - t_ms) <= gap:
            cost = ctx.patch.item_purchase_cost(item_id_of(fact))
            if cost:
                total += cost
    return total


def _present_for_objective(ctx: RuleContext, fact: Fact) -> bool:
    pid = ctx.subject_pid
    if fact.payload.get("killerId") == pid or pid in assisting_ids(fact):
        return True
    if not is_alive(ctx.gst, pid, fact.t_ms, ctx.patch):
        return False
    pos = position_at(ctx.gst, pid, fact.t_ms)
    if pos is None:
        return False
    return distance(pos.value, pit_point("DRAGON")) < 4500 or distance(
        pos.value, pit_point("BARON")
    ) < 4500
