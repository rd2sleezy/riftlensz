from __future__ import annotations

from riftlens.analysis.rules.context import RuleContext
from riftlens.analysis.rules.predicates._common import (
    combine_conf,
    constant_int,
    damage_by_pid,
    death_at,
    death_zone_ok_forward,
    emit,
    enemy_dealers,
    enemy_jungler,
    fact_ev,
    hp_below_max,
    kill_point,
    mmss,
    near_own_turret,
    nearest_ally_distances,
    subject_deaths,
    trinket_available,
    turret_damage_present,
    wards_placed,
)
from riftlens.analysis.rules.registry import register_rule
from riftlens.domain.fact import Fact
from riftlens.domain.finding import Finding
from riftlens.domain.geometry import Point, distance, is_enemy_half, zone_of


@register_rule("rules.risk.died_to_unseen_jungler")
def died_to_unseen_jungler(ctx: RuleContext) -> Finding | None:
    """R-001: enemy jungler damaged the subject while unseen past 3:00."""
    if ctx.t_ms < int(ctx.params.min_game_time_ms):
        return None
    kill = death_at(ctx.gst, ctx.subject_pid, ctx.t_ms)
    if kill is None:
        return None
    jungler = enemy_jungler(ctx.gst, ctx.subject_pid)
    if jungler is None:
        return None
    dealers = enemy_dealers(ctx.gst, kill, ctx.subject_pid)
    if jungler not in dealers and kill.payload.get("killerId") != jungler:
        return None
    team = ctx.gst.participants[ctx.subject_pid].team
    # The death itself makes the jungler observable — measure info age just before.
    age = ctx.features.info_age(team, jungler, max(0, ctx.t_ms - 1))
    if age.value < int(ctx.params.jungler_info_age_min_ms):
        return None
    point = kill_point(kill)
    if point is None or not death_zone_ok_forward(point, team):
        return None
    dmg = damage_by_pid(kill)
    total = sum(dmg.values()) or 1.0
    jshare = 100.0 * dmg.get(jungler, 0.0) / total
    zone = zone_of(point).value
    confidence = combine_conf(kill.confidence, age.confidence, 0.9)
    return emit(
        ctx,
        confidence=confidence,
        evidence=[
            fact_ev(
                "death",
                {"t_ms": ctx.t_ms, "zone": zone, "x": point.x, "y": point.y},
                t_ms=ctx.t_ms,
            ),
            fact_ev(
                "jungler damage share",
                {"jungler_pid": jungler, "pct": round(jshare, 1), "dealers": dealers},
                t_ms=ctx.t_ms,
            ),
            fact_ev(
                "jungler info age",
                {
                    "age_ms": age.value,
                    "basis": age.basis,
                    "interpretation": "inferred from non-omniscient observations",
                },
                t_ms=ctx.t_ms,
                confidence=age.confidence,
                inferred=True,
            ),
        ],
        bindings={
            "death_zone": zone,
            "jungler_damage_pct": round(jshare, 1),
            "info_age_s": round(age.value / 1000.0),
            "jungler_last_seen_mmss": mmss(max(0, ctx.t_ms - age.value)),
            "jungler_champion": ctx.gst.champion_of(jungler),
        },
        severity_bindings={"jungler_damage_pct": jshare},
        map_x=int(point.x),
        map_y=int(point.y),
        outcome="DEATH",
    )


