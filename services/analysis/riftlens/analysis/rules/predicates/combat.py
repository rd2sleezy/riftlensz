from __future__ import annotations

from riftlens.analysis.features.fights import Fight, opposing_team, segment_fights
from riftlens.analysis.rules.context import RuleContext
from riftlens.analysis.rules.predicates._common import (
    combine_conf,
    damage_span_ms,
    death_at,
    emit,
    fact_ev,
    fight_involves,
    first_death_pid,
    iter_enemies,
    mmss,
    summoner_loadout,
    team_of_pid,
)
from riftlens.analysis.rules.registry import register_rule
from riftlens.domain.finding import Finding

_ENGAGE_TANKS = frozenset(
    {"Nautilus", "Leona", "Alistar", "Rell", "Malphite", "Ornn", "Sion", "Zac", "Sejuani"}
)


@register_rule("rules.combat.fight_into_unknown")
def fight_into_unknown(ctx: RuleContext) -> Finding | None:
    """R-012: joined a fight with ≥2 enemies fogged, no numbers lead, lost ≥2."""
    fight = _fight_starting_at(ctx, ctx.t_ms)
    if fight is None or not fight_involves(fight, ctx.subject_pid):
        return None
    team = team_of_pid(ctx.gst, ctx.subject_pid)
    ours = fight.participants_by_team.get(team, frozenset())
    theirs = fight.participants_by_team.get(opposing_team(team), frozenset())
    if len(ours) > len(theirs):
        return None
    ages: list[dict[str, object]] = []
    unknown = 0
    fog_confs: list[float] = []
    for enemy in iter_enemies(ctx.gst, ctx.subject_pid):
        age = ctx.features.info_age(team, enemy, max(0, fight.t_start - 1))
        fogged = age.value > int(ctx.params.info_age_min_ms) and age.confidence >= 0.35
        if fogged:
            unknown += 1
            fog_confs.append(age.confidence)
        ages.append(
            {
                "pid": enemy,
                "champion": ctx.gst.champion_of(enemy),
                "age_ms": age.value,
                "fogged": fogged,
                "confidence": age.confidence,
            }
        )
    if unknown < int(ctx.params.min_unknown_enemies):
        return None
    our_deaths = 0
    for death in fight.deaths_in_order:
        victim = death.payload.get("victimId")
        if isinstance(victim, int) and victim in ctx.gst.participants:
            if team_of_pid(ctx.gst, victim) is team:
                our_deaths += 1
    if our_deaths < int(ctx.params.min_team_deaths):
        return None
    conf = combine_conf(0.75, *fog_confs[:2])
    return emit(
        ctx,
        confidence=conf,
        evidence=[
            fact_ev(
                "fight window",
                {"start": fight.t_start, "end": fight.t_end},
                t_ms=fight.t_start,
            ),
            fact_ev("enemy info ages", ages, t_ms=fight.t_start, inferred=True, confidence=conf),
            fact_ev("team deaths in fight", our_deaths, t_ms=fight.t_start),
            fact_ev("numbers", {"ours": len(ours), "theirs": len(theirs)}, t_ms=fight.t_start),
        ],
        bindings={"unknown": unknown, "our_deaths": our_deaths, "fight_mmss": mmss(fight.t_start)},
        t_ms=fight.t_start,
        t_end_ms=fight.t_end,
        outcome="LOST_FIGHT",
    )


@register_rule("rules.combat.dies_first")
def dies_first(ctx: RuleContext) -> Finding | None:
    """R-013: first death in ≥50% of joined fights (min 3), not an engage tank."""
    champ = ctx.gst.champion_of(ctx.subject_pid)
    if champ in _ENGAGE_TANKS:
        return None
    joined = [fight for fight in segment_fights(ctx.gst) if fight_involves(fight, ctx.subject_pid)]
    if len(joined) < int(ctx.params.min_fights):
        return None
    firsts = [fight for fight in joined if first_death_pid(fight) == ctx.subject_pid]
    ratio = len(firsts) / len(joined)
    if ratio < float(ctx.params.ratio_min):
        return None
    return emit(
        ctx,
        confidence=0.85,
        evidence=[
            fact_ev("fights joined", len(joined), t_ms=ctx.t_ms),
            fact_ev("first deaths", len(firsts), t_ms=ctx.t_ms),
            fact_ev(
                "first-death timestamps",
                [mmss(fight.t_start) for fight in firsts],
                t_ms=ctx.t_ms,
            ),
        ],
        bindings={"firsts": len(firsts), "joined": len(joined), "pct": round(100.0 * ratio)},
        t_end_ms=ctx.gst.duration_ms,
    )


@register_rule("rules.combat.unused_escape")
def unused_escape(ctx: RuleContext) -> Finding | None:
    """R-020: Flash modelled available and the death recap spanned > 1.5 s."""
    kill = death_at(ctx.gst, ctx.subject_pid, ctx.t_ms)
    if kill is None:
        return None
    loadout = summoner_loadout(ctx.gst, ctx.subject_pid)
    if loadout is None:
        return None
    flash_ids = ctx.patch.named_constant("flash_summoner_ids")
    ids = {int(x) for x in flash_ids} if isinstance(flash_ids, list) else {4}
    s1 = int(loadout.get("summoner1Id") or 0)
    s2 = int(loadout.get("summoner2Id") or 0)
    if s1 not in ids and s2 not in ids:
        return None
    casts_key = "summoner1Casts" if s1 in ids else "summoner2Casts"
    casts = int(loadout.get(casts_key) or 0)
    # Post-game cast totals cannot time a Flash. Only fire when casts == 0 (never used).
    if casts != 0:
        return None
    span = damage_span_ms(kill)
    min_span = int(ctx.params.min_damage_span_ms)
    if span is None or span <= min_span:
        return None
    return emit(
        ctx,
        confidence=0.7,
        evidence=[
            fact_ev(
                "summoner loadout",
                {
                    **{
                        k: loadout.get(k)
                        for k in (
                            "summoner1Id",
                            "summoner2Id",
                            "summoner1Casts",
                            "summoner2Casts",
                        )
                    },
                    "source": "DERIVED fact",
                },
                t_ms=ctx.t_ms,
                inferred=True,
                confidence=0.7,
            ),
            fact_ev("flash casts (match total)", casts, t_ms=ctx.t_ms),
            fact_ev("death recap span ms", span, t_ms=ctx.t_ms),
        ],
        bindings={"span_s": round(span / 1000.0, 2)},
        outcome="DEATH",
    )


def _fight_starting_at(ctx: RuleContext, t_ms: int) -> Fight | None:
    for fight in ctx.features.segment_fights():
        if fight.t_start == t_ms:
            return fight
    return None
