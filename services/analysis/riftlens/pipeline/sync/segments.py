"""Pause, cut, and multi-game segmentation for H.10. Slope is not fitted here."""

from __future__ import annotations

from collections.abc import Sequence

from riftlens.domain.sync_map import PauseInterval
from riftlens.pipeline.sync.errors import MultipleGamesDetected
from riftlens.pipeline.sync.filter import AcceptedPoint

PAUSE_MIN_OBSERVATIONS = 3
CUT_OFFSET_JUMP_MS = 2_000
GAME_RESET_DROP_MS = 5 * 60 * 1000
NEW_GAME_CEILING_MS = 3 * 60 * 1000
RESET_CONFIRM_POINTS = 3


def detect_pauses(
    points: Sequence[AcceptedPoint],
    *,
    min_observations: int = PAUSE_MIN_OBSERVATIONS,
) -> tuple[PauseInterval, ...]:
    """Return pauses where game time is frozen while video advances."""
    if not points:
        return ()
    pauses: list[PauseInterval] = []
    run_game = points[0].t_game_ms
    run_start = points[0].t_video_ms
    run_end = points[0].t_video_ms
    run_count = 1
    for point in points[1:]:
        if point.t_game_ms == run_game:
            run_end = point.t_video_ms
            run_count += 1
            continue
        _maybe_append_pause(pauses, run_start, run_end, run_game, run_count, min_observations)
        run_game = point.t_game_ms
        run_start = point.t_video_ms
        run_end = point.t_video_ms
        run_count = 1
    _maybe_append_pause(pauses, run_start, run_end, run_game, run_count, min_observations)
    return tuple(pauses)


def points_outside_pauses(
    points: Sequence[AcceptedPoint],
    pauses: Sequence[PauseInterval],
) -> list[AcceptedPoint]:
    """Return points whose video time is not inside a detected pause interval."""
    if not pauses:
        return list(points)
    kept: list[AcceptedPoint] = []
    for point in points:
        if any(_in_pause(point.t_video_ms, pause) for pause in pauses):
            continue
        kept.append(point)
    return kept


def detect_multiple_games(points: Sequence[AcceptedPoint]) -> None:
    """Raise ``MultipleGamesDetected`` when the stream resets to a new match clock."""
    if len(points) < RESET_CONFIRM_POINTS * 2:
        return
    max_game = points[0].t_game_ms
    index = 1
    while index < len(points):
        point = points[index]
        if point.t_game_ms > max_game:
            max_game = point.t_game_ms
        drop = max_game - point.t_game_ms
        if drop >= GAME_RESET_DROP_MS and point.t_game_ms <= NEW_GAME_CEILING_MS:
            if _confirmed_reset(points, index):
                raise MultipleGamesDetected(
                    "Video contains footage from more than one League game.",
                    boundaries_video_ms=(point.t_video_ms,),
                    details={"max_game_ms_before_reset": max_game},
                )
        index += 1


def split_linear_groups(
    points: Sequence[AcceptedPoint],
    *,
    jump_ms: int = CUT_OFFSET_JUMP_MS,
    confirm: int = 3,
) -> list[list[AcceptedPoint]]:
    """Split by sustained offset discontinuities. Isolated outliers stay in-group for RANSAC."""
    if not points:
        return []
    groups: list[list[AcceptedPoint]] = [[points[0]]]
    current_offsets = [points[0].t_game_ms - points[0].t_video_ms]
    pending: list[AcceptedPoint] = []
    for point in points[1:]:
        offset = point.t_game_ms - point.t_video_ms
        median = _median_int(current_offsets[-20:])
        if abs(offset - median) <= jump_ms:
            if pending:
                groups[-1].extend(pending)
                pending = []
            groups[-1].append(point)
            current_offsets.append(offset)
            continue
        pending.append(point)
        if len(pending) < confirm:
            continue
        pending_offsets = [item.t_game_ms - item.t_video_ms for item in pending]
        if abs(_median_int(pending_offsets) - median) > jump_ms:
            groups.append(list(pending))
            current_offsets = list(pending_offsets)
            pending = []
    if pending:
        groups[-1].extend(pending)
    return groups


def overlapping_game_boundary(
    groups: Sequence[Sequence[AcceptedPoint]],
) -> int | None:
    """Return a video-ms boundary when two groups cover overlapping game times."""
    spans: list[tuple[int, int, int]] = []
    for group in groups:
        if not group:
            continue
        games = [item.t_game_ms for item in group]
        spans.append((min(games), max(games), group[0].t_video_ms))
    spans.sort(key=lambda item: item[2])
    last_end = -1
    for start, end, video_start in spans:
        if start < last_end:
            return video_start
        last_end = max(last_end, end)
    return None


def _maybe_append_pause(
    pauses: list[PauseInterval],
    start: int,
    end: int,
    t_game_ms: int,
    count: int,
    min_observations: int,
) -> None:
    if count >= min_observations and end > start:
        pauses.append(
            PauseInterval(video_start_ms=start, video_end_ms=end, t_game_ms=t_game_ms)
        )


def _in_pause(t_video_ms: int, pause: PauseInterval) -> bool:
    return pause.video_start_ms <= t_video_ms <= pause.video_end_ms


def _confirmed_reset(points: Sequence[AcceptedPoint], index: int) -> bool:
    end = min(len(points), index + RESET_CONFIRM_POINTS)
    window = points[index:end]
    if len(window) < RESET_CONFIRM_POINTS:
        return False
    return all(item.t_game_ms <= NEW_GAME_CEILING_MS for item in window)


def _median_int(values: Sequence[int]) -> int:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return int(round((ordered[mid - 1] + ordered[mid]) / 2.0))
