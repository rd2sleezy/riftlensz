from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from riftlens.analysis.features._query import allies_of, cs_total, enemies_of, facts_for, subject
from riftlens.analysis.features.fights import Fight, opposing_team
from riftlens.analysis.rules.context import RuleContext, evidence_fact
from riftlens.analysis.rules.explain import render_rule_template, render_string
from riftlens.domain.enums import EvidenceKind, FactKind, Lane, Source
from riftlens.domain.estimate import Estimate, combine
from riftlens.domain.fact import Fact
from riftlens.domain.finding import Finding
from riftlens.domain.geometry import Point, Zone, distance, is_enemy_half, near_turret, zone_of
from riftlens.domain.ports import PatchData
from riftlens.domain.timeline import GameStateTimeline

_RIVER = frozenset({Zone.TOP_RIVER, Zone.BOT_RIVER})
_PIT = frozenset({Zone.BARON_PIT, Zone.DRAGON_PIT})


def mmss(t_ms: int) -> str:
    """Return ``m:ss`` / ``mm:ss`` game clock. Assumes ``t_ms`` is game-clock ms."""
    total_s = max(0, t_ms) // 1000
    minutes, seconds = divmod(total_s, 60)
    return f"{minutes}:{seconds:02d}"


def certainty_key(confidence: float) -> str:
    """Return mechanical certainty bucket from §6.7. Assumes confidence in 0..1."""
    if confidence >= 0.85:
        return "certain"
    if confidence >= 0.6:
        return "likely"
    return "looks_like"


def emit(
    ctx: RuleContext,
    *,
    confidence: float,
    evidence: Sequence[Any],
    bindings: Mapping[str, Any],
    severity_bindings: Mapping[str, Any] | None = None,
    t_ms: int | None = None,
    t_end_ms: int | None = None,
    gold_equivalent: float | None = None,
    outcome: str | None = None,
    map_x: int | None = None,
    map_y: int | None = None,
) -> Finding:
    """Stamp a Finding with template prose. Assumes evidence is non-empty."""
    stamp = ctx.t_ms if t_ms is None else t_ms
    payload = {
        "t_ms": stamp,
        "t_mmss": mmss(stamp),
        "pid": ctx.subject_pid,
        "champion": ctx.gst.champion_of(ctx.subject_pid),
        "role": ctx.gst.role_of(ctx.subject_pid).value,
        "certainty": certainty_key(confidence),
        **dict(bindings),
    }
    explanation = render_rule_template(ctx.rule.id, payload)
    alternative = (
        render_string(ctx.rule.better_alternative, payload) if ctx.rule.better_alternative else None
    )
    return ctx.finding(
        evidence=evidence,
        confidence=max(0.0, min(1.0, confidence)),
        severity=ctx.severity_with_modifiers(severity_bindings or payload),
        t_ms=stamp,
        t_end_ms=t_end_ms,
        explanation=explanation,
        alternative=alternative,
        gold_equivalent=gold_equivalent,
        outcome=outcome,
        map_x=map_x,
        map_y=map_y,
    )


def fact_ev(
    label: str,
    value: Mapping[str, Any] | Sequence[Any] | str | int | float | bool | None,
    *,
    t_ms: int | None,
    confidence: float = 1.0,
    inferred: bool = False,
) -> Any:
    """Return evidence. Inferred items use DERIVED source and never claim certainty."""
    return evidence_fact(
        label,
        value,
        t_ms=t_ms,
        source=Source.DERIVED if inferred else Source.RIOT_TIMELINE,
        confidence=confidence,
        kind=EvidenceKind.SERIES if inferred else EvidenceKind.FACT,
    )


def subject_deaths(gst: GameStateTimeline, pid: int) -> list[Fact]:
    """Return CHAMPION_KILL facts where ``pid`` is the victim, in time order."""
    return [
        item
        for item in gst.facts(kind=FactKind.CHAMPION_KILL)
        if item.payload.get("victimId") == pid
    ]


def death_at(gst: GameStateTimeline, pid: int, t_ms: int) -> Fact | None:
    """Return the subject's death at ``t_ms``, if any."""
    for item in subject_deaths(gst, pid):
        if item.t_ms == t_ms:
            return item
    return None


