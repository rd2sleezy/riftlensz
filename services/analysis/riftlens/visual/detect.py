from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray

from riftlens.domain.observation.common import ScreenRect

RgbImage = NDArray[np.uint8]

# Ally-like LoL health bars are saturated green; enemy-like bars are saturated red.
# These ranges are for viewport health bars, not the HUD resource globe.
_GREEN_LOW = np.array([40, 140, 140], dtype=np.uint8)
_GREEN_HIGH = np.array([80, 255, 255], dtype=np.uint8)
_RED_LOW_A = np.array([0, 140, 140], dtype=np.uint8)
_RED_HIGH_A = np.array([10, 255, 255], dtype=np.uint8)
_RED_LOW_B = np.array([170, 140, 140], dtype=np.uint8)
_RED_HIGH_B = np.array([180, 255, 255], dtype=np.uint8)
MAX_PLAUSIBLE_CHAMPIONS = 10


class ViewportCoverage(StrEnum):
    """Whether the captured viewport is usable for entity detection.

    Off-camera is not fog-of-war. UNCONTROLLED camera + empty detections
    does not mean the player lacked vision.
    """

    USEFUL = "USEFUL"
    OBSTRUCTED = "OBSTRUCTED"
    TRANSITION = "TRANSITION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class DetectedBar:
    """One champion-like health-bar detection. Not a champion identity."""

    region: ScreenRect
    confidence: float
    ally_like: bool | None
    """True=green/ally-like, False=red/enemy-like, None=uncolored/unknown."""


def detect_champion_like_bars(pixels: RgbImage) -> tuple[DetectedBar, ...]:
    """Detect horizontal health-bar-like regions in a gameplay viewport crop.

    This is a V.0 heuristic, not champion recognition. Empty output means
    nothing matched the bar geometry — not that champions are known absent.
    """
    if pixels.ndim != 3 or pixels.shape[2] != 3:
        return ()
    height, width = int(pixels.shape[0]), int(pixels.shape[1])
    if height < 16 or width < 16:
        return ()
    import cv2

    crop, origin_x, origin_y = _viewport_crop(pixels)
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    green = np.asarray(cv2.inRange(hsv, _GREEN_LOW, _GREEN_HIGH), dtype=np.uint8)
    red = np.asarray(
        cv2.bitwise_or(
            cv2.inRange(hsv, _RED_LOW_A, _RED_HIGH_A),
            cv2.inRange(hsv, _RED_LOW_B, _RED_HIGH_B),
        ),
        dtype=np.uint8,
    )
    found: list[DetectedBar] = []
    found.extend(_bars_from_mask(green, origin_x=origin_x, origin_y=origin_y, ally_like=True))
    found.extend(_bars_from_mask(red, origin_x=origin_x, origin_y=origin_y, ally_like=False))
    return _nms(tuple(found))


def viewport_is_informative(pixels: RgbImage) -> bool:
    """Return False when the sampled frame has too little texture to trust counts."""
    return classify_viewport(pixels) is ViewportCoverage.USEFUL


def classify_viewport(pixels: RgbImage) -> ViewportCoverage:
    """Classify captured-frame coverage. Does not claim player vision or fog."""
    if pixels.size == 0 or pixels.ndim != 3:
        return ViewportCoverage.UNKNOWN
    crop, _, _ = _viewport_crop(pixels)
    if crop.size == 0:
        return ViewportCoverage.UNKNOWN
    luma = crop.astype(np.float32).mean(axis=2)
    mean = float(luma.mean())
    std = float(luma.std())
    if std >= 12.0 and mean >= 8.0:
        return ViewportCoverage.USEFUL
    if mean < 8.0:
        return ViewportCoverage.OBSTRUCTED
    if std < 12.0:
        return ViewportCoverage.TRANSITION
    return ViewportCoverage.UNKNOWN


def _viewport_crop(pixels: RgbImage) -> tuple[RgbImage, int, int]:
    """Drop typical HUD/minimap bands so bars there are not counted as champions."""
    height, width = int(pixels.shape[0]), int(pixels.shape[1])
    top = int(round(height * 0.08))
    bottom = int(round(height * 0.82))
    left = int(round(width * 0.02))
    right = int(round(width * 0.98))
    if bottom - top < 16 or right - left < 16:
        return pixels, 0, 0
    # Minimap sits in the lower-left of the remaining crop; cut an extra corner.
    crop = pixels[top:bottom, left:right].copy()
    mm_h = int(round(crop.shape[0] * 0.22))
    mm_w = int(round(crop.shape[1] * 0.18))
    crop[-mm_h:, :mm_w] = 0
    return crop, left, top


def _bars_from_mask(
    mask: NDArray[np.uint8],
    *,
    origin_x: int,
    origin_y: int,
    ally_like: bool,
) -> list[DetectedBar]:
    import cv2

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3))
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out: list[DetectedBar] = []
    for contour in contours:
        x, y, width, height = (int(v) for v in cv2.boundingRect(contour))
        if height < 3 or width < 24:
            continue
        aspect = width / float(height)
        if aspect < 4.5 or aspect > 16.0:
            continue
        if height > 10 or width > 140:
            continue
        fill = float(cv2.contourArea(contour)) / float(max(width * height, 1))
        if fill < 0.40:
            continue
        confidence = _bar_confidence(aspect=aspect, fill=fill, height=height)
        out.append(
            DetectedBar(
                region=ScreenRect(x=origin_x + x, y=origin_y + y, width=width, height=height),
                confidence=confidence,
                ally_like=ally_like,
            )
        )
    return out


def _bar_confidence(*, aspect: float, fill: float, height: int) -> float:
    aspect_score = 1.0 - min(abs(aspect - 8.0) / 12.0, 1.0)
    fill_score = min(fill / 0.7, 1.0)
    height_score = 1.0 if 3 <= height <= 10 else 0.6
    return round(
        max(0.2, min(0.85, 0.35 * aspect_score + 0.4 * fill_score + 0.25 * height_score)), 3
    )


def _nms(bars: tuple[DetectedBar, ...], iou: float = 0.35) -> tuple[DetectedBar, ...]:
    ordered = sorted(bars, key=lambda item: item.confidence, reverse=True)
    kept: list[DetectedBar] = []
    for candidate in ordered:
        if any(_overlap(candidate.region, item.region) >= iou for item in kept):
            continue
        kept.append(candidate)
    return tuple(sorted(kept, key=lambda item: (item.region.y, item.region.x)))


def _overlap(left: ScreenRect, right: ScreenRect) -> float:
    x0 = max(left.x, right.x)
    y0 = max(left.y, right.y)
    x1 = min(left.x + left.width, right.x + right.width)
    y1 = min(left.y + left.height, right.y + right.height)
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = left.width * left.height + right.width * right.height - inter
    if union <= 0:
        return 0.0
    return inter / float(union)
