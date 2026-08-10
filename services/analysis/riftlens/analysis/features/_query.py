from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from riftlens.domain.enums import FactKind, Team
from riftlens.domain.estimate import Estimate
from riftlens.domain.fact import Fact, SubjectRef
from riftlens.domain.geometry import Point
from riftlens.domain.timeline import GameStateTimeline

_FRAME_DECAY = 0.85


def subject(pid: int) -> SubjectRef:
    """Return a participant subject ref. Assumes ``pid`` is a match participant id."""
    return SubjectRef(kind="participant", id=pid)


def facts_for(gst: GameStateTimeline, kind: FactKind, pid: int) -> Sequence[Fact]:
    """Return facts of ``kind`` for ``pid`` in time order. Assumes GST is populated."""
    return gst.facts(kind=kind, subject=subject(pid))


def bracket(facts: Sequence[Fact], t_ms: int) -> tuple[Fact | None, Fact | None]:
    """Return the last fact at/before ``t_ms`` and the first after. Assumes time-ordered facts."""
    before: Fact | None = None
    after: Fact | None = None
    for fact in facts:
        if fact.t_ms <= t_ms:
            before = fact
        elif fact.t_ms > t_ms:
            after = fact
            break
    return before, after


def exact_frame(facts: Sequence[Fact], t_ms: int) -> Fact | None:
    """Return the fact at exactly ``t_ms``, if any. Assumes time-ordered facts."""
    for fact in facts:
        if fact.t_ms == t_ms:
            return fact
        if fact.t_ms > t_ms:
            return None
    return None


def cs_total(payload: object) -> int:
    """Return lane+jungle CS from a CS fact payload. Assumes Riot frame field names."""
    if not isinstance(payload, Mapping):
        return 0
    return int(payload.get("minionsKilled") or 0) + int(payload.get("jungleMinionsKilled") or 0)


def jungle_cs(payload: object) -> int:
    """Return jungle CS from a CS fact payload. Assumes Riot frame field names."""
    if not isinstance(payload, Mapping):
        return 0
    return int(payload.get("jungleMinionsKilled") or 0)


def frame_confidence(frac: float) -> float:
    """Return 1.0 at a frame edge, decaying to 0.15 at the midpoint. Assumes ``frac`` in 0..1."""
    clamped = min(1.0, max(0.0, frac))
    return 1.0 - _FRAME_DECAY * math.sin(math.pi * clamped)


def interval_frac(left_ms: int, right_ms: int, t_ms: int) -> float:
    """Return progress of ``t_ms`` through ``[left, right]``. Assumes ``right >= left``."""
    span = right_ms - left_ms
    if span <= 0:
        return 0.0
    return min(1.0, max(0.0, (t_ms - left_ms) / span))


def point_from_kill(fact: Fact) -> Point | None:
    """Return a kill position if present. Assumes CHAMPION_KILL payload shape."""
    raw = fact.payload.get("position")
    if not isinstance(raw, dict):
        return None
    if "x" not in raw or "y" not in raw:
        return None
    return Point(float(raw["x"]), float(raw["y"]))


def opposing(team: Team) -> Team:
    """Return the other Summoner's Rift team. Assumes Team is BLUE or RED."""
    return Team.RED if team is Team.BLUE else Team.BLUE


def team_of(gst: GameStateTimeline, pid: int) -> Team:
    """Return ``pid``'s team. Assumes ``pid`` is in ``gst.participants``."""
    return gst.participants[pid].team


def allies_of(gst: GameStateTimeline, pid: int) -> list[int]:
    """Return allied participant ids excluding ``pid``. Assumes participants are populated."""
    team = team_of(gst, pid)
    return [other for other, info in gst.participants.items() if info.team is team and other != pid]


def enemies_of(gst: GameStateTimeline, pid: int) -> list[int]:
    """Return enemy participant ids. Assumes participants are populated."""
    team = team_of(gst, pid)
    return [other for other, info in gst.participants.items() if info.team is not team]


def last_numeric(
    gst: GameStateTimeline, kind: FactKind, pid: int, key: str
) -> Estimate[float] | None:
    """Return the last fact's numeric ``key`` for ``pid``. Assumes facts store that key."""
    series = facts_for(gst, kind, pid)
    if not series:
        return None
    raw = series[-1].payload.get(key)
    if raw is None:
        return None
    last = series[-1]
    return Estimate(
        value=float(raw),
        confidence=last.confidence,
        basis=f"{key} at t={last.t_ms}",
    )
