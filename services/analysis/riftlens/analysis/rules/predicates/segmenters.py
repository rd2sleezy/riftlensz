from __future__ import annotations

from riftlens.analysis.features._query import facts_for
from riftlens.analysis.features.fights import segment_fights
from riftlens.analysis.rules.predicates._common import elite_monster_type, killer_team, reset_times
from riftlens.analysis.rules.registry import register_segmenter
from riftlens.domain.enums import FactKind
from riftlens.domain.timeline import GameStateTimeline


@register_segmenter("rules.clock.match_end")
def match_end(gst: GameStateTimeline, subject_pid: int) -> list[int]:
    """Return GAME_END timestamps, or duration_ms when the fact is absent."""
    del subject_pid
    stamps = [fact.t_ms for fact in gst.facts(kind=FactKind.GAME_END)]
    return stamps or [gst.duration_ms]


@register_segmenter("rules.clock.marks_20_and_end")
def marks_20_and_end(gst: GameStateTimeline, subject_pid: int) -> list[int]:
    """Return 20:00 and match end when those times exist on the GST clock."""
    times = [1_200_000]
    times.extend(match_end(gst, subject_pid))
    return sorted({t_ms for t_ms in times if 0 <= t_ms <= gst.duration_ms})


@register_segmenter("rules.deaths.subject_deaths")
def subject_death_times(gst: GameStateTimeline, subject_pid: int) -> list[int]:
    """Return victim death times for ``subject_pid``."""
    return [
        fact.t_ms
        for fact in gst.facts(kind=FactKind.CHAMPION_KILL)
        if fact.payload.get("victimId") == subject_pid
    ]


@register_segmenter("rules.fights.subject_fight_starts")
def subject_fight_starts(gst: GameStateTimeline, subject_pid: int) -> list[int]:
    """Return fight-start times involving ``subject_pid``."""
    times: list[int] = []
    for fight in segment_fights(gst):
        members = set().union(*fight.participants_by_team.values())
        if subject_pid in members:
            times.append(fight.t_start)
    return times


@register_segmenter("rules.fights.subject_fight_ends")
def subject_fight_ends(gst: GameStateTimeline, subject_pid: int) -> list[int]:
    """Return fight-end times involving ``subject_pid``."""
    times: list[int] = []
    for fight in segment_fights(gst):
        members = set().union(*fight.participants_by_team.values())
        if subject_pid in members:
            times.append(fight.t_end)
    return times


@register_segmenter("rules.resets.purchase_clusters")
def purchase_cluster_starts(gst: GameStateTimeline, subject_pid: int) -> list[int]:
    """Return reset cluster starts from ITEM_PURCHASED gaps."""
    gap = 12_000
    return reset_times(gst, subject_pid, gap)


@register_segmenter("rules.objectives.enemy_elite_kills")
def enemy_elite_kills(gst: GameStateTimeline, subject_pid: int) -> list[int]:
    """Return ELITE_MONSTER_KILL times scored by the enemy team."""
    team = gst.participants[subject_pid].team
    times: list[int] = []
    for fact in gst.facts(kind=FactKind.ELITE_MONSTER_KILL):
        killer = killer_team(gst, fact)
        if killer is not None and killer is not team:
            times.append(fact.t_ms)
    return times


@register_segmenter("rules.objectives.major_elite_kills")
def major_elite_kills(gst: GameStateTimeline, subject_pid: int) -> list[int]:
    """Return dragon/baron/herald/voidgrub kill times (any team)."""
    del subject_pid
    times: list[int] = []
    for fact in gst.facts(kind=FactKind.ELITE_MONSTER_KILL):
        label = elite_monster_type(fact).upper()
        tokens = ("DRAGON", "BARON", "HERALD", "HORDE", "GRUB", "ATAKHAN")
        if any(token in label for token in tokens):
            times.append(fact.t_ms)
    return times


@register_segmenter("rules.levels.subject_level_ups")
def subject_level_ups(gst: GameStateTimeline, subject_pid: int) -> list[int]:
    """Return LEVEL_UP times for ``subject_pid``."""
    return [fact.t_ms for fact in facts_for(gst, FactKind.LEVEL_UP, subject_pid)]

