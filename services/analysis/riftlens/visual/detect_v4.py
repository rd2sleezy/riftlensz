"""V.4 spectator bar proposals. Extends V.2 geometry with blue-team hues.

Does not replace the V.2 detector. Adds blue/cyan health-bar proposals that
free-spectator rendering uses for team 100, which V.0 green/red masks miss.
Blue proposals use the same champion-bar geometry gate as V.2.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from riftlens.domain.observation.common import ScreenRect
from riftlens.visual.detect import (
    MAX_PLAUSIBLE_CHAMPIONS,
    DetectedBar,
    ViewportCoverage,
    classify_viewport,
    detect_champion_like_bars,
)
from riftlens.visual.detect_v2 import (
    DetectedEntity,
    _cluster_bars,
    _entity_from_cluster,
    _plausible_champion_bar,
    candidates_from_entities,
    confirm_temporal,
)
from riftlens.visual.hud_mask import RgbImage, apply_hud_mask, center_in_hud
from riftlens.visual.track import FrameDetections

# OpenCV HSV: spectator blue-side champion bars (strict sat/val to avoid chrome).
_BLUE_LOW = np.array([95, 140, 140], dtype=np.uint8)
_BLUE_HIGH = np.array([125, 255, 255], dtype=np.uint8)

V4_DETECTOR_SOURCE = "v4.spectator"


def detect_blue_team_bars(pixels: RgbImage) -> tuple[DetectedBar, ...]:
    """Detect horizontal blue health-bar-like regions. ally_like is None."""
    if pixels.ndim != 3 or pixels.shape[2] != 3:
        return ()
    height, width = int(pixels.shape[0]), int(pixels.shape[1])
    if height < 16 or width < 16:
        return ()
    import cv2

    hsv = cv2.cvtColor(pixels, cv2.COLOR_RGB2HSV)
    mask = np.asarray(cv2.inRange(hsv, _BLUE_LOW, _BLUE_HIGH), dtype=np.uint8)
    return _bars_from_mask(mask)


def detect_champion_like_entities_v4(pixels: RgbImage) -> tuple[DetectedEntity, ...]:
    """V.2 hybrid entity detect plus spectator blue-team bar proposals."""
    if pixels.ndim != 3 or pixels.shape[2] != 3:
        return ()
    height, width = int(pixels.shape[0]), int(pixels.shape[1])
    if height < 16 or width < 16:
        return ()
    masked = apply_hud_mask(pixels)
    bars = list(detect_champion_like_bars(masked))
    bars.extend(detect_blue_team_bars(masked))
    gameplay = tuple(
        bar
        for bar in _nms_bars(tuple(bars))
        if not center_in_hud(bar.region, width=width, height=height)
        and _plausible_champion_bar(bar, frame_width=width)
    )
    if len(gameplay) > MAX_PLAUSIBLE_CHAMPIONS:
        return ()
    clustered = _cluster_bars(gameplay)
    entities = tuple(
        _entity_from_cluster(group, width=width, height=height) for group in clustered
    )
    out: list[DetectedEntity] = []
    for item in entities:
        if item is None:
            continue
        out.append(
            DetectedEntity(
                region=item.region,
                bar_region=item.bar_region,
                confidence=item.confidence,
                ally_like=None,  # V.4 defers team to calibration
                source=V4_DETECTOR_SOURCE,
            )
        )
    return tuple(out)


def detect_sample_entities_v4(
    pixels: RgbImage,
    *,
    frame_index: int,
    game_t_ms: int,
) -> FrameDetections:
    """One-frame V.4 detection. Team left UNKNOWN until calibration."""
    coverage = classify_viewport(pixels)
    if coverage is not ViewportCoverage.USEFUL:
        return FrameDetections(
            frame_index=frame_index,
            game_t_ms=game_t_ms,
            candidates=(),
            coverage=coverage,
        )
    entities = detect_champion_like_entities_v4(pixels)
    return FrameDetections(
        frame_index=frame_index,
        game_t_ms=game_t_ms,
        candidates=candidates_from_entities(entities),
        coverage=coverage,
    )


def _bars_from_mask(mask: NDArray[np.uint8]) -> tuple[DetectedBar, ...]:
    import cv2

    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    found: list[DetectedBar] = []
    for index in range(1, count):
        x, y, width, height, area = (int(v) for v in stats[index])
        if width < 40 or height < 3 or height > 12 or area < 80:
            continue
        aspect = width / float(max(height, 1))
        if aspect < 5.5:
            continue
        found.append(
            DetectedBar(
                region=ScreenRect(x=x, y=y, width=width, height=height),
                confidence=0.8,
                ally_like=None,
            )
        )
    return tuple(found)


def _nms_bars(bars: tuple[DetectedBar, ...], *, iou: float = 0.35) -> tuple[DetectedBar, ...]:
    """Prefer higher-confidence overlapping proposals (dedupe red/blue doubles)."""
    ordered = sorted(bars, key=lambda item: item.confidence, reverse=True)
    kept: list[DetectedBar] = []
    for bar in ordered:
        if any(_iou(bar.region, other.region) >= iou for other in kept):
            continue
        kept.append(bar)
    return tuple(kept)


def _iou(a: ScreenRect, b: ScreenRect) -> float:
    x0 = max(a.x, b.x)
    y0 = max(a.y, b.y)
    x1 = min(a.x + a.width, b.x + b.width)
    y1 = min(a.y + a.height, b.y + b.height)
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    if inter <= 0:
        return 0.0
    union = a.width * a.height + b.width * b.height - inter
    return inter / float(max(union, 1))


__all__ = [
    "V4_DETECTOR_SOURCE",
    "confirm_temporal",
    "detect_blue_team_bars",
    "detect_champion_like_entities_v4",
    "detect_sample_entities_v4",
]
