from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

MIN_ANCHORS = 3
MAX_STDEV_MS = 750.0
MAX_RESIDUAL_MS = 750.0
OUTLIER_ABS_MS = 750.0


@dataclass(frozen=True)
class KillEvent:
    """One champion-kill observation. Times are integer milliseconds in that side's clock."""

    t_ms: int
    killer_champion: str | None = None
    victim_champion: str | None = None
    killer_name: str | None = None
    victim_name: str | None = None

    def identity_key(self) -> tuple[str, str] | None:
        """Return a structural match key. Time is never part of the key."""
        killer_c = _norm(self.killer_champion)
        victim_c = _norm(self.victim_champion)
        if killer_c and victim_c:
            return (f"champ:{killer_c}", f"champ:{victim_c}")
        killer_n = _norm(self.killer_name)
        victim_n = _norm(self.victim_name)
        if killer_n and victim_n:
            return (f"name:{killer_n}", f"name:{victim_n}")
        return None


@dataclass(frozen=True)
class MatchedAnchor:
    """One accepted riot↔LCD kill pair. ``offset_ms = game_t_ms - source_ms``."""

    riot_index: int
    lcd_index: int
    game_t_ms: int
    source_ms: int
    offset_ms: int
    identity_key: tuple[str, str] | None
    method: str


@dataclass(frozen=True)
class RejectedCandidate:
    """A kill that could not be paired, or a pair rejected as ambiguous."""

    side: str
    index: int
    reason: str


@dataclass(frozen=True)
class AnchorMatchResult:
    """Pure matcher output. ``accepted`` is True only when the §5.2 gate passes."""

    accepted: bool
    reason: str
    anchors: tuple[MatchedAnchor, ...]
    rejected: tuple[RejectedCandidate, ...]
    offset_ms: int | None
    residual_ms: float | None
    stdev_ms: float | None
    inlier_count: int

    @property
    def anchor_count(self) -> int:
        return len(self.anchors)


def match_kill_anchors(
    riot_kills: Sequence[KillEvent],
    lcd_kills: Sequence[KillEvent],
) -> AnchorMatchResult:
    """Match champion kills by identity then ordinal. Never uses offset as the match key."""
    riot = list(riot_kills)
    lcd = list(lcd_kills)
    rejected: list[RejectedCandidate] = []
    if not riot or not lcd:
        return _fail("insufficient_events", (), tuple(rejected))

    identified = _enough_identity(riot, lcd)
    pairs: list[tuple[int, int, str, tuple[str, str] | None]]
    if identified:
        pairs, leftover_riot, leftover_lcd = _match_by_identity(riot, lcd, rejected)
        extra, extra_r, extra_l = _match_by_ordinal(leftover_riot, leftover_lcd, rejected)
        pairs.extend(extra)
        leftover_riot, leftover_lcd = extra_r, extra_l
        if len(pairs) < MIN_ANCHORS and any(
            item.reason == "no_identity_peer" for item in rejected
        ):
            return _fail("ambiguous", tuple(), tuple(rejected))
    else:
        pairs, leftover_riot, leftover_lcd = _match_by_ordinal(
            list(range(len(riot))), list(range(len(lcd))), rejected
        )
    for idx in leftover_riot:
        rejected.append(RejectedCandidate(side="riot", index=idx, reason="unmatched"))
    for idx in leftover_lcd:
        rejected.append(RejectedCandidate(side="lcd", index=idx, reason="unmatched"))

    anchors = [
        MatchedAnchor(
            riot_index=ri,
            lcd_index=li,
            game_t_ms=riot[ri].t_ms,
            source_ms=lcd[li].t_ms,
            offset_ms=int(riot[ri].t_ms) - int(lcd[li].t_ms),
            identity_key=key,
            method=method,
        )
        for ri, li, method, key in pairs
    ]
    if len(anchors) < MIN_ANCHORS:
        return _fail("insufficient_anchors", tuple(anchors), tuple(rejected))

    inliers, offset, residual, stdev = _best_inlier_set(anchors)
    if offset is None or residual is None or stdev is None:
        return _fail("insufficient_inliers", tuple(anchors), tuple(rejected))
    if stdev > MAX_STDEV_MS or residual > MAX_RESIDUAL_MS:
        return AnchorMatchResult(
            accepted=False,
            reason="residual_too_high",
            anchors=tuple(inliers),
            rejected=tuple(rejected),
            offset_ms=offset,
            residual_ms=residual,
            stdev_ms=stdev,
            inlier_count=len(inliers),
        )
    return AnchorMatchResult(
        accepted=True,
        reason="ok",
        anchors=tuple(inliers),
        rejected=tuple(rejected),
        offset_ms=offset,
        residual_ms=residual,
        stdev_ms=stdev,
        inlier_count=len(inliers),
    )


