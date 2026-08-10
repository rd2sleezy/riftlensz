from __future__ import annotations

from riftlens.analysis.features._query import facts_for, subject
from riftlens.analysis.rules.context import RuleContext
from riftlens.analysis.rules.predicates._common import (
    anti_heal_ids,
    combine_conf,
    death_at,
    emit,
    fact_ev,
    gold_meets_min,
    is_alive,
    item_id_of,
    last_numeric_frame,
    last_purchase,
    mmss,
    unspent_for_rule,
)
from riftlens.analysis.rules.registry import register_rule
from riftlens.domain.enums import FactKind, Role
from riftlens.domain.finding import Finding

_DAMAGE_ROLES = frozenset({Role.TOP, Role.JUNGLE, Role.MIDDLE, Role.BOTTOM})


@register_rule("rules.economy.unspent_gold_at_death")
def unspent_gold_at_death(ctx: RuleContext) -> Finding | None:
    """R-002: died holding a large reconstructed (or frame-exact) gold pile."""
    kill = death_at(ctx.gst, ctx.subject_pid, ctx.t_ms)
    if kill is None:
        return None
    gold = unspent_for_rule(ctx, ctx.subject_pid, ctx.t_ms)
    minimum = int(ctx.params.unspent_gold_min)
    if not gold_meets_min(gold, minimum):
        return None
    last = last_purchase(ctx.gst, ctx.subject_pid, ctx.t_ms)
    alive_ms = ctx.t_ms if last is None else ctx.t_ms - last.t_ms
    if alive_ms < int(ctx.params.min_alive_since_shop_ms):
        return None
    confidence = combine_conf(kill.confidence, gold.confidence)
    return emit(
        ctx,
        confidence=confidence,
        evidence=[
            fact_ev(
                "unspent gold",
                {
                    "value": gold.value,
                    "lo": gold.lo,
                    "hi": gold.hi,
                    "basis": gold.basis,
                    "goldPerSecond": "not used (unit quarantined)",
                },
                t_ms=ctx.t_ms,
                confidence=gold.confidence,
                inferred=gold.confidence < 1.0,
            ),
            fact_ev(
                "last shop",
                None if last is None else mmss(last.t_ms),
                t_ms=None if last is None else last.t_ms,
            ),
            fact_ev("alive since shop ms", alive_ms, t_ms=ctx.t_ms),
        ],
        bindings={
            "gold": gold.value,
            "last_shop_mmss": "never" if last is None else mmss(last.t_ms),
        },
        gold_equivalent=float(gold.value),
        outcome="DEATH",
        severity_bindings={"unspent_gold": gold.value},
    )