def is_alive(gst: GameStateTimeline, pid: int, t_ms: int, patch: PatchData) -> bool:
    """Return False when ``pid`` is inside a modelled respawn window at ``t_ms``."""
    for death in subject_deaths(gst, pid):
        if death.t_ms > t_ms:
            break
        level_fact = gst.nearest(FactKind.LEVEL, death.t_ms, "before", subject=subject(pid))
        level = int(level_fact.payload.get("level") or 1) if level_fact else 1
        respawn = patch.respawn_ms(level, death.t_ms)
        if respawn is None:
            if t_ms - death.t_ms < 10_000:
                return False
            continue
        if death.t_ms <= t_ms < death.t_ms + respawn:
            return False
    return True


def enemy_dealers(gst: GameStateTimeline, kill: Fact, victim: int) -> list[int]:
    """Return distinct enemy participant ids in victimDamageReceived + killer."""
    team = gst.participants[victim].team
    found: list[int] = []
    received = kill.payload.get("victimDamageReceived")
    if isinstance(received, list):
        for entry in received:
            if not isinstance(entry, dict):
                continue
            pid = entry.get("participantId")
            if isinstance(pid, int) and pid in gst.participants:
                if gst.participants[pid].team is not team and pid not in found:
                    found.append(pid)
    killer = kill.payload.get("killerId")
    if isinstance(killer, int) and killer in gst.participants:
        if gst.participants[killer].team is not team and killer not in found:
            found.append(killer)
    return found


def damage_by_pid(kill: Fact) -> dict[int, float]:
    """Return participantId → damage from victimDamageReceived. Missing list → {}."""
    out: dict[int, float] = {}
    received = kill.payload.get("victimDamageReceived")
    if not isinstance(received, list):
        return out
    for entry in received:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("participantId")
        if not isinstance(pid, int):
            continue
        amount = entry.get("damage")
        if amount is None:
            amount = entry.get("magicDamage")
        try:
            out[pid] = out.get(pid, 0.0) + float(amount or 0)
        except (TypeError, ValueError):
            continue
    return out


def kill_point(kill: Fact) -> Point | None:
    """Return death position when the kill payload includes x/y."""
    raw = kill.payload.get("position")
    if not isinstance(raw, dict) or "x" not in raw or "y" not in raw:
        return None
    return Point(float(raw["x"]), float(raw["y"]))


def death_zone_ok_forward(point: Point, team: Any) -> bool:
    """Return True when death is enemy half or river (Appendix E R-001)."""
    zone = zone_of(point)
    if zone in _RIVER or zone in _PIT:
        return True
    return is_enemy_half(point, team)


def last_purchase(gst: GameStateTimeline, pid: int, t_ms: int) -> Fact | None:
    """Return the latest ITEM_PURCHASED for ``pid`` at or before ``t_ms``."""
    return gst.nearest(FactKind.ITEM_PURCHASED, t_ms, "before", subject=subject(pid))


def purchases_in(
    gst: GameStateTimeline, pid: int, start_ms: int, end_ms: int
) -> list[Fact]:
    """Return ITEM_PURCHASED facts on ``(start_ms, end_ms]``."""
    return [
        item
        for item in facts_for(gst, FactKind.ITEM_PURCHASED, pid)
        if start_ms < item.t_ms <= end_ms
    ]


def wards_placed(gst: GameStateTimeline, pid: int, start_ms: int, end_ms: int) -> list[Fact]:
    """Return WARD_PLACED facts on ``[start_ms, end_ms]`` for ``pid``."""
    return [
        item
        for item in facts_for(gst, FactKind.WARD_PLACED, pid)
        if start_ms <= item.t_ms <= end_ms
    ]


def reset_times(gst: GameStateTimeline, pid: int, gap_ms: int) -> list[int]:
    """Return purchase-cluster start times. Assumes a gap starts a new reset."""
    buys = list(facts_for(gst, FactKind.ITEM_PURCHASED, pid))
    if not buys:
        return []
    clusters = [buys[0].t_ms]
    last = buys[0].t_ms
    for item in buys[1:]:
        if item.t_ms - last > gap_ms:
            clusters.append(item.t_ms)
        last = item.t_ms
    return clusters


