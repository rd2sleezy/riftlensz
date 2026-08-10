from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

MIN_ANCHORS = 3
MAX_STDEV_MS = 750.0
MAX_RESIDUAL_MS = 750.0
OUTLIER_ABS_MS = 750.0

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_WS = re.compile(r"\s+")

# Official Riot id / display dual forms. Not fuzzy similarity.
_CHAMPION_ALIASES: dict[str, str] = {
    "wukong": "monkeyking",
    "monkeyking": "monkeyking",
}


def normalize_identity_token(value: str | None, *, kind: str = "champion") -> str | None:
    """Return a canonical token. Champions drop punctuation; names keep letters/digits."""
    if value is None:
        return None
    text = value.strip().casefold()
    if not text:
        return None
    if kind == "champion":
        text = _NON_ALNUM.sub("", text)
        if not text:
            return None
        return _CHAMPION_ALIASES.get(text, text)
    text = _WS.sub("", text)
    return text or None


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
        killer_c = normalize_identity_token(self.killer_champion, kind="champion")
        victim_c = normalize_identity_token(self.victim_champion, kind="champion")
        if killer_c and victim_c:
            return (f"champ:{killer_c}", f"champ:{victim_c}")
        killer_n = normalize_identity_token(self.killer_name, kind="name")
        victim_n = normalize_identity_token(self.victim_name, kind="name")
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
    riot_count: int = 0
    lcd_count: int = 0
    unmatched_riot: int = 0
    unmatched_lcd: int = 0

    @property
    def anchor_count(self) -> int:
        return len(self.anchors)


