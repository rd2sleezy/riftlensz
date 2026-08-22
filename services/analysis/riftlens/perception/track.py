"""Conservative short-window visual tracking for RP.1 candidates."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from riftlens.domain.observation.common import ScreenRect
from riftlens.perception.models import (
    BarCandidate,
    CandidateKind,
    TeamClass,
    TrackState,
    VisualTrack,
)

MATCH_CENTER_PX = 48.0
AMBIGUITY_RATIO = 0.85


@dataclass
class _Live:
    track_id: str
    kind: CandidateKind
    team_class: TeamClass
    first_ms: int
    last_ms: int
    count: int
    confidence: float
    last_region: ScreenRect
    ambiguous: bool = False
    state: TrackState = TrackState.ACTIVE


@dataclass
class _Assoc:
    lives: list[_Live] = field(default_factory=list)
    next_id: int = 1


def track_candidates_across_frames(
    frames: Sequence[tuple[int, tuple[BarCandidate, ...]]],
) -> tuple[VisualTrack, ...]:
    """Associate candidates across adjacent frames. Prefer split over merge.

    ``frames`` is (game_t_ms, candidates). Track IDs are local visual IDs only —
    never participant identities.
    """
    assoc = _Assoc()
    closed: list[_Live] = []
    for game_t_ms, candidates in frames:
        _associate_frame(assoc, closed, game_t_ms=game_t_ms, candidates=candidates)
    closed.extend(assoc.lives)
    return tuple(_to_track(item) for item in closed)


def _associate_frame(
    assoc: _Assoc,
    closed: list[_Live],
    *,
    game_t_ms: int,
    candidates: tuple[BarCandidate, ...],
) -> None:
    unused = list(assoc.lives)
    assoc.lives = []
    for candidate in candidates:
        matches = sorted(
            (
                (dist, live)
                for live in unused
                if live.kind is candidate.kind
                and (dist := _center_dist(live.last_region, candidate.region))
                <= MATCH_CENTER_PX
            ),
            key=lambda item: item[0],
        )
        if not matches:
            assoc.lives.append(
                _Live(
                    track_id=f"trk_vis_{assoc.next_id:04d}",
                    kind=candidate.kind,
                    team_class=candidate.team_class,
                    first_ms=game_t_ms,
                    last_ms=game_t_ms,
                    count=1,
                    confidence=candidate.confidence,
                    last_region=candidate.region,
                )
            )
            assoc.next_id += 1
            continue
        best_dist, best = matches[0]
        if len(matches) >= 2 and matches[1][0] <= best_dist / AMBIGUITY_RATIO:
            # Ambiguous: close best as AMBIGUOUS and start a new track.
            best.state = TrackState.AMBIGUOUS
            best.ambiguous = True
            unused.remove(best)
            closed.append(best)
            assoc.lives.append(
                _Live(
                    track_id=f"trk_vis_{assoc.next_id:04d}",
                    kind=candidate.kind,
                    team_class=candidate.team_class,
                    first_ms=game_t_ms,
                    last_ms=game_t_ms,
                    count=1,
                    confidence=candidate.confidence,
                    last_region=candidate.region,
                    ambiguous=True,
                    state=TrackState.AMBIGUOUS,
                )
            )
            assoc.next_id += 1
            continue
        unused.remove(best)
        best.last_ms = game_t_ms
        best.count += 1
        best.confidence = max(best.confidence, candidate.confidence)
        best.last_region = candidate.region
        if best.team_class is TeamClass.UNKNOWN:
            best.team_class = candidate.team_class
        assoc.lives.append(best)
    for leftover in unused:
        leftover.state = TrackState.LOST
        closed.append(leftover)


def _center_dist(left: ScreenRect, right: ScreenRect) -> float:
    lx = left.x + left.width / 2.0
    ly = left.y + left.height / 2.0
    rx = right.x + right.width / 2.0
    ry = right.y + right.height / 2.0
    return float(((lx - rx) ** 2 + (ly - ry) ** 2) ** 0.5)


def _to_track(live: _Live) -> VisualTrack:
    return VisualTrack(
        track_id=live.track_id,
        kind=live.kind,
        state=live.state,
        first_game_t_ms=live.first_ms,
        last_game_t_ms=live.last_ms,
        observation_count=live.count,
        confidence=round(live.confidence, 3),
        team_class=live.team_class,
        notes="local visual track; participant_id unset",
    )