def control_ward_ids(patch: PatchData) -> frozenset[int]:
    """Return Control Ward item ids from patch item names. Empty if unknown."""
    names = patch.named_constant("control_ward_item_names")
    labels: tuple[str, ...]
    if isinstance(names, list) and names:
        labels = tuple(str(item) for item in names)
    else:
        labels = ("Control Ward",)
    return patch.item_ids_named(*labels)


def anti_heal_ids(patch: PatchData) -> frozenset[int]:
    """Return anti-heal item ids by name needles from patch constants."""
    needles = patch.named_constant("anti_heal_item_name_needles")
    if not isinstance(needles, list) or not needles:
        return frozenset()
    return patch.item_ids_name_contains(*(str(item) for item in needles))


def item_id_of(fact: Fact) -> int:
    """Return itemId from a purchase/sell fact, or 0."""
    try:
        return int(fact.payload.get("itemId") or 0)
    except (TypeError, ValueError):
        return 0


def cs_at(gst: GameStateTimeline, pid: int, t_ms: int) -> tuple[int, float]:
    """Return (cs_total, confidence) from the nearest CS frame at or before ``t_ms``."""
    fact = gst.nearest(FactKind.CS, t_ms, "before", subject=subject(pid))
    if fact is None:
        return 0, 0.0
    return cs_total(fact.payload), fact.confidence


# Allow a CS frame just after a periodic tick to count for the window end.
_CS_END_SLACK_MS = 2_000


def cs_at_window_end(
    gst: GameStateTimeline, pid: int, t_ms: int, *, slack_ms: int = _CS_END_SLACK_MS
) -> tuple[int, float]:
    """Return CS at ``t_ms``, accepting a frame within ``slack_ms`` after the tick.

    Periodic roam checks land on exact 60s boundaries; Riot CS frames often land a
    few hundred ms later. Prefer that nearby after-frame when it is closer than the
    previous before-frame.
    """
    before = gst.nearest(FactKind.CS, t_ms, "before", subject=subject(pid))
    after = gst.nearest(FactKind.CS, t_ms, "after", subject=subject(pid))
    chosen = before
    if after is not None and 0 <= after.t_ms - t_ms <= slack_ms:
        if before is None or (after.t_ms - t_ms) <= (t_ms - before.t_ms):
            chosen = after
    if chosen is None:
        return 0, 0.0
    return cs_total(chosen.payload), chosen.confidence


def cs_rate(gst: GameStateTimeline, pid: int, start_ms: int, end_ms: int) -> Estimate[float]:
    """Return CS/min on ``[start_ms, end_ms]`` from bracketing CS frames."""
    if end_ms <= start_ms:
        return Estimate(value=0.0, confidence=0.0, basis="empty cs window")
    left = gst.nearest(FactKind.CS, start_ms, "before", subject=subject(pid))
    right = gst.nearest(FactKind.CS, end_ms, "before", subject=subject(pid))
    if left is None or right is None:
        return Estimate(value=0.0, confidence=0.2, basis="missing CS frames")
    span_min = (right.t_ms - left.t_ms) / 60_000.0
    if span_min <= 0:
        return Estimate(value=0.0, confidence=0.2, basis="zero cs span")
    rate = (cs_total(right.payload) - cs_total(left.payload)) / span_min
    conf = combine([left.confidence, right.confidence])
    return Estimate(value=rate, confidence=conf, basis=f"cs {left.t_ms}-{right.t_ms}")


def gold_meets_min(estimate: Estimate[int], minimum: int) -> bool:
    """Return True when the conservative gold interval clears ``minimum``."""
    if estimate.lo is not None:
        return int(estimate.lo) >= minimum
    return estimate.value >= minimum and estimate.confidence >= 0.85


def hp_below_max(estimate: Estimate[float], maximum: float) -> bool:
    """Return True when the entire HP CI lies at or below ``maximum``."""
    if estimate.hi is not None:
        return float(estimate.hi) <= maximum
    return estimate.value <= maximum and estimate.confidence >= 0.85