def match_kill_anchors(
    riot_kills: Sequence[KillEvent],
    lcd_kills: Sequence[KillEvent],
) -> AnchorMatchResult:
    """Match champion kills by identity, then temporally consistent assignment."""
    riot = list(riot_kills)
    lcd = list(lcd_kills)
    rejected: list[RejectedCandidate] = []
    if not riot or not lcd:
        return _fail("insufficient_events", (), tuple(rejected), len(riot), len(lcd))

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
            return _fail(
                "ambiguous",
                tuple(),
                tuple(rejected),
                len(riot),
                len(lcd),
                unmatched_riot=sum(1 for item in rejected if item.side == "riot"),
                unmatched_lcd=sum(1 for item in rejected if item.side == "lcd"),
            )
    else:
        pairs, leftover_riot, leftover_lcd = _match_by_ordinal(
            list(range(len(riot))), list(range(len(lcd))), rejected
        )
    for idx in leftover_riot:
        rejected.append(RejectedCandidate(side="riot", index=idx, reason="unmatched"))
    for idx in leftover_lcd:
        rejected.append(RejectedCandidate(side="lcd", index=idx, reason="unmatched"))

    unmatched_riot = sum(1 for item in rejected if item.side == "riot")
    unmatched_lcd = sum(1 for item in rejected if item.side == "lcd")
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
        return _fail(
            "insufficient_anchors",
            tuple(anchors),
            tuple(rejected),
            len(riot),
            len(lcd),
            unmatched_riot=unmatched_riot,
            unmatched_lcd=unmatched_lcd,
        )

    inliers, offset, residual, stdev = _best_inlier_set(anchors)
    if offset is None or residual is None or stdev is None:
        return _fail(
            "insufficient_inliers",
            tuple(anchors),
            tuple(rejected),
            len(riot),
            len(lcd),
            unmatched_riot=unmatched_riot,
            unmatched_lcd=unmatched_lcd,
        )
    accepted = stdev <= MAX_STDEV_MS and residual <= MAX_RESIDUAL_MS
    return AnchorMatchResult(
        accepted=accepted,
        reason="ok" if accepted else "residual_too_high",
        anchors=tuple(inliers),
        rejected=tuple(rejected),
        offset_ms=offset,
        residual_ms=residual,
        stdev_ms=stdev,
        inlier_count=len(inliers),
        riot_count=len(riot),
        lcd_count=len(lcd),
        unmatched_riot=unmatched_riot,
        unmatched_lcd=unmatched_lcd,
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
    riot_groups: dict[tuple[str, str], list[int]] = {}
    lcd_groups: dict[tuple[str, str], list[int]] = {}
    unidentified_riot: list[int] = []
    unidentified_lcd: list[int] = []
    for idx, event in enumerate(riot):
        key = event.identity_key()
        if key is None:
            unidentified_riot.append(idx)
            continue
        riot_groups.setdefault(key, []).append(idx)
    for idx, event in enumerate(lcd):
        key = event.identity_key()
        if key is None:
            unidentified_lcd.append(idx)
            continue
        lcd_groups.setdefault(key, []).append(idx)

    shared = sorted(set(riot_groups) & set(lcd_groups))
    pairs: list[tuple[int, int, str, tuple[str, str] | None]] = []
    used_riot: set[int] = set()
    used_lcd: set[int] = set()

    one_to_one_offsets: list[int] = []
    for key in shared:
        r_idxs = riot_groups[key]
        l_idxs = lcd_groups[key]
        if len(r_idxs) == 1 and len(l_idxs) == 1:
            ri, li = r_idxs[0], l_idxs[0]
            pairs.append((ri, li, "identity", key))
            used_riot.add(ri)
            used_lcd.add(li)
            one_to_one_offsets.append(int(riot[ri].t_ms) - int(lcd[li].t_ms))

    offset_hat = _median_int(one_to_one_offsets) if one_to_one_offsets else _consensus_offset(
        riot, lcd, riot_groups, lcd_groups, used_riot, used_lcd
    )

    remaining_lcd = sorted(
        (idx for key in shared for idx in lcd_groups[key] if idx not in used_lcd),
        key=lambda idx: (lcd[idx].t_ms, idx),
    )
    for li in remaining_lcd:
        key = lcd[li].identity_key()
        if key is None:
            continue
        candidates = [ri for ri in riot_groups[key] if ri not in used_riot]
        if not candidates:
            rejected.append(RejectedCandidate(side="lcd", index=li, reason="no_identity_peer"))
            used_lcd.add(li)
            continue
        if offset_hat is None:
            rejected.append(RejectedCandidate(side="lcd", index=li, reason="no_identity_peer"))
            used_lcd.add(li)
            continue
        ri = min(
            candidates,
            key=lambda idx: (
                abs((int(riot[idx].t_ms) - int(lcd[li].t_ms)) - offset_hat),
                int(riot[idx].t_ms),
                idx,
            ),
        )
        pairs.append((ri, li, "identity", key))
        used_riot.add(ri)
        used_lcd.add(li)

    for key in shared:
        for ri in riot_groups[key]:
            if ri not in used_riot:
                rejected.append(RejectedCandidate(side="riot", index=ri, reason="no_identity_peer"))
    for key, idxs in lcd_groups.items():
        if key in shared:
            continue
        for li in idxs:
            rejected.append(RejectedCandidate(side="lcd", index=li, reason="no_identity_peer"))
    for key, idxs in riot_groups.items():
        if key in shared:
            continue
        for ri in idxs:
            rejected.append(RejectedCandidate(side="riot", index=ri, reason="no_identity_peer"))

    leftover_riot = [idx for idx in unidentified_riot if idx not in used_riot]
    leftover_lcd = [idx for idx in unidentified_lcd if idx not in used_lcd]
    leftover_riot.sort()
    leftover_lcd.sort()
    return pairs, leftover_riot, leftover_lcd


def _consensus_offset(
    riot: Sequence[KillEvent],
    lcd: Sequence[KillEvent],
    riot_groups: dict[tuple[str, str], list[int]],
    lcd_groups: dict[tuple[str, str], list[int]],
    used_riot: set[int],
    used_lcd: set[int],
) -> int | None:
    seeds: list[int] = []
    shared = set(riot_groups) & set(lcd_groups)
    for key in shared:
        for ri in riot_groups[key]:
            if ri in used_riot:
                continue
            for li in lcd_groups[key]:
                if li in used_lcd:
                    continue
                seeds.append(int(riot[ri].t_ms) - int(lcd[li].t_ms))
    if not seeds:
        return None
    best_o: int | None = None
    best_score = -1
    for offset in sorted(set(seeds)):
        score = _score_offset(
            offset, riot, lcd, riot_groups, lcd_groups, used_riot, used_lcd
        )
        if score > best_score:
            best_o, best_score = offset, score
            continue
        if score == best_score and best_o is not None:
            if abs(offset) < abs(best_o) or (abs(offset) == abs(best_o) and offset < best_o):
                best_o = offset
    if best_o is None or best_score < 1:
        return None
    return best_o


def _score_offset(
    offset: int,
    riot: Sequence[KillEvent],
    lcd: Sequence[KillEvent],
    riot_groups: dict[tuple[str, str], list[int]],
    lcd_groups: dict[tuple[str, str], list[int]],
    used_riot: set[int],
    used_lcd: set[int],
) -> int:
    taken = set(used_riot)
    score = 0
    lcd_order = sorted(
        (
            idx
            for key in set(riot_groups) & set(lcd_groups)
            for idx in lcd_groups[key]
            if idx not in used_lcd
        ),
        key=lambda idx: (lcd[idx].t_ms, idx),
    )
    for li in lcd_order:
        key = lcd[li].identity_key()
        if key is None:
            continue
        candidates = [
            ri
            for ri in riot_groups[key]
            if ri not in taken
            and abs((int(riot[ri].t_ms) - int(lcd[li].t_ms)) - offset) <= MAX_RESIDUAL_MS
        ]
        if not candidates:
            continue
        ri = min(
            candidates,
            key=lambda idx: (
                abs((int(riot[idx].t_ms) - int(lcd[li].t_ms)) - offset),
                int(riot[idx].t_ms),
                idx,
            ),
        )
        taken.add(ri)
        score += 1
    return score


def _match_by_ordinal(
    riot_idxs: Sequence[int],
    lcd_idxs: Sequence[int],
    rejected: list[RejectedCandidate],
) -> tuple[list[tuple[int, int, str, tuple[str, str] | None]], list[int], list[int]]:
    n = min(len(riot_idxs), len(lcd_idxs))
    pairs: list[tuple[int, int, str, tuple[str, str] | None]] = [
        (riot_idxs[i], lcd_idxs[i], "ordinal", None) for i in range(n)
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


def _fail(
    reason: str,
    anchors: tuple[MatchedAnchor, ...],
    rejected: tuple[RejectedCandidate, ...],
    riot_count: int = 0,
    lcd_count: int = 0,
    *,
    unmatched_riot: int = 0,
    unmatched_lcd: int = 0,
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
        riot_count=riot_count,
        lcd_count=lcd_count,
        unmatched_riot=unmatched_riot,
        unmatched_lcd=unmatched_lcd,
    )