def _enough_identity(riot: Sequence[KillEvent], lcd: Sequence[KillEvent]) -> bool:
    riot_ids = sum(1 for item in riot if item.identity_key() is not None)
    lcd_ids = sum(1 for item in lcd if item.identity_key() is not None)
    return riot_ids >= MIN_ANCHORS and lcd_ids >= MIN_ANCHORS


def _match_by_identity(
    riot: Sequence[KillEvent],
    lcd: Sequence[KillEvent],
    rejected: list[RejectedCandidate],
) -> tuple[list[tuple[int, int, str, tuple[str, str] | None]], list[int], list[int]]:
    lcd_buckets: dict[tuple[str, str], list[int]] = {}
    unidentified_lcd: list[int] = []
    for idx, event in enumerate(lcd):
        key = event.identity_key()
        if key is None:
            unidentified_lcd.append(idx)
            continue
        lcd_buckets.setdefault(key, []).append(idx)
    pairs: list[tuple[int, int, str, tuple[str, str] | None]] = []
    unidentified_riot: list[int] = []
    for idx, event in enumerate(riot):
        key = event.identity_key()
        if key is None:
            unidentified_riot.append(idx)
            continue
        bucket = lcd_buckets.get(key)
        if not bucket:
            rejected.append(
                RejectedCandidate(side="riot", index=idx, reason="no_identity_peer")
            )
            continue
        lcd_idx = bucket.pop(0)
        pairs.append((idx, lcd_idx, "identity", key))
    leftover_identified_lcd = [idx for bucket in lcd_buckets.values() for idx in bucket]
    for idx in leftover_identified_lcd:
        rejected.append(RejectedCandidate(side="lcd", index=idx, reason="no_identity_peer"))
    leftover_lcd = list(unidentified_lcd)
    leftover_lcd.sort()
    return pairs, unidentified_riot, leftover_lcd


def _match_by_ordinal(
    riot_idxs: Sequence[int],
    lcd_idxs: Sequence[int],
    rejected: list[RejectedCandidate],
) -> tuple[list[tuple[int, int, str, tuple[str, str] | None]], list[int], list[int]]:
    n = min(len(riot_idxs), len(lcd_idxs))
    pairs: list[tuple[int, int, str, tuple[str, str] | None]] = [
        (riot_idxs[i], lcd_idxs[i], "ordinal", None)
        for i in range(n)
    ]
    if len(riot_idxs) != len(lcd_idxs) and n > 0:
        rejected.append(
            RejectedCandidate(
                side="both",
                index=n,
                reason="ordinal_length_mismatch",
            )
        )
    return pairs, list(riot_idxs[n:]), list(lcd_idxs[n:])


def _best_inlier_set(
    anchors: Sequence[MatchedAnchor],
) -> tuple[list[MatchedAnchor], int | None, float | None, float | None]:
    remaining = list(anchors)
    last_stats: tuple[list[MatchedAnchor], int, float, float] | None = None
    while len(remaining) >= MIN_ANCHORS:
        offset, residual, stdev = _offset_stats(remaining)
        last_stats = (list(remaining), offset, residual, stdev)
        if stdev <= MAX_STDEV_MS and residual <= MAX_RESIDUAL_MS:
            return remaining, offset, residual, stdev
        farthest = max(remaining, key=lambda item: abs(item.offset_ms - offset))
        if abs(farthest.offset_ms - offset) <= OUTLIER_ABS_MS:
            break
        remaining.remove(farthest)
    if last_stats is None:
        return list(anchors), None, None, None
    return last_stats


def _offset_stats(anchors: Sequence[MatchedAnchor]) -> tuple[int, float, float]:
    offsets = [item.offset_ms for item in anchors]
    offset = _median_int(offsets)
    residual = float(max(abs(item - offset) for item in offsets))
    return offset, residual, _stdev(offsets)


def _median_int(values: Sequence[int]) -> int:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return int(round((ordered[mid - 1] + ordered[mid]) / 2.0))


def _stdev(values: Sequence[int]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((item - mean) ** 2 for item in values) / (len(values) - 1)
    return math.sqrt(var)


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip().lower()
    return text or None


def _fail(
    reason: str,
    anchors: tuple[MatchedAnchor, ...],
    rejected: tuple[RejectedCandidate, ...],
) -> AnchorMatchResult:
    return AnchorMatchResult(
        accepted=False,
        reason=reason,
        anchors=anchors,
        rejected=rejected,
        offset_ms=None,
        residual_ms=None,
        stdev_ms=None,
        inlier_count=len(anchors),
    )