@register_rule("rules.economy.dead_gold")
def dead_gold(ctx: RuleContext) -> Finding | None:
    """R-006: unspent gold stayed above the next-item threshold for ≥ 120 s while alive."""
    if not is_alive(ctx.gst, ctx.subject_pid, ctx.t_ms, ctx.patch):
        return None
    threshold = int(ctx.params.unspent_gold_min)
    hold_ms = int(ctx.params.min_hold_ms)
    step = int(ctx.params.sample_step_ms)
    samples: list[int] = []
    t_ms = ctx.t_ms
    while t_ms >= ctx.t_ms - hold_ms:
        gold = unspent_for_rule(ctx, ctx.subject_pid, t_ms)
        alive = is_alive(ctx.gst, ctx.subject_pid, t_ms, ctx.patch)
        if not gold_meets_min(gold, threshold) or not alive:
            return None
        samples.append(gold.value)
        t_ms -= step
    gold = unspent_for_rule(ctx, ctx.subject_pid, ctx.t_ms)
    return emit(
        ctx,
        confidence=combine_conf(gold.confidence, 0.8),
        evidence=[
            fact_ev(
                "unspent gold samples",
                {"values": samples, "threshold": threshold, "basis": gold.basis},
                t_ms=ctx.t_ms,
                confidence=gold.confidence,
                inferred=gold.confidence < 1.0,
            )
        ],
        bindings={"gold": gold.value, "hold_s": hold_ms // 1000, "threshold": threshold},
        gold_equivalent=float(gold.value),
        severity_bindings={"unspent_gold": gold.value},
    )


@register_rule("rules.economy.no_anti_heal")
def no_anti_heal(ctx: RuleContext) -> Finding | None:
    """R-011: damage role never bought anti-heal vs a HIGH_SUSTAIN enemy with healing."""
    if ctx.gst.role_of(ctx.subject_pid) not in _DAMAGE_ROLES:
        return None
    sustain = _high_sustain_enemies(ctx)
    if not sustain:
        return None
    heal_floor = float(ctx.params.enemy_healing_min)
    healing_rows = _enemy_healing(ctx, sustain)
    evidenced_heal = [row for row in healing_rows if row[1] >= heal_floor]
    inferred_only = not evidenced_heal
    if inferred_only and not bool(ctx.params.allow_tag_only):
        return None
    if _bought_anti_heal(ctx):
        return None
    ids = sorted(anti_heal_ids(ctx.patch))
    confidence = 0.9 if evidenced_heal else 0.45
    focus = evidenced_heal if evidenced_heal else [(pid, 0.0) for pid in sustain]
    names = [ctx.gst.champion_of(pid) for pid, _ in focus]
    return emit(
        ctx,
        confidence=confidence,
        evidence=[
            fact_ev("high-sustain enemies", names, t_ms=ctx.t_ms),
            fact_ev(
                "enemy healing",
                [{"pid": pid, "heal": heal} for pid, heal in healing_rows],
                t_ms=ctx.t_ms,
                inferred=inferred_only,
                confidence=0.9 if evidenced_heal else 0.4,
            ),
            fact_ev("anti-heal item ids considered", ids, t_ms=ctx.t_ms),
            fact_ev("player anti-heal purchases", 0, t_ms=ctx.t_ms),
        ],
        bindings={
            "enemy_names": ", ".join(names),
            "healing_known": not inferred_only,
            "suggested_item": (
                "Oblivion Orb / Bramble Vest / Executioner's Calling (patch item table)"
            ),
        },
    )


@register_rule("rules.economy.low_damage_conversion")
def low_damage_conversion(ctx: RuleContext) -> Finding | None:
    """R-019: teamDamage% / gold_share < 0.65 for a damage role in a 20+ min game."""
    if ctx.gst.duration_ms < int(ctx.params.min_game_ms):
        return None
    if ctx.gst.role_of(ctx.subject_pid) not in _DAMAGE_ROLES:
        return None
    team = ctx.gst.participants[ctx.subject_pid].team
    dmg, gold = {}, {}
    for pid, info in ctx.gst.participants.items():
        if info.team is not team:
            continue
        dmg[pid] = last_numeric_frame(
            ctx.gst, FactKind.DAMAGE_ACCUM, pid, "totalDamageDoneToChampions", ctx.t_ms
        ) or 0.0
        gold_fact = ctx.gst.nearest(FactKind.GOLD, ctx.t_ms, "before", subject=subject(pid))
        gold[pid] = float((gold_fact.payload.get("totalGold") if gold_fact else 0) or 0)
    team_dmg = sum(dmg.values()) or 1.0
    team_gold = sum(gold.values()) or 1.0
    dmg_share = dmg.get(ctx.subject_pid, 0.0) / team_dmg
    gold_share = gold.get(ctx.subject_pid, 0.0) / team_gold
    if gold_share <= 0:
        return None
    ratio = dmg_share / gold_share
    if ratio >= float(ctx.params.ratio_max):
        return None
    return emit(
        ctx,
        confidence=0.85,
        evidence=[
            fact_ev("damage share", round(dmg_share, 4), t_ms=ctx.t_ms),
            fact_ev("gold share", round(gold_share, 4), t_ms=ctx.t_ms),
            fact_ev("conversion ratio", round(ratio, 3), t_ms=ctx.t_ms),
        ],
        bindings={
            "dmg_pct": round(100.0 * dmg_share, 1),
            "gold_pct": round(100.0 * gold_share, 1),
            "ratio": round(ratio, 2),
        },
    )


def _high_sustain_enemies(ctx: RuleContext) -> list[int]:
    tagged = getattr(ctx, "champion_tags_for", None)
    del tagged
    # Engine stores tags on RuleEngine, not context — load from the same YAML via champion name.
    from riftlens.analysis.rules.champion_tags import load_champion_tags

    table = load_champion_tags()
    out: list[int] = []
    my_team = ctx.gst.participants[ctx.subject_pid].team
    for pid, info in ctx.gst.participants.items():
        if info.team is my_team:
            continue
        tags = table.get(info.champion, ()) + table.get(info.champion.casefold(), ())
        if "HIGH_SUSTAIN" in tags:
            out.append(pid)
    return out


def _enemy_healing(ctx: RuleContext, pids: list[int]) -> list[tuple[int, float]]:
    rows: list[tuple[int, float]] = []
    for pid in pids:
        for kind_key in ("totalHeal", "effectiveHealAndShielding"):
            value = last_numeric_frame(ctx.gst, FactKind.DAMAGE_ACCUM, pid, kind_key, ctx.t_ms)
            if value is None:
                derived = ctx.gst.nearest(
                    FactKind.DERIVED, ctx.t_ms, "before", subject=subject(pid)
                )
                if derived is not None:
                    raw = derived.payload.get(kind_key)
                    try:
                        value = float(raw) if raw is not None else None
                    except (TypeError, ValueError):
                        value = None
            if value is not None:
                rows.append((pid, value))
                break
    return rows


def _bought_anti_heal(ctx: RuleContext) -> bool:
    ids = anti_heal_ids(ctx.patch)
    if not ids:
        return False
    for fact in facts_for(ctx.gst, FactKind.ITEM_PURCHASED, ctx.subject_pid):
        if item_id_of(fact) in ids:
            return True
    return False
