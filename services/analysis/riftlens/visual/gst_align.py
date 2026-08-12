"""Research-only alignment of GST facts onto visual timestamps.

Does not mutate GST. Does not relabel visual observations as Riot/GST facts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from riftlens.domain.enums import FactKind
from riftlens.domain.fact import Fact
from riftlens.domain.timeline import GameStateTimeline
from riftlens.visual.track import CandidateKind, EntityTrack, TrackLifecycle

DEATH_ALIGN_MS = 2_000
EVENT_NEAR_MS = 2_000


@dataclass(frozen=True)
class AlignedKill:
    """A CHAMPION_KILL in the capture GAME window, copied not rewritten."""

    game_t_ms: int
    killer_id: int | None
    victim_id: int | None
    assist_ids: tuple[int, ...]
    subject_role: str | None
    confidence: float
    nearby_track_ids: tuple[str, ...]


@dataclass(frozen=True)
class SubjectGstState:
    participant_id: int
    champion: str | None
    team_id: int | None
    deaths: tuple[int, ...]
    kills: tuple[int, ...]
    assists: tuple[int, ...]


@dataclass(frozen=True)
class GstAlignment:
    """Read-only GST context for a visual window. Parallel to R.11, not inside it."""

    match_id: str
    start_game_ms: int
    end_game_ms: int
    subject: SubjectGstState | None
    kills: tuple[AlignedKill, ...]
    mutated_gst: bool = False


def align_gst(
    gst: GameStateTimeline | None,
    *,
    start_game_ms: int,
    end_game_ms: int,
    subject_pid: int | None,
    tracks: Sequence[EntityTrack] = (),
) -> GstAlignment:
    """List GST kills/deaths in the window and nearby visual track changes."""
    if gst is None:
        return GstAlignment(
            match_id="",
            start_game_ms=start_game_ms,
            end_game_ms=end_game_ms,
            subject=None,
            kills=(),
            mutated_gst=False,
        )
    window = (int(start_game_ms), int(end_game_ms))
    facts = list(gst.facts(kind=FactKind.CHAMPION_KILL, window=window))
    subject = _subject_state(gst, subject_pid, facts) if subject_pid is not None else None
    kills = tuple(
        _align_kill(fact, subject_pid=subject_pid, tracks=tracks) for fact in facts
    )
    return GstAlignment(
        match_id=gst.match_id,
        start_game_ms=start_game_ms,
        end_game_ms=end_game_ms,
        subject=subject,
        kills=kills,
        mutated_gst=False,
    )


def tracks_near_time(
    tracks: Sequence[EntityTrack],
    game_t_ms: int,
    *,
    window_ms: int = EVENT_NEAR_MS,
) -> tuple[EntityTrack, ...]:
    """Tracks whose last/first observation falls near ``game_t_ms``."""
    matched: list[EntityTrack] = []
    for track in tracks:
        if track.kind is CandidateKind.NOISE:
            continue
        if abs(track.last_seen_game_t_ms - game_t_ms) <= window_ms:
            matched.append(track)
            continue
        if abs(track.first_seen_game_t_ms - game_t_ms) <= window_ms:
            matched.append(track)
    return tuple(matched)


def disappearing_near(
    tracks: Sequence[EntityTrack],
    game_t_ms: int,
    *,
    window_ms: int = DEATH_ALIGN_MS,
) -> tuple[EntityTrack, ...]:
    """Champion-like tracks that cease being observed near ``game_t_ms``."""
    out: list[EntityTrack] = []
    for track in tracks:
        if track.kind is not CandidateKind.CHAMPION_LIKE:
            continue
        if track.closed_reason in {TrackLifecycle.LEFT_VIEW, TrackLifecycle.LOST_TRACK, None}:
            if abs(track.last_seen_game_t_ms - game_t_ms) <= window_ms:
                out.append(track)
    return tuple(out)


def _subject_state(
    gst: GameStateTimeline,
    subject_pid: int,
    kills: Sequence[Fact],
) -> SubjectGstState:
    info = gst.participants.get(subject_pid)
    deaths = tuple(
        int(fact.t_ms) for fact in kills if _as_int(fact.payload.get("victimId")) == subject_pid
    )
    got_kills = tuple(
        int(fact.t_ms) for fact in kills if _as_int(fact.payload.get("killerId")) == subject_pid
    )
    assists = tuple(
        int(fact.t_ms)
        for fact in kills
        if subject_pid in _assist_ids(fact) and _as_int(fact.payload.get("killerId")) != subject_pid
    )
    return SubjectGstState(
        participant_id=subject_pid,
        champion=None if info is None else info.champion,
        team_id=None if info is None else int(info.team),
        deaths=deaths,
        kills=got_kills,
        assists=assists,
    )


def _align_kill(
    fact: Fact,
    *,
    subject_pid: int | None,
    tracks: Sequence[EntityTrack],
) -> AlignedKill:
    killer = _as_int(fact.payload.get("killerId"))
    victim = _as_int(fact.payload.get("victimId"))
    assists = _assist_ids(fact)
    role: str | None = None
    if subject_pid is not None:
        if victim == subject_pid:
            role = "victim"
        elif killer == subject_pid:
            role = "killer"
        elif subject_pid in assists:
            role = "assist"
    nearby = tracks_near_time(tracks, fact.t_ms)
    return AlignedKill(
        game_t_ms=int(fact.t_ms),
        killer_id=killer,
        victim_id=victim,
        assist_ids=assists,
        subject_role=role,
        confidence=float(fact.confidence),
        nearby_track_ids=tuple(item.track_id for item in nearby),
    )


def _assist_ids(fact: Fact) -> tuple[int, ...]:
    raw = fact.payload.get("assistingParticipantIds")
    if raw is None:
        raw = fact.payload.get("assists")
    if not isinstance(raw, (list, tuple)):
        return ()
    out: list[int] = []
    for item in raw:
        parsed = _as_int(item)
        if parsed is not None:
            out.append(parsed)
    return tuple(out)


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None
    return int(value)