def frame_current_gold(gst: GameStateTimeline, pid: int, t_ms: int) -> Estimate[int] | None:
    """Return exact currentGold when a GOLD frame exists at ``t_ms``."""
    fact = gst.nearest(FactKind.GOLD, t_ms, "before", subject=subject(pid))
    if fact is None or fact.t_ms != t_ms:
        return None
    raw = fact.payload.get("currentGold")
    if raw is None:
        return None
    value = int(raw)
    return Estimate(value=value, confidence=1.0, lo=value, hi=value, basis=f"frame gold t={t_ms}")


def unspent_for_rule(ctx: RuleContext, pid: int, t_ms: int) -> Estimate[int]:
    """Prefer frame-exact currentGold; else H.5 reconstruction (no goldPerSecond)."""
    exact = frame_current_gold(ctx.gst, pid, t_ms)
    if exact is not None:
        return exact
    return ctx.features.unspent_gold(pid, t_ms)


def constant_int(patch: PatchData, key: str, default: int) -> int:
    """Return an int patch constant or ``default`` when missing/unusable."""
    raw = patch.named_constant(key)
    if isinstance(raw, bool) or raw is None:
        return default
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    if isinstance(raw, str):
        try:
            return int(raw)
        except ValueError:
            return default
    return default


def trinket_available(
    gst: GameStateTimeline, pid: int, t_ms: int, cooldown_ms: int
) -> tuple[bool, int | None]:
    """Return (available, last_ward_ms). Models yellow/trinket wards by cooldown only."""
    last: Fact | None = None
    for item in facts_for(gst, FactKind.WARD_PLACED, pid):
        if item.t_ms > t_ms:
            break
        ward_type = str(item.payload.get("wardType") or "").upper()
        if "CONTROL" in ward_type:
            continue
        last = item
    if last is None:
        return True, None
    return (t_ms - last.t_ms) >= cooldown_ms, last.t_ms


def pit_point(monster_type: str) -> Point:
    """Return a pit landmark. Assumes dragon/baron/herald names from timeline."""
    key = monster_type.upper()
    if "BARON" in key or "HORDE" in key:
        return Point(5007.0, 10471.0)
    if "RIFTHERALD" in key or "HERALD" in key:
        return Point(5007.0, 10471.0)
    return Point(9866.0, 4414.0)


def elite_monster_type(fact: Fact) -> str:
    """Return monsterType / monsterSubType from an ELITE_MONSTER_KILL payload."""
    sub = fact.payload.get("monsterSubType") or fact.payload.get("monsterType")
    return str(sub or "UNKNOWN")


def killer_team(gst: GameStateTimeline, fact: Fact) -> Any | None:
    """Return the killing team for an elite/building kill when known."""
    team_id = fact.payload.get("teamId")
    if team_id in {100, 200}:
        from riftlens.domain.enums import Team

        return Team(int(team_id))
    killer = fact.payload.get("killerId")
    if isinstance(killer, int) and killer in gst.participants:
        return gst.participants[killer].team
    return None


def assisting_ids(fact: Fact) -> list[int]:
    """Return assistingParticipantIds as ints."""
    raw = fact.payload.get("assistingParticipantIds")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, int) and item > 0]


def team_down_count(gst: GameStateTimeline, team: Any, t_ms: int, patch: PatchData) -> int:
    """Return how many members of ``team`` are dead at ``t_ms``."""
    count = 0
    for pid, info in gst.participants.items():
        if info.team is not team:
            continue
        if not is_alive(gst, pid, t_ms, patch):
            count += 1
    return count


def plates_or_towers(
    gst: GameStateTimeline, pid: int, start_ms: int, end_ms: int
) -> int:
    """Return plate + turret kills credited to ``pid`` in the window."""
    count = 0
    for kind in (FactKind.TURRET_PLATE_DESTROYED, FactKind.BUILDING_KILL):
        for item in gst.facts(kind=kind, window=(start_ms, end_ms)):
            if item.payload.get("killerId") == pid:
                count += 1
                continue
            if pid in assisting_ids(item):
                count += 1
    return count


