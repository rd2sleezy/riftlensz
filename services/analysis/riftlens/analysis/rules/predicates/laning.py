from __future__ import annotations

from riftlens.analysis.features._query import facts_for, subject
from riftlens.analysis.rules.context import RuleContext
from riftlens.analysis.rules.predicates._common import (
    combine_conf,
    cs_rate,
    emit,
    fact_ev,
    gold_meets_min,
    hp_below_max,
    last_purchase,
    mmss,
    subject_deaths,
    unspent_for_rule,
)
from riftlens.analysis.rules.registry import register_rule
from riftlens.domain.enums import FactKind
from riftlens.domain.finding import Finding


@register_rule("rules.laning.cs_collapse_after_death")
def cs_collapse_after_death(ctx: RuleContext) -> Finding | None:
    """R-005: CS/min after ≥2 deaths drops below 55% of the pre-death window."""
    window = int(ctx.params.window_ms)
    ratio_max = float(ctx.params.ratio_max)
    deaths = [
        item
        for item in subject_deaths(ctx.gst, ctx.subject_pid)
        if item.t_ms + window <= ctx.gst.duration_ms
    ]
    collapses: list[dict[str, float | int]] = []
    for death in deaths:
        pre = cs_rate(ctx.gst, ctx.subject_pid, death.t_ms - window, death.t_ms)
        post = cs_rate(ctx.gst, ctx.subject_pid, death.t_ms, death.t_ms + window)
        if pre.value <= 0.5:
            continue
        ratio = post.value / pre.value
        if ratio < ratio_max:
            collapses.append(
                {
                    "t_ms": death.t_ms,
                    "pre": round(pre.value, 2),
                    "post": round(post.value, 2),
                    "ratio": round(ratio, 3),
                }
            )
    if len(collapses) < int(ctx.params.min_occurrences):
        return None
    confidence = 0.85
    return emit(
        ctx,
        confidence=confidence,
        evidence=[
            fact_ev("collapse windows", collapses, t_ms=ctx.t_ms),
            fact_ev("death times", [mmss(int(row["t_ms"])) for row in collapses], t_ms=ctx.t_ms),
        ],
        bindings={"n": len(collapses), "ratio_max_pct": int(ratio_max * 100)},
        t_end_ms=ctx.gst.duration_ms,
    )


@register_rule("rules.laning.low_hp_high_gold")
def low_hp_high_gold(ctx: RuleContext) -> Finding | None:
    """R-007: CI-bounded low HP + large unspent gold + no recent purchase."""
    if ctx.t_ms < int(ctx.params.min_game_time_ms):
        return None
    hp = ctx.features.hp_fraction(ctx.subject_pid, ctx.t_ms)
    if not hp_below_max(hp, float(ctx.params.hp_fraction_max)):
        return None
    gold = unspent_for_rule(ctx, ctx.subject_pid, ctx.t_ms)
    if not gold_meets_min(gold, int(ctx.params.unspent_gold_min)):
        return None
    last = last_purchase(ctx.gst, ctx.subject_pid, ctx.t_ms)
    if last is not None and ctx.t_ms - last.t_ms < int(ctx.params.min_time_since_last_purchase_ms):
        return None
    confidence = combine_conf(hp.confidence, gold.confidence)
    return emit(
        ctx,
        confidence=confidence,
        evidence=[
            fact_ev(
                "HP fraction",
                {
                    "value": round(hp.value, 3),
                    "lo": hp.lo,
                    "hi": hp.hi,
                    "basis": hp.basis,
                    "healthRegen": "not applied",
                },
                t_ms=ctx.t_ms,
                confidence=hp.confidence,
                inferred=hp.confidence < 1.0,
            ),
            fact_ev(
                "unspent gold",
                {"value": gold.value, "lo": gold.lo, "hi": gold.hi, "basis": gold.basis},
                t_ms=ctx.t_ms,
                confidence=gold.confidence,
                inferred=gold.confidence < 1.0,
            ),
            fact_ev(
                "last shop",
                None if last is None else mmss(last.t_ms),
                t_ms=None if last is None else last.t_ms,
            ),
        ],
        bindings={
            "hp_pct": round(100.0 * hp.value),
            "gold": gold.value,
            "last_purchase_mmss": "none" if last is None else mmss(last.t_ms),
        },
        severity_bindings={"hp_fraction": hp.value, "unspent_gold": gold.value},
        gold_equivalent=float(gold.value),
    )


