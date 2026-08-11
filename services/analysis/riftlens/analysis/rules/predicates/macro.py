from __future__ import annotations

from riftlens.analysis.features._query import facts_for
from riftlens.analysis.features.fights import Fight, segment_fights
from riftlens.analysis.rules.context import RuleContext
from riftlens.analysis.rules.predicates._common import (
    assisting_ids,
    combine_conf,
    cs_at,
    cs_at_window_end,
    cs_rate,
    elite_monster_type,
    emit,
    fact_ev,
    fight_involves,
    is_alive,
    killer_team,
    mmss,
    pit_point,
    plates_or_towers,
    position_at,
    subject_actionable_after_fight,
    team_down_count,
    wards_placed,
    zone_matches_lane,
)
from riftlens.analysis.rules.registry import register_rule
from riftlens.domain.enums import FactKind
from riftlens.domain.fact import Fact
from riftlens.domain.finding import Finding
from riftlens.domain.geometry import Zone, distance, zone_of
from riftlens.domain.timeline import GameStateTimeline


@register_rule("rules.macro.objective_no_show")
def objective_no_show(ctx: RuleContext) -> Finding | None:
    """R-008: alive, far from an enemy elite kill, not assisting, no plate/tower trade."""
    kill = _elite_at(ctx.gst, ctx.t_ms)
    if kill is None:
        return None
    team = ctx.gst.participants[ctx.subject_pid].team
    if killer_team(ctx.gst, kill) is team:
        return None
    if not is_alive(ctx.gst, ctx.subject_pid, ctx.t_ms, ctx.patch):
        return None
    if ctx.subject_pid in assisting_ids(kill) or kill.payload.get("killerId") == ctx.subject_pid:
        return None
    if team_down_count(ctx.gst, team, ctx.t_ms, ctx.patch) >= int(ctx.params.max_team_down):
        return None
    window = int(ctx.params.trade_window_ms)
    if plates_or_towers(ctx.gst, ctx.subject_pid, ctx.t_ms - window, ctx.t_ms + window) >= int(
        ctx.params.trade_plates_min
    ):
        return None
    monster = elite_monster_type(kill)
    pit = pit_point(monster)
    pos = position_at(ctx.gst, ctx.subject_pid, ctx.t_ms)
    if pos is None:
        return None
    dist = distance(pos.value, pit)
    if dist < float(ctx.params.min_distance):
        return None
    cs0, _ = cs_at(ctx.gst, ctx.subject_pid, ctx.t_ms - window)
    cs1, _ = cs_at(ctx.gst, ctx.subject_pid, ctx.t_ms)
    confidence = combine_conf(pos.confidence, kill.confidence)
    return emit(
        ctx,
        confidence=confidence,
        evidence=[
            fact_ev("objective", {"type": monster, "t_ms": ctx.t_ms}, t_ms=ctx.t_ms),
            fact_ev(
                "player distance to pit",
                {
                    "distance": round(dist, 1),
                    "position_confidence": pos.confidence,
                    "basis": pos.basis,
                },
                t_ms=ctx.t_ms,
                confidence=pos.confidence,
                inferred=pos.confidence < 1.0,
            ),
            fact_ev("CS delta during window", cs1 - cs0, t_ms=ctx.t_ms),
            fact_ev("plates/towers in window", 0, t_ms=ctx.t_ms),
        ],
        bindings={"monster": monster, "distance": int(dist), "cs_delta": cs1 - cs0},
        map_x=int(pos.value.x),
        map_y=int(pos.value.y),
    )