def nearest_ally_distances(
    gst: GameStateTimeline, pid: int, t_ms: int, origin: Point
) -> list[tuple[int, float, float]]:
    """Return (ally_id, distance, position_confidence) for living allies."""
    out: list[tuple[int, float, float]] = []
    for ally in allies_of(gst, pid):
        try:
            estimate = gst.interpolate_position(ally, t_ms)
        except KeyError:
            continue
        out.append((ally, distance(estimate.value, origin), estimate.confidence))
    out.sort(key=lambda row: row[1])
    return out


def damage_span_ms(kill: Fact) -> int | None:
    """Return timestamp span of victimDamageReceived entries when present."""
    received = kill.payload.get("victimDamageReceived")
    if not isinstance(received, list):
        return None
    stamps: list[int] = []
    for entry in received:
        if not isinstance(entry, dict):
            continue
        stamp = entry.get("timestamp")
        if isinstance(stamp, int):
            stamps.append(stamp)
    if len(stamps) < 2:
        return None
    return max(stamps) - min(stamps)


def summoner_loadout(gst: GameStateTimeline, pid: int) -> dict[str, Any] | None:
    """Return optional DERIVED summoner payload. Absent on unpaired Riot GST."""
    for item in gst.facts(kind=FactKind.DERIVED, subject=subject(pid)):
        payload = item.payload
        if payload.get("kind") == "summoner_loadout" or "summoner1Id" in payload:
            return dict(payload)
    return None


def last_numeric_frame(
    gst: GameStateTimeline, kind: FactKind, pid: int, key: str, t_ms: int
) -> float | None:
    """Return a numeric payload field from the last fact at or before ``t_ms``."""
    fact = gst.nearest(kind, t_ms, "before", subject=subject(pid))
    if fact is None:
        return None
    raw = fact.payload.get(key)
    try:
        return None if raw is None else float(raw)
    except (TypeError, ValueError):
        return None


def fight_involves(fight: Fight, pid: int) -> bool:
    """Return True when ``pid`` appears in the fight participant sets."""
    for members in fight.participants_by_team.values():
        if pid in members:
            return True
    return False


def died_in_fight(fight: Fight, pid: int) -> bool:
    """Return True when ``pid`` is a victim in ``fight.deaths_in_order``."""
    for death in fight.deaths_in_order:
        if death.payload.get("victimId") == pid:
            return True
    return False


def subject_actionable_after_fight(
    gst: GameStateTimeline, pid: int, fight: Fight, patch: PatchData
) -> bool:
    """Return True when ``pid`` can act at the start of the post-fight window.

    Kill/assist credit is not sufficient. Death before ``fight.t_end`` suppresses
    the window; a modelled respawn after ``t_end`` does not restore it.
    """
    if died_in_fight(fight, pid):
        return False
    return is_alive(gst, pid, fight.t_end, patch)


# Opening of a clustered fight for decision attribution. Shorter than FIGHT_GAP_MS
# (20s) so single-linkage cannot pull a later skirmish into the subject's decision.
SUBJECT_FIGHT_DECISION_MS = 5_000


def kill_involves_pid(kill: Fact, pid: int) -> bool:
    """Return True when ``pid`` is killer, victim, assist, or a damage dealer on ``kill``."""
    if kill.payload.get("victimId") == pid or kill.payload.get("killerId") == pid:
        return True
    if pid in assisting_ids(kill):
        return True
    received = kill.payload.get("victimDamageReceived")
    if isinstance(received, list):
        for entry in received:
            if isinstance(entry, dict) and entry.get("participantId") == pid:
                return True
    return False


def subject_involved_near_fight_start(
    fight: Fight, pid: int, *, window_ms: int = SUBJECT_FIGHT_DECISION_MS
) -> bool:
    """Return True when ``pid`` fights in the opening of ``fight``, not only later.

    Cluster membership alone is not enough: single-linkage can merge a distant
    later skirmish. Decision-time coaching requires involvement on a death within
    ``window_ms`` of ``fight.t_start``.
    """
    for death in fight.deaths_in_order:
        if death.t_ms - fight.t_start > window_ms:
            break
        if kill_involves_pid(death, pid):
            return True
    return False


def zone_matches_lane(zone: Zone, lane: Lane) -> bool:
    """Return True when ``zone`` is the assigned laner's lane corridor."""
    if lane is Lane.TOP:
        return zone is Zone.TOP_LANE
    if lane is Lane.MIDDLE:
        return zone is Zone.MID_LANE
    if lane is Lane.BOTTOM:
        return zone is Zone.BOT_LANE
    return False


