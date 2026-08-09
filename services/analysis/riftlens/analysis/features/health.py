from __future__ import annotations

from riftlens.analysis.features._query import (
    bracket,
    exact_frame,
    facts_for,
    frame_confidence,
    interval_frac,
    subject,
    team_of,
)
from riftlens.domain.enums import FactKind, Team
from riftlens.domain.estimate import Estimate
from riftlens.domain.fact import Fact
from riftlens.domain.geometry import BLUE_BASE, RED_BASE, Zone, distance, zone_of
from riftlens.domain.ports import PatchData
from riftlens.domain.timeline import GameStateTimeline

_BASE_RADIUS = 1200.0


def hp_fraction(gst: GameStateTimeline, pid: int, t_ms: int, patch: PatchData) -> Estimate[float]:
    """Return estimated HP / HPMax at ``t_ms``.

    Exact at HEALTH frame times. Between frames, subtract a uniform share of the
    ``totalDamageTaken`` delta and add ``healthRegen``. Hard-resets to 1.0 at
    detected fountain visits and respawns. ``lo``/``hi`` are generous so rules
    can require the whole interval to clear a threshold. Assumes HEALTH facts exist.
    """
    health_facts = facts_for(gst, FactKind.HEALTH, pid)
    exact = exact_frame(health_facts, t_ms)
    if exact is not None:
        frac = _ratio(exact)
        if frac is None:
            return Estimate(
                value=0.0, confidence=0.1, lo=0.0, hi=1.0, basis="health frame incomplete"
            )
        return Estimate(value=frac, confidence=1.0, lo=frac, hi=frac, basis=f"frame hp t={t_ms}")
    left, right = bracket(health_facts, t_ms)
    if left is None and right is None:
        return Estimate(value=0.0, confidence=0.0, lo=0.0, hi=1.0, basis="no HEALTH facts")
    if left is None:
        return _clamp_endpoint(right, t_ms, side="before first health frame")
    if right is None:
        return _clamp_endpoint(left, t_ms, side="after last health frame")
    return _between(gst, pid, left, right, t_ms, patch)


def _between(
    gst: GameStateTimeline,
    pid: int,
    left: Fact,
    right: Fact,
    t_ms: int,
    patch: PatchData,
) -> Estimate[float]:
    start = _ratio(left)
    if start is None:
        return Estimate(value=0.0, confidence=0.15, lo=0.0, hi=1.0, basis="left health incomplete")
    if _should_reset(gst, pid, left.t_ms, t_ms, patch):
        value = 1.0
        basis = "hard-reset at base visit or respawn"
    else:
        value = _integrate_hp(gst, pid, left, right, t_ms, start, patch)
        basis = f"interpolated hp between {left.t_ms},{right.t_ms}"
    frac = interval_frac(left.t_ms, right.t_ms, t_ms)
    confidence = frame_confidence(frac)
    pad = max(0.12, 0.40 * (1.0 - confidence) + 0.08)
    return Estimate(
        value=value,
        confidence=confidence,
        lo=max(0.0, value - pad),
        hi=min(1.0, value + pad),
        basis=basis,
    )


def _integrate_hp(
    gst: GameStateTimeline,
    pid: int,
    left: Fact,
    right: Fact,
    t_ms: int,
    start: float,
    patch: PatchData,
) -> float:
    frac = interval_frac(left.t_ms, right.t_ms, t_ms)
    left_max = float(left.payload.get("healthMax") or 0.0)
    right_max = float(right.payload.get("healthMax") or left_max or 1.0)
    hmax = left_max + (right_max - left_max) * frac
    if hmax <= 0:
        return 0.0
    taken = _damage_taken_delta(gst, pid, left.t_ms, right.t_ms) * frac
    regen_stat = float(left.payload.get("healthRegen") or 0.0)
    regen = patch.health_regen_per_ms(regen_stat) * max(0, t_ms - left.t_ms)
    hp = start * left_max - taken + regen
    return min(1.0, max(0.0, hp / hmax))


def _damage_taken_delta(gst: GameStateTimeline, pid: int, left_ms: int, right_ms: int) -> float:
    series = facts_for(gst, FactKind.DAMAGE_ACCUM, pid)
    left = next((fact for fact in series if fact.t_ms == left_ms), None)
    right = next((fact for fact in series if fact.t_ms == right_ms), None)
    if left is None or right is None:
        return 0.0
    return float(right.payload.get("totalDamageTaken") or 0) - float(
        left.payload.get("totalDamageTaken") or 0
    )


def _should_reset(
    gst: GameStateTimeline, pid: int, start_ms: int, t_ms: int, patch: PatchData
) -> bool:
    if _respawned_by(gst, pid, start_ms, t_ms, patch):
        return True
    if _purchased_in_base(gst, pid, start_ms, t_ms):
        return True
    return _in_friendly_base(gst, pid, t_ms)


def _respawned_by(
    gst: GameStateTimeline, pid: int, start_ms: int, t_ms: int, patch: PatchData
) -> bool:
    for fact in gst.facts(kind=FactKind.CHAMPION_KILL, subject=subject(pid)):
        if fact.payload.get("victimId") != pid:
            continue
        if not (start_ms < fact.t_ms <= t_ms):
            continue
        level_fact = gst.nearest(
            FactKind.LEVEL, fact.t_ms, direction="before", subject=subject(pid)
        )
        level = int(level_fact.payload.get("level") or 1) if level_fact else 1
        respawn = patch.respawn_ms(level, fact.t_ms)
        if respawn is None:
            continue
        if fact.t_ms + respawn <= t_ms:
            return True
    return False


def _purchased_in_base(gst: GameStateTimeline, pid: int, start_ms: int, t_ms: int) -> bool:
    purchases = [
        fact
        for fact in gst.facts(kind=FactKind.ITEM_PURCHASED, subject=subject(pid))
        if start_ms < fact.t_ms <= t_ms
    ]
    return bool(purchases) and _in_friendly_base(gst, pid, t_ms)


def _in_friendly_base(gst: GameStateTimeline, pid: int, t_ms: int) -> bool:
    try:
        estimate = gst.interpolate_position(pid, t_ms)
    except KeyError:
        return False
    point = estimate.value
    team = team_of(gst, pid)
    fountain = BLUE_BASE if team is Team.BLUE else RED_BASE
    if distance(point, fountain) <= _BASE_RADIUS:
        return True
    zone = zone_of(point)
    return zone is Zone.BLUE_BASE if team is Team.BLUE else zone is Zone.RED_BASE


def _ratio(fact: Fact) -> float | None:
    health = fact.payload.get("health")
    health_max = fact.payload.get("healthMax")
    if health is None or health_max is None:
        return None
    maximum = float(health_max)
    if maximum <= 0:
        return 0.0
    return min(1.0, max(0.0, float(health) / maximum))


def _clamp_endpoint(fact: Fact | None, t_ms: int, *, side: str) -> Estimate[float]:
    if fact is None:
        return Estimate(value=0.0, confidence=0.0, lo=0.0, hi=1.0, basis=side)
    frac = _ratio(fact)
    if frac is None:
        return Estimate(value=0.0, confidence=0.15, lo=0.0, hi=1.0, basis=side)
    return Estimate(
        value=frac,
        confidence=0.4,
        lo=max(0.0, frac - 0.25),
        hi=min(1.0, frac + 0.25),
        basis=f"clamped {side} t={fact.t_ms} queried t={t_ms}",
    )