@register_rule("rules.macro.tempo_no_conversion")
def tempo_no_conversion(ctx: RuleContext) -> Finding | None:
    """R-014: won a 2+ kill fight then took no objective/tower/plate during respawn tempo."""
    fight = _fight_ending_at(ctx, ctx.t_ms)
    if fight is None or not fight_involves(fight, ctx.subject_pid):
        return None
    team = ctx.gst.participants[ctx.subject_pid].team
    if fight.winner is not team:
        return None
    our_kills = 0
    for death in fight.deaths_in_order:
        victim = death.payload.get("victimId")
        if not isinstance(victim, int) or victim not in ctx.gst.participants:
            continue
        if ctx.gst.participants[victim].team is not team:
            our_kills += 1
    if our_kills < int(ctx.params.min_kills):
        return None
    if not subject_actionable_after_fight(ctx.gst, ctx.subject_pid, fight, ctx.patch):
        return None
    window = int(ctx.params.tempo_window_ms)
    if plates_or_towers(ctx.gst, ctx.subject_pid, fight.t_end, fight.t_end + window):
        return None
    if any(
        killer_team(ctx.gst, item) is team
        for item in ctx.gst.facts(
            kind=FactKind.ELITE_MONSTER_KILL, window=(fight.t_end, fight.t_end + window)
        )
    ):
        return None
    own = cs_rate(ctx.gst, ctx.subject_pid, 0, fight.t_end)
    post = cs_rate(ctx.gst, ctx.subject_pid, fight.t_end, fight.t_end + window)
    if own.value > 0 and post.value >= own.value * 0.9:
        return None
    return emit(
        ctx,
        confidence=0.75,
        evidence=[
            fact_ev(
                "won fight",
                {"t_start": fight.t_start, "t_end": fight.t_end, "kills": our_kills},
                t_ms=fight.t_end,
            ),
            fact_ev("objectives/towers in tempo window", 0, t_ms=fight.t_end),
            fact_ev(
                "CS rate after fight vs own average",
                {"post": round(post.value, 2), "own": round(own.value, 2)},
                t_ms=fight.t_end,
                inferred=True,
                confidence=0.7,
            ),
        ],
        bindings={"kills": our_kills, "window_s": window // 1000, "fight_mmss": mmss(fight.t_end)},
        t_ms=fight.t_end,
        t_end_ms=fight.t_end + window,
    )


@register_rule("rules.macro.roam_cost_exceeded")
def roam_cost_exceeded(ctx: RuleContext) -> Finding | None:
    """R-017: left an established lane, lost ≥12 CS, gained no kill/assist/objective/ward."""
    pos = position_at(ctx.gst, ctx.subject_pid, ctx.t_ms)
    if pos is None:
        return None
    lane = ctx.lane_of(ctx.subject_pid)
    if lane is None:
        return None
    zone = zone_of(pos.value)
    if not _off_lane(zone):
        return None
    lookback = int(ctx.params.roam_window_ms)
    earlier = position_at(ctx.gst, ctx.subject_pid, max(0, ctx.t_ms - lookback))
    if earlier is None or not zone_matches_lane(zone_of(earlier.value), lane):
        return None
    cs0, c0 = cs_at(ctx.gst, ctx.subject_pid, ctx.t_ms - lookback)
    cs1, c1 = cs_at_window_end(ctx.gst, ctx.subject_pid, ctx.t_ms)
    cs_lost = int(ctx.params.expected_cs_in_window) - (cs1 - cs0)
    if cs_lost < int(ctx.params.min_cs_lost):
        return None
    if _roam_payoff(ctx, ctx.t_ms - lookback, ctx.t_ms):
        return None
    confidence = combine_conf(pos.confidence, c0, c1, 0.55)
    return emit(
        ctx,
        confidence=min(0.7, confidence),
        evidence=[
            fact_ev(
                "roam position",
                {"zone": zone.value, "basis": pos.basis, "limitation": "60s frames only"},
                t_ms=ctx.t_ms,
                confidence=pos.confidence,
                inferred=True,
            ),
            fact_ev(
                "CS gained vs expected",
                {"gained": cs1 - cs0, "expected": int(ctx.params.expected_cs_in_window)},
                t_ms=ctx.t_ms,
            ),
            fact_ev("kill/assist/objective/ward payoff", False, t_ms=ctx.t_ms),
        ],
        bindings={"cs_lost": cs_lost, "zone": zone.value},
        map_x=int(pos.value.x),
        map_y=int(pos.value.y),
    )


def _elite_at(gst: GameStateTimeline, t_ms: int) -> Fact | None:
    for fact in gst.facts(kind=FactKind.ELITE_MONSTER_KILL):
        if fact.t_ms == t_ms:
            return fact
    return None


def _fight_ending_at(ctx: RuleContext, t_ms: int) -> Fight | None:
    for fight in segment_fights(ctx.gst):
        if fight.t_end == t_ms:
            return fight
    return None


def _off_lane(zone: Zone) -> bool:
    return zone not in {Zone.TOP_LANE, Zone.MID_LANE, Zone.BOT_LANE, Zone.BLUE_BASE, Zone.RED_BASE}


def _roam_payoff(ctx: RuleContext, start_ms: int, end_ms: int) -> bool:
    pid = ctx.subject_pid
    for fact in ctx.gst.facts(kind=FactKind.CHAMPION_KILL, window=(start_ms, end_ms)):
        if fact.payload.get("killerId") == pid or pid in assisting_ids(fact):
            return True
    if plates_or_towers(ctx.gst, pid, start_ms, end_ms):
        return True
    if any(item.t_ms >= start_ms for item in facts_for(ctx.gst, FactKind.ELITE_MONSTER_KILL, pid)):
        return True
    if wards_placed(ctx.gst, pid, start_ms, end_ms):
        return True
    return False
