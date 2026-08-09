from __future__ import annotations

from riftlens.analysis.features._query import facts_for, jungle_cs
from riftlens.domain.enums import FactKind, Team
from riftlens.domain.estimate import Estimate
from riftlens.domain.timeline import GameStateTimeline

_NO_OBS_CONFIDENCE = 0.25
_CAMP_CLEAR_CONFIDENCE = 0.55
_AGE_DECAY_MS = 5 * 60 * 1000


def info_age(gst: GameStateTimeline, team: Team, target_pid: int, t_ms: int) -> Estimate[int]:
    """Return ms since ``target_pid`` was last observable by ``team``.

    Counts non-omniscient OBSERVATION facts plus jungle CS deltas (camp-clear
    inferences at the later frame). Frame-omniscient observations are ignored.
    Kill-feed events are treated as globally visible in Phase 1. When nothing
    has been seen, returns a large age with low confidence. Assumes ``t_ms`` is
    on the game clock. ``team`` is reserved for Phase-3 vision filtering.
    """
    del team
    observations = _observation_times(gst, target_pid)
    prior = [(stamp, conf) for stamp, conf in observations if stamp <= t_ms]
    if not prior:
        age = max(t_ms, gst.duration_ms)
        return Estimate(
            value=age,
            confidence=_NO_OBS_CONFIDENCE,
            lo=t_ms,
            hi=max(age, gst.duration_ms),
            basis="no non-omniscient observations",
        )
    last_t, last_c = max(prior, key=lambda item: item[0])
    age = t_ms - last_t
    decay = max(0.30, 1.0 - age / _AGE_DECAY_MS)
    confidence = max(0.15, min(1.0, last_c * decay))
    return Estimate(
        value=age,
        confidence=confidence,
        lo=max(0, age - 15_000),
        hi=age + 60_000,
        basis=f"last observable at t={last_t}",
    )


def _observation_times(gst: GameStateTimeline, target_pid: int) -> list[tuple[int, float]]:
    times: list[tuple[int, float]] = []
    for fact in facts_for(gst, FactKind.OBSERVATION, target_pid):
        if fact.payload.get("omniscient"):
            continue
        times.append((fact.t_ms, fact.confidence))
    times.extend(_camp_clear_times(gst, target_pid))
    return times


def _camp_clear_times(gst: GameStateTimeline, target_pid: int) -> list[tuple[int, float]]:
    series = facts_for(gst, FactKind.CS, target_pid)
    out: list[tuple[int, float]] = []
    previous = 0
    for fact in series:
        current = jungle_cs(fact.payload)
        if current > previous:
            out.append((fact.t_ms, _CAMP_CLEAR_CONFIDENCE))
        previous = current
    return out
