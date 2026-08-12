"""Health-bar color sampling for spectator team calibration. Research-only."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from riftlens.domain.observation.common import ScreenRect

RgbImage = NDArray[np.uint8]

MIN_SAT = 80
MIN_VAL = 80
MIN_PIXELS = 8


@dataclass(frozen=True)
class BarColorSample:
    """Stable HSV summary of a health-bar region. Not a team label."""

    hue_median: float
    sat_median: float
    val_median: float
    hue_p25: float
    hue_p75: float
    sample_pixels: int
    usable: bool


def sample_bar_color(pixels: RgbImage, region: ScreenRect) -> BarColorSample:
    """Return a median HSV sample over saturated pixels inside ``region``."""
    empty = BarColorSample(
        hue_median=0.0,
        sat_median=0.0,
        val_median=0.0,
        hue_p25=0.0,
        hue_p75=0.0,
        sample_pixels=0,
        usable=False,
    )
    if pixels.ndim != 3 or pixels.shape[2] != 3:
        return empty
    height, width = int(pixels.shape[0]), int(pixels.shape[1])
    y0 = max(0, int(region.y))
    x0 = max(0, int(region.x))
    y1 = min(height, int(region.y + region.height))
    x1 = min(width, int(region.x + region.width))
    if y1 - y0 < 2 or x1 - x0 < 4:
        return empty
    # Shrink 1px to avoid anti-aliased borders.
    if y1 - y0 > 3:
        y0 += 1
        y1 -= 1
    if x1 - x0 > 6:
        x0 += 1
        x1 -= 1
    patch = pixels[y0:y1, x0:x1]
    if patch.size == 0:
        return empty
    import cv2

    hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)
    mask = (hsv[:, :, 1] >= MIN_SAT) & (hsv[:, :, 2] >= MIN_VAL)
    vals = hsv[mask] if int(mask.sum()) >= MIN_PIXELS else hsv.reshape(-1, 3)
    if len(vals) < MIN_PIXELS:
        return empty
    hues = vals[:, 0].astype(np.float64)
    sats = vals[:, 1].astype(np.float64)
    brights = vals[:, 2].astype(np.float64)
    return BarColorSample(
        hue_median=float(np.median(hues)),
        sat_median=float(np.median(sats)),
        val_median=float(np.median(brights)),
        hue_p25=float(np.percentile(hues, 25)),
        hue_p75=float(np.percentile(hues, 75)),
        sample_pixels=int(len(vals)),
        usable=True,
    )


def hue_is_red_like(hue: float) -> bool:
    """Spectator red-team bars sit near hue 0/180 in OpenCV HSV."""
    return hue <= 15.0 or hue >= 165.0


def hue_is_blue_like(hue: float) -> bool:
    """Spectator blue-team bars sit near hue 90–130 in OpenCV HSV."""
    return 85.0 <= hue <= 135.0


def hue_is_green_like(hue: float) -> bool:
    """Play-perspective ally green (rare in free spectator)."""
    return 40.0 <= hue <= 85.0