@register_rule("rules.laning.deficit_at_spike")
def deficit_at_spike(ctx: RuleContext) -> Finding | None:
    """R-016: opponent hit 6/11/16 ≥ 25 s earlier and the subject took damage or died."""
    spikes: list[int] = list(ctx.params.spike_levels)
    level_fact = ctx.gst.nearest(
        FactKind.LEVEL_UP, ctx.t_ms, "before", subject=subject(ctx.subject_pid)
    )
    if level_fact is None or level_fact.t_ms != ctx.t_ms:
        # periodic/window may land on the LEVEL_UP time from the segmenter
        level_now = _level_at(ctx, ctx.subject_pid, ctx.t_ms)
    else:
        level_now = int(
            level_fact.payload.get("level") or _level_at(ctx, ctx.subject_pid, ctx.t_ms)
        )
    if level_now not in spikes:
        return None
    opponent = ctx.gst.lane_opponent(ctx.subject_pid)
    if opponent is None:
        return None
    opp_t = _time_reached_level(ctx, opponent, level_now)
    self_t = _time_reached_level(ctx, ctx.subject_pid, level_now)
    if opp_t is None or self_t is None:
        return None
    lead = self_t - opp_t
    if lead < int(ctx.params.min_lead_ms):
        return None
    died = any(
        self_t <= item.t_ms <= self_t + int(ctx.params.outcome_window_ms)
        for item in subject_deaths(ctx.gst, ctx.subject_pid)
    )
    dmg = _damage_taken_delta(ctx, self_t, self_t + int(ctx.params.outcome_window_ms))
    hmax = _health_max(ctx, self_t)
    dmg_frac = dmg / hmax if hmax else 0.0
    if not died and dmg_frac < float(ctx.params.min_damage_frac):
        return None
    return emit(
        ctx,
        confidence=0.85,
        evidence=[
            fact_ev("subject level-up", mmss(self_t), t_ms=self_t),
            fact_ev("opponent level-up", mmss(opp_t), t_ms=opp_t),
            fact_ev("lead ms", lead, t_ms=self_t),
            fact_ev(
                "damage taken frac after spike",
                round(dmg_frac, 3),
                t_ms=self_t,
                inferred=True,
                confidence=0.75,
            ),
            fact_ev("died in window", died, t_ms=self_t),
        ],
        bindings={
            "level": level_now,
            "lead_s": round(lead / 1000.0, 1),
            "opponent": ctx.gst.champion_of(opponent),
        },
        t_ms=self_t,
        outcome="DEATH" if died else "DAMAGED",
    )


def _level_at(ctx: RuleContext, pid: int, t_ms: int) -> int:
    fact = ctx.gst.nearest(FactKind.LEVEL, t_ms, "before", subject=subject(pid))
    if fact is None:
        return 1
    return int(fact.payload.get("level") or 1)


def _time_reached_level(ctx: RuleContext, pid: int, level: int) -> int | None:
    for fact in facts_for(ctx.gst, FactKind.LEVEL_UP, pid):
        if int(fact.payload.get("level") or 0) == level:
            return fact.t_ms
    for fact in facts_for(ctx.gst, FactKind.LEVEL, pid):
        if int(fact.payload.get("level") or 0) >= level:
            return fact.t_ms
    return None


def _damage_taken_delta(ctx: RuleContext, start_ms: int, end_ms: int) -> float:
    left = ctx.gst.nearest(
        FactKind.DAMAGE_ACCUM, start_ms, "before", subject=subject(ctx.subject_pid)
    )
    right = ctx.gst.nearest(
        FactKind.DAMAGE_ACCUM, end_ms, "before", subject=subject(ctx.subject_pid)
    )
    if left is None or right is None:
        return 0.0
    taken_right = float(right.payload.get("totalDamageTaken") or 0)
    taken_left = float(left.payload.get("totalDamageTaken") or 0)
    return taken_right - taken_left


def _health_max(ctx: RuleContext, t_ms: int) -> float:
    fact = ctx.gst.nearest(FactKind.HEALTH, t_ms, "before", subject=subject(ctx.subject_pid))
    if fact is None:
        return 0.0
    return float(fact.payload.get("healthMax") or 0)