@register_rule("rules.risk.forward_no_ward")
def forward_no_ward(ctx: RuleContext) -> Finding | None:
    """R-003: died in the enemy half with no recent ward and trinket modelled up."""
    kill = death_at(ctx.gst, ctx.subject_pid, ctx.t_ms)
    if kill is None:
        return None
    point = kill_point(kill)
    team = ctx.gst.participants[ctx.subject_pid].team
    if point is None or not is_enemy_half(point, team):
        return None
    lookback = int(ctx.params.ward_lookback_ms)
    if wards_placed(ctx.gst, ctx.subject_pid, ctx.t_ms - lookback, ctx.t_ms):
        return None
    cd = constant_int(ctx.patch, "trinket_ward_cooldown_ms", 240_000)
    available, last_ward = trinket_available(ctx.gst, ctx.subject_pid, ctx.t_ms, cd)
    if not available:
        return None
    zone = zone_of(point).value
    confidence = combine_conf(kill.confidence, 0.7)
    return emit(
        ctx,
        confidence=confidence,
        evidence=[
            fact_ev("death zone", {"zone": zone, "enemy_half": True}, t_ms=ctx.t_ms),
            fact_ev(
                "wards in lookback",
                {"count": 0, "lookback_ms": lookback, "last_ward_ms": last_ward},
                t_ms=ctx.t_ms,
            ),
            fact_ev(
                "trinket model",
                {"available": True, "cooldown_ms": cd, "limitation": "ward location unknown"},
                t_ms=ctx.t_ms,
                inferred=True,
                confidence=0.7,
            ),
        ],
        bindings={"death_zone": zone, "lookback_s": lookback // 1000},
        map_x=int(point.x),
        map_y=int(point.y),
        outcome="DEATH",
    )


@register_rule("rules.risk.caught_alone")
def caught_alone(ctx: RuleContext) -> Finding | None:
    """R-004: late solo death — 1 dealer, or 3+ dealers with no ally nearby."""
    if ctx.t_ms < int(ctx.params.min_game_time_ms):
        return None
    kill = death_at(ctx.gst, ctx.subject_pid, ctx.t_ms)
    if kill is None:
        return None
    point = kill_point(kill)
    if point is None:
        return None
    dealers = enemy_dealers(ctx.gst, kill, ctx.subject_pid)
    allies = nearest_ally_distances(ctx.gst, ctx.subject_pid, ctx.t_ms, point)
    near = [row for row in allies if row[1] <= float(ctx.params.ally_range)]
    alone_collapse = len(dealers) >= 3 and len(near) == 0
    solo = len(dealers) == 1
    if not (solo or alone_collapse):
        return None
    pos_conf = min((row[2] for row in allies), default=0.5)
    confidence = combine_conf(kill.confidence, pos_conf)
    return emit(
        ctx,
        confidence=confidence,
        evidence=[
            fact_ev("enemy dealers", dealers, t_ms=ctx.t_ms),
            fact_ev(
                "ally distances",
                [{"pid": pid, "distance": round(dist, 1)} for pid, dist, _ in allies[:4]],
                t_ms=ctx.t_ms,
                inferred=True,
                confidence=pos_conf,
            ),
        ],
        bindings={"dealer_count": len(dealers), "allies_near": len(near)},
        map_x=int(point.x),
        map_y=int(point.y),
        outcome="DEATH",
    )


@register_rule("rules.risk.dived")
def dived(ctx: RuleContext) -> Finding | None:
    """R-015: died under own turret to 2+ enemies, with turret damage or low prior HP."""
    kill = death_at(ctx.gst, ctx.subject_pid, ctx.t_ms)
    if kill is None:
        return None
    point = kill_point(kill)
    team = ctx.gst.participants[ctx.subject_pid].team
    if point is None or not near_own_turret(point, team):
        return None
    dealers = enemy_dealers(ctx.gst, kill, ctx.subject_pid)
    if len(dealers) < 2:
        return None
    hp = ctx.features.hp_fraction(ctx.subject_pid, max(0, ctx.t_ms - 60_000))
    turret = turret_damage_present(kill)
    low_hp = hp_below_max(hp, float(ctx.params.prior_hp_max))
    if not turret and not low_hp:
        return None
    confidence = combine_conf(kill.confidence, hp.confidence if low_hp else 0.85)
    return emit(
        ctx,
        confidence=confidence,
        evidence=[
            fact_ev(
                "own turret death",
                {"x": point.x, "y": point.y, "zone": zone_of(point).value},
                t_ms=ctx.t_ms,
            ),
            fact_ev("enemy dealers", dealers, t_ms=ctx.t_ms),
            fact_ev("turret damage in death recap", turret, t_ms=ctx.t_ms),
            fact_ev(
                "HP at prior frame",
                {"value": round(hp.value, 3), "hi": hp.hi, "basis": hp.basis},
                t_ms=max(0, ctx.t_ms - 60_000),
                confidence=hp.confidence,
                inferred=hp.confidence < 1.0,
            ),
        ],
        bindings={"dealer_count": len(dealers), "turret_damage": turret},
        map_x=int(point.x),
        map_y=int(point.y),
        outcome="DEATH",
    )


@register_rule("rules.risk.death_location_cluster")
def death_location_cluster(ctx: RuleContext) -> Finding | None:
    """R-018: DBSCAN-like cluster of ≥3 deaths within 2000 units."""
    deaths = subject_deaths(ctx.gst, ctx.subject_pid)
    points = [(item, point) for item in deaths if (point := kill_point(item)) is not None]
    if len(points) < int(ctx.params.min_deaths):
        return None
    radius = float(ctx.params.cluster_radius)
    best: list[tuple[Fact, Point]] = []
    for _, anchor in points:
        members = [(item, point) for item, point in points if distance(anchor, point) <= radius]
        if len(members) > len(best):
            best = members
    if len(best) < int(ctx.params.min_deaths):
        return None
    xs = [point.x for _, point in best]
    ys = [point.y for _, point in best]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    zone = zone_of(Point(cx, cy)).value
    times = [item.t_ms for item, _ in best]
    return emit(
        ctx,
        confidence=0.85,
        evidence=[
            fact_ev("cluster size", len(best), t_ms=ctx.t_ms),
            fact_ev("death times", [mmss(t) for t in times], t_ms=ctx.t_ms),
            fact_ev(
                "centroid",
                {"x": round(cx, 1), "y": round(cy, 1), "zone": zone},
                t_ms=ctx.t_ms,
            ),
        ],
        bindings={
            "cluster_n": len(best),
            "zone": zone,
            "death_clocks": ", ".join(mmss(t) for t in times),
        },
        t_end_ms=max(times),
        map_x=int(cx),
        map_y=int(cy),
    )
