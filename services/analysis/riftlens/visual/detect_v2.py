"""V.2 hybrid champion-like detector. Classical, local, no learned weights.

Pipeline: HUD mask → V.0 health-bar proposals → cluster stacked bars →
expand to a champion-like body box → temporal confirmation across samples.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from riftlens.domain.observation.common import ScreenRect
from riftlens.visual.detect import (
    MAX_PLAUSIBLE_CHAMPIONS,
    DetectedBar,
    ViewportCoverage,
    classify_viewport,
    detect_champion_like_bars,
)
from riftlens.visual.hud_mask import (
    RgbImage,
    apply_hud_mask,
    center_in_hud,
    clamp_rect,
    union_rects,
)
from riftlens.visual.track import CandidateKind, FrameCandidate, FrameDetections

DETECTOR_SOURCE = "v2.hybrid"
STANDALONE_CONFIDENCE = 0.72
NEIGHBOR_CENTER_PX = 80.0
CLUSTER_X_PX = 28.0
CLUSTER_Y_PX = 18.0
BODY_HEIGHT_FACTOR = 2.2
BODY_MAX_HEIGHT = 96
BODY_MIN_HEIGHT = 28


@dataclass(frozen=True)
class DetectedEntity:
    """One champion-like entity proposal. Not a champion or participant id."""

    region: ScreenRect
    bar_region: ScreenRect
    confidence: float
    ally_like: bool | None
    source: str = DETECTOR_SOURCE


def detect_champion_like_entities(pixels: RgbImage) -> tuple[DetectedEntity, ...]:
    """Detect champion-like entities in one frame. Empty means undetected, not absent."""
    if pixels.ndim != 3 or pixels.shape[2] != 3:
        return ()
    height, width = int(pixels.shape[0]), int(pixels.shape[1])
    if height < 16 or width < 16:
        return ()
    masked = apply_hud_mask(pixels)
    bars = detect_champion_like_bars(masked)
    gameplay = tuple(
        bar
        for bar in bars
        if not center_in_hud(bar.region, width=width, height=height)
        and _plausible_champion_bar(bar, frame_width=width)
    )
    if len(gameplay) > MAX_PLAUSIBLE_CHAMPIONS:
        return ()
    clustered = _cluster_bars(gameplay)
    entities = tuple(
        _entity_from_cluster(group, width=width, height=height) for group in clustered
    )
    return tuple(item for item in entities if item is not None)


def candidates_from_entities(entities: Sequence[DetectedEntity]) -> tuple[FrameCandidate, ...]:
    """Lift V.2 entities into V.1 tracker candidates."""
    return tuple(
        FrameCandidate(
            region=item.region,
            confidence=item.confidence,
            ally_like=item.ally_like,
            kind=CandidateKind.CHAMPION_LIKE,
        )
        for item in entities
    )


def detect_sample_entities(
    pixels: RgbImage,
    *,
    frame_index: int,
    game_t_ms: int,
) -> FrameDetections:
    """One-frame V.2 detection with viewport coverage. No temporal confirmation yet."""
    coverage = classify_viewport(pixels)
    if coverage is not ViewportCoverage.USEFUL:
        return FrameDetections(
            frame_index=frame_index,
            game_t_ms=game_t_ms,
            candidates=(),
            coverage=coverage,
        )
    entities = detect_champion_like_entities(pixels)
    return FrameDetections(
        frame_index=frame_index,
        game_t_ms=game_t_ms,
        candidates=candidates_from_entities(entities),
        coverage=coverage,
    )


def confirm_temporal(
    frames: Sequence[FrameDetections],
    *,
    neighbor_px: float = NEIGHBOR_CENTER_PX,
    standalone: float = STANDALONE_CONFIDENCE,
) -> tuple[FrameDetections, ...]:
    """Drop one-frame flashes unless confidence is strong enough to stand alone.

    A candidate is kept when it matches a neighbor in an adjacent sample or
    its confidence is >= ``standalone``. True entries spanning >=2 samples
    are preserved.
    """
    confirmed: list[FrameDetections] = []
    for index, frame in enumerate(frames):
        if frame.coverage is not ViewportCoverage.USEFUL:
            confirmed.append(frame)
            continue
        kept: list[FrameCandidate] = []
        for candidate in frame.candidates:
            if candidate.confidence >= standalone:
                kept.append(candidate)
                continue
            if _has_nearby(candidate, frames, index, neighbor_px, radius=2):
                kept.append(candidate)
                continue
        confirmed.append(
            FrameDetections(
                frame_index=frame.frame_index,
                game_t_ms=frame.game_t_ms,
                candidates=tuple(kept),
                coverage=frame.coverage,
            )
        )
    return tuple(confirmed)


def _plausible_champion_bar(bar: DetectedBar, *, frame_width: int) -> bool:
    """Reject short/thick bars that are usually minion or FX fragments.

    Real champion bars on a 1904x992 replay capture are ~104x9–10. Edge chrome
    and minion fragments are typically 24–28 px wide.
    """
    region = bar.region
    min_width = max(28, int(round(frame_width * 0.035)))
    if region.width < min_width or region.height > 12:
        return False
    aspect = region.width / float(max(region.height, 1))
    return 5.5 <= aspect <= 14.0


def _cluster_bars(bars: Sequence[DetectedBar]) -> tuple[tuple[DetectedBar, ...], ...]:
    remaining = list(bars)
    clusters: list[tuple[DetectedBar, ...]] = []
    while remaining:
        seed = remaining.pop(0)
        group = [seed]
        changed = True
        while changed:
            changed = False
            leftover: list[DetectedBar] = []
            for bar in remaining:
                if any(_same_entity(bar, member) for member in group):
                    group.append(bar)
                    changed = True
                else:
                    leftover.append(bar)
            remaining = leftover
        clusters.append(tuple(group))
    return tuple(clusters)


def _same_entity(left: DetectedBar, right: DetectedBar) -> bool:
    lx = left.region.x + left.region.width / 2.0
    rx = right.region.x + right.region.width / 2.0
    ly = left.region.y + left.region.height / 2.0
    ry = right.region.y + right.region.height / 2.0
    if abs(lx - rx) <= CLUSTER_X_PX and abs(ly - ry) <= CLUSTER_Y_PX:
        return True
    return _iou(left.region, right.region) >= 0.25


def _entity_from_cluster(
    group: Sequence[DetectedBar],
    *,
    width: int,
    height: int,
) -> DetectedEntity | None:
    bar_union = union_rects(tuple(item.region for item in group))
    if bar_union is None or bar_union.width <= 0 or bar_union.height <= 0:
        return None
    if center_in_hud(bar_union, width=width, height=height):
        return None
    ally_votes = [item.ally_like for item in group if item.ally_like is not None]
    ally: bool | None
    if not ally_votes:
        ally = None
    elif all(ally_votes):
        ally = True
    elif not any(ally_votes):
        ally = False
    else:
        ally = None
    confidence = max(item.confidence for item in group)
    pad_x = max(4, bar_union.width // 8)
    body_h = max(BODY_MIN_HEIGHT, min(BODY_MAX_HEIGHT, int(bar_union.width * BODY_HEIGHT_FACTOR)))
    body = clamp_rect(
        ScreenRect(
            x=bar_union.x - pad_x,
            y=bar_union.y,
            width=bar_union.width + 2 * pad_x,
            height=body_h,
        ),
        width=width,
        height=height,
    )
    if body.width < 16 or body.height < 12:
        return None
    return DetectedEntity(
        region=body,
        bar_region=bar_union,
        confidence=round(min(0.9, confidence + 0.04 * (len(group) - 1)), 3),
        ally_like=ally,
        source=DETECTOR_SOURCE,
    )


def _has_nearby(
    candidate: FrameCandidate,
    frames: Sequence[FrameDetections],
    index: int,
    neighbor_px: float,
    *,
    radius: int,
) -> bool:
    for offset in range(-radius, radius + 1):
        if offset == 0:
            continue
        other_index = index + offset
        if other_index < 0 or other_index >= len(frames):
            continue
        other = frames[other_index]
        cx = candidate.region.x + candidate.region.width / 2.0
        cy = candidate.region.y + candidate.region.height / 2.0
        for item in other.candidates:
            ix = item.region.x + item.region.width / 2.0
            iy = item.region.y + item.region.height / 2.0
            dist = float(((cx - ix) ** 2 + (cy - iy) ** 2) ** 0.5)
            if dist <= neighbor_px:
                return True
    return False


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
