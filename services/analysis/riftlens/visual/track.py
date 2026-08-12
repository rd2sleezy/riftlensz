"""Deterministic temporal tracking of champion-like viewport candidates.

A false split is preferred to a confident merge. Crossing tracks become
AMBIGUOUS rather than swapping identity. LEFT_VIEW means the track left the
captured viewport — not that the champion left the fight, died, or fogged.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from riftlens.domain.observation.common import ScreenRect
from riftlens.visual.detect import DetectedBar, ViewportCoverage

MISS_GRACE_FRAMES = 2
LONG_GAP_FRAMES = 8
MATCH_CENTER_PX = 72.0
MATCH_IOU = 0.12
AMBIGUITY_RATIO = 0.82
STATIC_CENTER_STD_PX = 2.5
TEAM_COLOR_CONFIDENCE_CAP = 0.55
MAX_CONFIDENCE_BUMP = 0.06


class TrackLifecycle(StrEnum):
    """Viewport observability of a track. Not a tactical state."""

    ENTERED_VIEW = "ENTERED_VIEW"
    PRESENT = "PRESENT"
    LEFT_VIEW = "LEFT_VIEW"
    LOST_TRACK = "LOST_TRACK"
    AMBIGUOUS = "AMBIGUOUS"


class CandidateKind(StrEnum):
    CHAMPION_LIKE = "CHAMPION_LIKE"
    NOISE = "NOISE"
    UNKNOWN = "UNKNOWN"


class TeamEstimate(StrEnum):
    ALLY = "ALLY"
    ENEMY = "ENEMY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class FrameCandidate:
    """One detection in one sampled frame. Not a champion identity."""

    region: ScreenRect
    confidence: float
    ally_like: bool | None
    kind: CandidateKind = CandidateKind.CHAMPION_LIKE


@dataclass(frozen=True)
class FrameDetections:
    frame_index: int
    game_t_ms: int
    candidates: tuple[FrameCandidate, ...]
    coverage: ViewportCoverage = ViewportCoverage.USEFUL


@dataclass(frozen=True)
class TrackObservation:
    frame_index: int
    game_t_ms: int
    region: ScreenRect
    confidence: float
    lifecycle: TrackLifecycle
    team_estimate: TeamEstimate
    team_confidence: float


@dataclass(frozen=True)
class TrackEvent:
    track_id: str
    game_t_ms: int
    kind: TrackLifecycle


@dataclass(frozen=True)
class EntityTrack:
    """One temporally associated candidate. Identity fields stay unset here."""

    track_id: str
    first_seen_game_t_ms: int
    last_seen_game_t_ms: int
    observations: tuple[TrackObservation, ...]
    confidence: float
    kind: CandidateKind
    team_estimate: TeamEstimate
    team_confidence: float
    events: tuple[TrackEvent, ...]
    ambiguous: bool = False
    fragmented: bool = False
    closed_reason: TrackLifecycle | None = None

    @property
    def observation_count(self) -> int:
        return len(self.observations)


@dataclass
class _LiveTrack:
    track_id: str
    observations: list[TrackObservation] = field(default_factory=list)
    events: list[TrackEvent] = field(default_factory=list)
    confidence: float = 0.0
    misses: int = 0
    ambiguous: bool = False
    fragmented: bool = False
    closed: bool = False
    closed_reason: TrackLifecycle | None = None
    kind: CandidateKind = CandidateKind.CHAMPION_LIKE


def candidates_from_bars(bars: Sequence[DetectedBar]) -> tuple[FrameCandidate, ...]:
    """Lift V.0/V.1 bar detections into tracker candidates."""
    return tuple(
        FrameCandidate(
            region=bar.region,
            confidence=bar.confidence,
            ally_like=bar.ally_like,
            kind=CandidateKind.CHAMPION_LIKE,
        )
        for bar in bars
    )


def team_from_ally_like(ally_like: bool | None, *, confidence: float) -> tuple[TeamEstimate, float]:
    """Conservative team guess from health-bar color. Never a participant id."""
    capped = min(float(confidence), TEAM_COLOR_CONFIDENCE_CAP)
    if ally_like is True:
        return TeamEstimate.ALLY, capped
    if ally_like is False:
        return TeamEstimate.ENEMY, capped
    return TeamEstimate.UNKNOWN, 0.0


def track_candidates(
    frames: Sequence[FrameDetections],
    *,
    miss_grace: int = MISS_GRACE_FRAMES,
    long_gap: int = LONG_GAP_FRAMES,
) -> tuple[EntityTrack, ...]:
    """Associate candidates across sampled frames. Deterministic and greedy."""
    live: list[_LiveTrack] = []
    closed: list[_LiveTrack] = []
    next_id = 1
    for frame in frames:
        if frame.coverage is not ViewportCoverage.USEFUL:
            for item in live:
                item.misses += 1
            _expire_tracks(
                live,
                closed,
                frame=frame,
                miss_grace=miss_grace,
                long_gap=long_gap,
                reason=TrackLifecycle.LOST_TRACK,
            )
            continue
        next_id = _associate_frame(
            live,
            closed,
            frame=frame,
            next_id=next_id,
            miss_grace=miss_grace,
            long_gap=long_gap,
        )
    last_t = frames[-1].game_t_ms if frames else 0
    while live:
        item = live.pop()
        _close_track(item, game_t_ms=last_t, reason=TrackLifecycle.LEFT_VIEW)
        closed.append(item)
    tracks = tuple(_freeze(item) for item in closed)
    return tuple(sorted(tracks, key=lambda item: (item.first_seen_game_t_ms, item.track_id)))


def classify_track_kind(track: EntityTrack) -> CandidateKind:
    """Downgrade static UI / one-off noise after tracking."""
    if track.kind is CandidateKind.NOISE:
        return CandidateKind.NOISE
    if _is_static_ui(track):
        return CandidateKind.NOISE
    if track.observation_count == 1 and track.confidence < 0.45:
        return CandidateKind.UNKNOWN
    if track.observation_count >= 2 or track.confidence >= 0.45:
        return CandidateKind.CHAMPION_LIKE
    return CandidateKind.UNKNOWN


def finalize_tracks(tracks: Sequence[EntityTrack]) -> tuple[EntityTrack, ...]:
    """Apply post-track kind classification without changing track ids."""
    finalized: list[EntityTrack] = []
    for track in tracks:
        kind = classify_track_kind(track)
        finalized.append(
            EntityTrack(
                track_id=track.track_id,
                first_seen_game_t_ms=track.first_seen_game_t_ms,
                last_seen_game_t_ms=track.last_seen_game_t_ms,
                observations=track.observations,
                confidence=track.confidence,
                kind=kind,
                team_estimate=track.team_estimate,
                team_confidence=(
                    track.team_confidence if kind is CandidateKind.CHAMPION_LIKE else 0.0
                ),
                events=track.events,
                ambiguous=track.ambiguous,
                fragmented=track.fragmented,
                closed_reason=track.closed_reason,
            )
        )
    return tuple(finalized)


def stable_track_count(tracks: Sequence[EntityTrack]) -> int:
    return sum(
        1
        for item in tracks
        if (
            item.kind is CandidateKind.CHAMPION_LIKE
            and not item.ambiguous
            and item.observation_count >= 2
        )
    )


def fragmented_track_count(tracks: Sequence[EntityTrack]) -> int:
    return sum(1 for item in tracks if item.fragmented or item.ambiguous)


def derive_timeline_events(tracks: Sequence[EntityTrack]) -> tuple[TrackEvent, ...]:
    """Descriptive viewport entry/exit events. No coaching labels."""
    events = [event for track in tracks for event in track.events]
    return tuple(sorted(events, key=lambda item: (item.game_t_ms, item.track_id, item.kind.value)))


def _associate_frame(
    live: list[_LiveTrack],
    closed: list[_LiveTrack],
    *,
    frame: FrameDetections,
    next_id: int,
    miss_grace: int,
    long_gap: int,
) -> int:
    candidates = list(enumerate(frame.candidates))
    active = [item for item in live if not item.closed]
    scores = _score_matrix(active, [item[1] for item in candidates])
    assigned_tracks, assigned_cands, ambiguous_tracks, ambiguous_cands = _greedy_assign(
        scores, track_count=len(active), cand_count=len(candidates)
    )
    for track_index in sorted(ambiguous_tracks, reverse=True):
        track = active[track_index]
        track.ambiguous = True
        track.fragmented = True
        _close_track(track, game_t_ms=frame.game_t_ms, reason=TrackLifecycle.AMBIGUOUS)
        live.remove(track)
        closed.append(track)
    used_cands = set(assigned_cands) | set(ambiguous_cands)
    for track_index, cand_index in assigned_tracks.items():
        if track_index in ambiguous_tracks:
            continue
        track = active[track_index]
        candidate = candidates[cand_index][1]
        _observe(track, frame=frame, candidate=candidate, first=False)
    for track_index, track in enumerate(active):
        if track_index in assigned_tracks or track_index in ambiguous_tracks:
            continue
        track.misses += 1
        if track.misses == miss_grace + 1:
            track.events.append(
                TrackEvent(
                    track_id=track.track_id,
                    game_t_ms=frame.game_t_ms,
                    kind=TrackLifecycle.LOST_TRACK,
                )
            )
    _expire_tracks(
        live,
        closed,
        frame=frame,
        miss_grace=miss_grace,
        long_gap=long_gap,
        reason=TrackLifecycle.LEFT_VIEW,
    )
    for cand_index, candidate in candidates:
        if cand_index in used_cands:
            continue
        track = _LiveTrack(track_id=f"trk_{next_id:04d}")
        next_id += 1
        if cand_index in ambiguous_cands:
            track.ambiguous = True
            track.fragmented = True
        _observe(track, frame=frame, candidate=candidate, first=True)
        live.append(track)
    return next_id


def _expire_tracks(
    live: list[_LiveTrack],
    closed: list[_LiveTrack],
    *,
    frame: FrameDetections,
    miss_grace: int,
    long_gap: int,
    reason: TrackLifecycle,
) -> None:
    remaining: list[_LiveTrack] = []
    for track in live:
        if track.misses > long_gap:
            _close_track(track, game_t_ms=frame.game_t_ms, reason=reason)
            closed.append(track)
        else:
            remaining.append(track)
    live[:] = remaining


def _observe(
    track: _LiveTrack,
    *,
    frame: FrameDetections,
    candidate: FrameCandidate,
    first: bool,
) -> None:
    team, team_conf = team_from_ally_like(candidate.ally_like, confidence=candidate.confidence)
    lifecycle = TrackLifecycle.ENTERED_VIEW if first else TrackLifecycle.PRESENT
    track.misses = 0
    track.confidence = _update_confidence(
        track.confidence, candidate.confidence, supporting=not first
    )
    observation = TrackObservation(
        frame_index=frame.frame_index,
        game_t_ms=frame.game_t_ms,
        region=candidate.region,
        confidence=candidate.confidence,
        lifecycle=lifecycle,
        team_estimate=team,
        team_confidence=team_conf,
    )
    track.observations.append(observation)
    if first:
        track.events.append(
            TrackEvent(
                track_id=track.track_id,
                game_t_ms=frame.game_t_ms,
                kind=TrackLifecycle.ENTERED_VIEW,
            )
        )
        track.confidence = candidate.confidence
    else:
        track.events.append(
            TrackEvent(
                track_id=track.track_id,
                game_t_ms=frame.game_t_ms,
                kind=TrackLifecycle.PRESENT,
            )
        )


def _close_track(track: _LiveTrack, *, game_t_ms: int, reason: TrackLifecycle) -> None:
    if track.closed:
        return
    track.closed = True
    track.closed_reason = reason
    track.events.append(TrackEvent(track_id=track.track_id, game_t_ms=game_t_ms, kind=reason))


def _freeze(track: _LiveTrack) -> EntityTrack:
    observations = tuple(track.observations)
    team, team_conf = _consensus_team(observations)
    first = observations[0].game_t_ms if observations else 0
    last = observations[-1].game_t_ms if observations else 0
    return EntityTrack(
        track_id=track.track_id,
        first_seen_game_t_ms=first,
        last_seen_game_t_ms=last,
        observations=observations,
        confidence=round(max(0.0, min(1.0, track.confidence)), 3),
        kind=track.kind,
        team_estimate=team,
        team_confidence=team_conf,
        events=tuple(track.events),
        ambiguous=track.ambiguous,
        fragmented=track.fragmented,
        closed_reason=track.closed_reason,
    )


def _consensus_team(observations: tuple[TrackObservation, ...]) -> tuple[TeamEstimate, float]:
    if not observations:
        return TeamEstimate.UNKNOWN, 0.0
    known = [item for item in observations if item.team_estimate is not TeamEstimate.UNKNOWN]
    if not known:
        return TeamEstimate.UNKNOWN, 0.0
    ally = sum(1 for item in known if item.team_estimate is TeamEstimate.ALLY)
    enemy = sum(1 for item in known if item.team_estimate is TeamEstimate.ENEMY)
    if ally and enemy:
        return TeamEstimate.UNKNOWN, 0.0
    estimate = TeamEstimate.ALLY if ally else TeamEstimate.ENEMY
    confidence = min(item.team_confidence for item in known)
    return estimate, round(min(confidence, TEAM_COLOR_CONFIDENCE_CAP), 3)


def _score_matrix(
    tracks: Sequence[_LiveTrack], candidates: Sequence[FrameCandidate]
) -> list[list[float]]:
    matrix: list[list[float]] = []
    for track in tracks:
        last = track.observations[-1]
        row = [_match_score(last, candidate) for candidate in candidates]
        matrix.append(row)
    return matrix


def _match_score(last: TrackObservation, candidate: FrameCandidate) -> float:
    iou = _iou(last.region, candidate.region)
    dist = _center_distance(last.region, candidate.region)
    if dist > MATCH_CENTER_PX and iou < MATCH_IOU:
        return 0.0
    dist_score = max(0.0, 1.0 - dist / MATCH_CENTER_PX)
    score = 0.55 * iou + 0.45 * dist_score
    last_team, _ = last.team_estimate, last.team_confidence
    cand_team, _ = team_from_ally_like(candidate.ally_like, confidence=candidate.confidence)
    if (
        last_team is not TeamEstimate.UNKNOWN
        and cand_team is not TeamEstimate.UNKNOWN
        and last_team != cand_team
    ):
        score *= 0.25
    elif last_team == cand_team and last_team is not TeamEstimate.UNKNOWN:
        score = min(1.0, score + 0.05)
    return score


def _greedy_assign(
    scores: Sequence[Sequence[float]],
    *,
    track_count: int,
    cand_count: int,
) -> tuple[dict[int, int], set[int], set[int], set[int]]:
    """Return (track→cand, assigned cands, ambiguous tracks, ambiguous cands)."""
    pairs: list[tuple[float, int, int]] = []
    for track_index, row in enumerate(scores):
        for cand_index, score in enumerate(row):
            if score > 0.0:
                pairs.append((score, track_index, cand_index))
    pairs.sort(key=lambda item: (-item[0], item[1], item[2]))
    assigned_tracks: dict[int, int] = {}
    assigned_cands: set[int] = set()
    ambiguous_tracks: set[int] = set()
    ambiguous_cands: set[int] = set()
    for track_index in range(track_count):
        ranked = sorted(
            ((scores[track_index][cand_index], cand_index) for cand_index in range(cand_count)),
            reverse=True,
        )
        if len(ranked) >= 2 and ranked[0][0] > 0 and ranked[1][0] >= AMBIGUITY_RATIO * ranked[0][0]:
            ambiguous_tracks.add(track_index)
            if ranked[0][0] > 0:
                ambiguous_cands.add(ranked[1][1])
                ambiguous_cands.add(ranked[0][1])
    for cand_index in range(cand_count):
        ranked = sorted(
            ((scores[track_index][cand_index], track_index) for track_index in range(track_count)),
            reverse=True,
        )
        if len(ranked) >= 2 and ranked[0][0] > 0 and ranked[1][0] >= AMBIGUITY_RATIO * ranked[0][0]:
            ambiguous_tracks.add(ranked[0][1])
            ambiguous_tracks.add(ranked[1][1])
            ambiguous_cands.add(cand_index)
    for _score, track_index, cand_index in pairs:
        if track_index in assigned_tracks or cand_index in assigned_cands:
            continue
        if track_index in ambiguous_tracks or cand_index in ambiguous_cands:
            continue
        assigned_tracks[track_index] = cand_index
        assigned_cands.add(cand_index)
    return assigned_tracks, assigned_cands, ambiguous_tracks, ambiguous_cands


def _update_confidence(previous: float, observed: float, *, supporting: bool) -> float:
    if not supporting:
        return round(max(0.0, min(1.0, observed)), 3)
    if observed >= previous:
        bumped = min(observed, previous + MAX_CONFIDENCE_BUMP)
        return round(min(0.9, max(previous, bumped)), 3)
    return round(0.85 * previous + 0.15 * observed, 3)


def _is_static_ui(track: EntityTrack) -> bool:
    """Treat glued-to-pixel detections in typical HUD bands as noise.

    A champion standing still in mid-viewport is not UI. Only suppress when
    the box never jitters *and* sits in a HUD-like strip.
    """
    if track.observation_count < 3:
        return False
    xs = [item.region.x + item.region.width / 2.0 for item in track.observations]
    ys = [item.region.y + item.region.height / 2.0 for item in track.observations]
    if _std(xs) > STATIC_CENTER_STD_PX or _std(ys) > STATIC_CENTER_STD_PX:
        return False
    y = track.observations[0].region.y
    x = track.observations[0].region.x
    return y <= 48 or x <= 16


def _std(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / float(len(values))
    var = sum((item - mean) ** 2 for item in values) / float(len(values))
    return float(var**0.5)


def _iou(left: ScreenRect, right: ScreenRect) -> float:
    x0 = max(left.x, right.x)
    y0 = max(left.y, right.y)
    x1 = min(left.x + left.width, right.x + right.width)
    y1 = min(left.y + left.height, right.y + right.height)
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = left.width * left.height + right.width * right.height - inter
    if union <= 0:
        return 0.0
    return float(inter) / float(union)


def _center_distance(left: ScreenRect, right: ScreenRect) -> float:
    lx = left.x + left.width / 2.0
    ly = left.y + left.height / 2.0
    rx = right.x + right.width / 2.0
    ry = right.y + right.height / 2.0
    return float(((lx - rx) ** 2 + (ly - ry) ** 2) ** 0.5)