# Mutual-trade / dive window: same brief combat, not a later unrelated catch.
FAILED_DIVE_TRADE_MS = 5_000


def subject_champion_kill_in_window(
    gst: GameStateTimeline, pid: int, start_ms: int, end_ms: int
) -> bool:
    """Return True when ``pid`` is the killer of a champion kill in the window."""
    for fact in gst.facts(kind=FactKind.CHAMPION_KILL, window=(start_ms, end_ms)):
        if fact.payload.get("killerId") == pid:
            return True
    return False


def subject_dealt_to_killer(kill: Fact, killer_id: int) -> bool:
    """Return True when the victim dealt damage to ``killer_id`` before dying."""
    dealt = kill.payload.get("victimDamageDealt")
    if not isinstance(dealt, list):
        return False
    for entry in dealt:
        if isinstance(entry, dict) and entry.get("participantId") == killer_id:
            return True
    return False


def failed_enemy_tower_dive_trade(
    gst: GameStateTimeline, pid: int, death: Fact, t_ms: int
) -> bool:
    """Return True when death looks like a failed enemy-tower dive/trade, not a catch.

    Requires enemy-turret context plus aggressive evidence (recent kill by the
    subject, or damage dealt to the killer while taking turret damage). Does not
    suppress every isolated death merely near an enemy turret.
    """
    point = kill_point(death)
    if point is None or pid not in gst.participants:
        return False
    team = gst.participants[pid].team
    turret_ctx = near_enemy_turret(point, team) or turret_damage_present(death)
    if not turret_ctx:
        return False
    if subject_champion_kill_in_window(gst, pid, max(0, t_ms - FAILED_DIVE_TRADE_MS), t_ms):
        return True
    killer = death.payload.get("killerId")
    if (
        isinstance(killer, int)
        and turret_damage_present(death)
        and subject_dealt_to_killer(death, killer)
    ):
        return True
    return False


def first_death_pid(fight: Fight) -> int | None:
    """Return the first victim in fight death order."""
    if not fight.deaths_in_order:
        return None
    victim = fight.deaths_in_order[0].payload.get("victimId")
    return victim if isinstance(victim, int) else None


def team_of_pid(gst: GameStateTimeline, pid: int) -> Any:
    """Return ``pid``'s team. Assumes the participant exists."""
    return gst.participants[pid].team


def enemy_jungler(gst: GameStateTimeline, pid: int) -> int | None:
    """Return the opposing jungler participant id, if assigned."""
    return gst.jungler_of(opposing_team(team_of_pid(gst, pid)))


def position_at(gst: GameStateTimeline, pid: int, t_ms: int) -> Estimate[Point] | None:
    """Return interpolated position or None when the pid is unknown."""
    try:
        return gst.interpolate_position(pid, t_ms)
    except KeyError:
        return None


def turret_damage_present(kill: Fact) -> bool:
    """Return True when victimDamageReceived cites a turret/tower."""
    received = kill.payload.get("victimDamageReceived")
    if not isinstance(received, list):
        return False
    for entry in received:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "")
        kind = str(entry.get("type") or "").upper()
        spell = str(entry.get("spellName") or "").lower()
        if name.startswith("Turret") or "TOWER" in kind or kind == "TOWER":
            return True
        if "turret" in spell or "tower" in spell:
            return True
    return False


def near_own_turret(point: Point, team: Any) -> bool:
    """Return True when ``point`` is within static own-turret radius."""
    return near_turret(point, team) is not None


def near_enemy_turret(point: Point, team: Any) -> bool:
    """Return True when ``point`` is within static enemy-turret radius."""
    return near_turret(point, opposing_team(team)) is not None


def combine_conf(*values: float) -> float:
    """Product-combine confidences with a 0.15 floor for emit gating."""
    return max(0.15, min(1.0, combine(values)))


def iter_enemies(gst: GameStateTimeline, pid: int) -> Iterable[int]:
    """Yield enemy participant ids."""
    return enemies_of(gst, pid)
