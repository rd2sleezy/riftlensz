from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from riftlens.domain.enums import DataTier, FactKind, GamePhase, Role, Team
from riftlens.domain.estimate import Estimate
from riftlens.domain.fact import Fact, SubjectRef
from riftlens.domain.geometry import (
    CHAMPION_SPEED_UNITS_PER_MS,
    Point,
)

_EARLY_END_MS = 14 * 60 * 1000
_LATE_FALLBACK_MS = 25 * 60 * 1000
_FRAME_MS = 60_000
_CONFIDENCE_FLOOR = 0.15
_CONFIDENCE_DROP = 0.85


@dataclass(frozen=True)
class ParticipantInfo:
    participant_id: int
    champion: str
    role: Role
    team: Team
    puuid: str


@dataclass(frozen=True)
class ParticipantSnapshot:
    participant_id: int
    position: Estimate[Point] | None
    gold: Estimate[int] | None
    cs: Estimate[int] | None
    level: Estimate[int] | None
    health: Estimate[int] | None
    health_max: Estimate[int] | None
    xp: Estimate[int] | None


@dataclass(frozen=True)
class GameStateSnapshot:
    t_ms: int
    phase: GamePhase
    participants: Mapping[int, ParticipantSnapshot]


class GameStateTimeline:
    """Canonical per-match fact store. Analysis reads only from this object."""

    def __init__(
        self,
        *,
        match_id: str,
        patch: str,
        queue_id: int,
        duration_ms: int,
        participants: Mapping[int, ParticipantInfo],
        available_data_tiers: frozenset[DataTier],
        lane_opponents: Mapping[int, int | None] | None = None,
    ) -> None:
        self.match_id = match_id
        self.patch = patch
        self.queue_id = queue_id
        self.duration_ms = duration_ms
        self.participants = dict(participants)
        self.available_data_tiers = available_data_tiers
        self._facts: list[Fact] = []
        self._lane_opponents: dict[int, int | None] = dict(lane_opponents or {})

    def add_facts(self, facts: Iterable[Fact]) -> None:
        """Append facts and keep them ordered by time. Assumes facts use game-clock ms."""
        self._facts.extend(facts)
        self._facts.sort(
            key=lambda fact: (fact.t_ms, fact.kind.value, _subject_sort_key(fact.subject))
        )

    def facts(
        self,
        kind: FactKind | None = None,
        subject: SubjectRef | None = None,
        window: tuple[int, int] | None = None,
        min_confidence: float = 0.0,
    ) -> Sequence[Fact]:
        """Return matching facts in time order. Assumes ``window`` is inclusive [start, end] ms."""
        out: list[Fact] = []
        for fact in self._facts:
            if kind is not None and fact.kind is not kind:
                continue
            if subject is not None and not _same_subject(fact.subject, subject):
                continue
            if window is not None and not (window[0] <= fact.t_ms <= window[1]):
                continue
            if fact.confidence < min_confidence:
                continue
            out.append(fact)
        return out

    def nearest(
        self,
        kind: FactKind,
        t_ms: int,
        direction: Literal["before", "after", "any"] = "any",
        subject: SubjectRef | None = None,
    ) -> Fact | None:
        """Return the closest fact of ``kind`` in ``direction``. Assumes ``t_ms`` is game ms."""
        candidates = [
            fact
            for fact in self._facts
            if fact.kind is kind and (subject is None or _same_subject(fact.subject, subject))
        ]
        if direction == "before":
            before = [fact for fact in candidates if fact.t_ms <= t_ms]
            return before[-1] if before else None
        if direction == "after":
            after = [fact for fact in candidates if fact.t_ms >= t_ms]
            return after[0] if after else None
        if not candidates:
            return None
        return min(candidates, key=lambda fact: (abs(fact.t_ms - t_ms), fact.t_ms))

    def at(self, t_ms: int) -> GameStateSnapshot:
        """Return a per-participant snapshot at ``t_ms``. Assumes participant ids are 1..n."""
        snapshots = {pid: self._participant_snapshot(pid, t_ms) for pid in self.participants}
        return GameStateSnapshot(t_ms=t_ms, phase=self.phase(t_ms), participants=snapshots)

    def interpolate_position(self, pid: int, t_ms: int) -> Estimate[Point]:
        """Return a linearly interpolated position between bracketing 60 s frames.

        Confidence is 1.0 exactly on a frame and decays to 0.15 at the midpoint via
        ``1.0 - 0.85 * sin(pi * frac)``. ``lo``/``hi`` are axis-aligned box corners
        around the interpolated point with radius
        ``min(frac, 1-frac) * 2 * 60000 * CHAMPION_SPEED_UNITS_PER_MS`` — the
        reachable set if the champion walked at 330 u/s perpendicular to the
        interpolated path for the time since the nearer frame. Assumes POSITION
        facts exist for ``pid`` and that frame spacing is ~60 s.
        """
        if pid not in self.participants:
            raise KeyError(pid)
        subject = SubjectRef(kind="participant", id=pid)
        positions = self.facts(kind=FactKind.POSITION, subject=subject)
        if not positions:
            origin = Point(0.0, 0.0)
            return Estimate(
                value=origin,
                confidence=0.0,
                lo=origin,
                hi=origin,
                basis="no position facts",
            )
        exact = next((fact for fact in positions if fact.t_ms == t_ms), None)
        if exact is not None:
            point = _point_from_payload(exact.payload)
            return Estimate(
                value=point,
                confidence=1.0,
                lo=point,
                hi=point,
                basis=f"participant frame at t={t_ms}",
            )
        before = [fact for fact in positions if fact.t_ms < t_ms]
        after = [fact for fact in positions if fact.t_ms > t_ms]
        if not before:
            return self._endpoint_estimate(after[0], t_ms, side="after first frame")
        if not after:
            return self._endpoint_estimate(before[-1], t_ms, side="before last frame")
        left, right = before[-1], after[0]
        span = right.t_ms - left.t_ms
        frac = 0.0 if span <= 0 else (t_ms - left.t_ms) / span
        left_pt = _point_from_payload(left.payload)
        right_pt = _point_from_payload(right.payload)
        value = Point(
            x=left_pt.x + (right_pt.x - left_pt.x) * frac,
            y=left_pt.y + (right_pt.y - left_pt.y) * frac,
        )
        confidence = 1.0 - _CONFIDENCE_DROP * math.sin(math.pi * frac)
        radius = min(frac, 1.0 - frac) * 2.0 * _FRAME_MS * CHAMPION_SPEED_UNITS_PER_MS
        lo = Point(value.x - radius, value.y - radius)
        hi = Point(value.x + radius, value.y + radius)
        basis = f"interpolated between frames {left.t_ms},{right.t_ms}"
        return Estimate(value=value, confidence=confidence, lo=lo, hi=hi, basis=basis)

    def phase(self, t_ms: int) -> GamePhase:
        """Return EARLY/MID/LATE for ``t_ms``. Assumes EARLY ends at 14:00.

        MID runs until the first inhibitor kill or 25:00, whichever comes first.
        """
        if t_ms < _EARLY_END_MS:
            return GamePhase.EARLY
        inhib = self._first_inhib_ms()
        mid_end = _LATE_FALLBACK_MS if inhib is None else min(inhib, _LATE_FALLBACK_MS)
        if t_ms < mid_end:
            return GamePhase.MID
        return GamePhase.LATE

    def role_of(self, pid: int) -> Role:
        """Return the resolved role for ``pid``. Assumes ``pid`` is in this match."""
        return self.participants[pid].role

    def champion_of(self, pid: int) -> str:
        """Return the champion name for ``pid``. Assumes ``pid`` is in this match."""
        return self.participants[pid].champion

    def lane_opponent(self, pid: int) -> int | None:
        """Return the opposing participant id sharing this player's role, or None."""
        return self._lane_opponents.get(pid)

    def jungler_of(self, team: Team) -> int | None:
        """Return that team's jungler pid, or None if no JUNGLE role was resolved."""
        for pid, info in self.participants.items():
            if info.team is team and info.role is Role.JUNGLE:
                return pid
        return None

    def _first_inhib_ms(self) -> int | None:
        for fact in self._facts:
            if fact.kind is not FactKind.BUILDING_KILL:
                continue
            building = str(fact.payload.get("buildingType", ""))
            if building == "INHIBITOR_BUILDING":
                return fact.t_ms
        return None

    def _participant_snapshot(self, pid: int, t_ms: int) -> ParticipantSnapshot:
        subject = SubjectRef(kind="participant", id=pid)
        gold_fact = self.nearest(FactKind.GOLD, t_ms, direction="before", subject=subject)
        cs_fact = self.nearest(FactKind.CS, t_ms, direction="before", subject=subject)
        level_fact = self.nearest(FactKind.LEVEL, t_ms, direction="before", subject=subject)
        health_fact = self.nearest(FactKind.HEALTH, t_ms, direction="before", subject=subject)
        xp_fact = self.nearest(FactKind.XP, t_ms, direction="before", subject=subject)
        gold = _int_estimate(gold_fact, "currentGold", t_ms)
        cs = _cs_estimate(cs_fact, t_ms)
        level = _int_estimate(level_fact, "level", t_ms)
        health = _int_estimate(health_fact, "health", t_ms)
        health_max = _int_estimate(health_fact, "healthMax", t_ms)
        xp = _int_estimate(xp_fact, "xp", t_ms)
        try:
            position = self.interpolate_position(pid, t_ms)
        except KeyError:
            position = None
        return ParticipantSnapshot(
            participant_id=pid,
            position=position,
            gold=gold,
            cs=cs,
            level=level,
            health=health,
            health_max=health_max,
            xp=xp,
        )

    def _endpoint_estimate(self, fact: Fact, t_ms: int, *, side: str) -> Estimate[Point]:
        point = _point_from_payload(fact.payload)
        delta = abs(t_ms - fact.t_ms)
        frac = min(1.0, delta / _FRAME_MS)
        drop = _CONFIDENCE_DROP * math.sin(math.pi * min(frac, 1.0) / 2.0)
        confidence = max(_CONFIDENCE_FLOOR, 1.0 - drop)
        radius = frac * _FRAME_MS * CHAMPION_SPEED_UNITS_PER_MS
        lo = Point(point.x - radius, point.y - radius)
        hi = Point(point.x + radius, point.y + radius)
        return Estimate(
            value=point,
            confidence=confidence,
            lo=lo,
            hi=hi,
            basis=f"clamped {side} t={fact.t_ms}",
        )


def _subject_sort_key(subject: SubjectRef) -> tuple[str, str]:
    return (subject.kind, "" if subject.id is None else str(subject.id))


def _same_subject(left: SubjectRef, right: SubjectRef) -> bool:
    return left.kind == right.kind and left.id == right.id


def _point_from_payload(payload: Mapping[str, object]) -> Point:
    return Point(float(payload["x"]), float(payload["y"]))  # type: ignore[arg-type]


def _int_estimate(fact: Fact | None, key: str, t_ms: int) -> Estimate[int] | None:
    if fact is None:
        return None
    raw = fact.payload.get(key)
    if raw is None:
        return None
    return Estimate(
        value=int(raw),
        confidence=fact.confidence,
        basis=f"{key} at t={fact.t_ms} queried t={t_ms}",
    )


def _cs_estimate(fact: Fact | None, t_ms: int) -> Estimate[int] | None:
    if fact is None:
        return None
    minions = int(fact.payload.get("minionsKilled") or 0)
    jungle = int(fact.payload.get("jungleMinionsKilled") or 0)
    return Estimate(
        value=minions + jungle,
        confidence=fact.confidence,
        basis=f"cs at t={fact.t_ms} queried t={t_ms}",
    )
