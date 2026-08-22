"""Deterministic synthetic RGB fixtures for RP.1 tests (no real replay media)."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

RgbImage = NDArray[np.uint8]


def blank_frame(width: int = 640, height: int = 360) -> RgbImage:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :] = (18, 22, 28)
    # Gameplay texture so viewport classification is USEFUL.
    image[40 : height - 60, 40 : width - 40] = (40, 50, 60)
    return image


def frame_with_champion_bar(
    *,
    width: int = 640,
    height: int = 360,
    x: int = 200,
    y: int = 120,
    bar_w: int = 64,
    bar_h: int = 6,
    fill: float = 0.75,
) -> RgbImage:
    image = blank_frame(width, height)
    filled = max(1, int(round(bar_w * fill)))
    image[y : y + bar_h, x : x + filled] = (40, 220, 50)
    if filled < bar_w:
        image[y : y + bar_h, x + filled : x + bar_w] = (40, 40, 40)
    return image


def frame_with_minion_bars(
    *,
    width: int = 640,
    height: int = 360,
    count: int = 3,
) -> RgbImage:
    """Short green bars in gameplay viewport (below champion width gate)."""
    image = blank_frame(width, height)
    for index in range(count):
        x = 180 + index * 36
        y = 140 + index * 10
        image[y : y + 4, x : x + 24] = (40, 220, 50)
    return image


def frame_with_player_hud(
    *,
    width: int = 640,
    height: int = 360,
    hp_fill: float = 0.8,
    resource_fill: float | None = 0.55,
) -> RgbImage:
    """Paint HP (green) and optional mana (blue) in the RP.1 HUD ROI."""
    image = blank_frame(width, height)
    # resource_hp_area ≈ (0.36, 0.86, 0.20, 0.04)
    x = int(round(0.36 * width))
    y = int(round(0.86 * height))
    w = max(8, int(round(0.20 * width)))
    h = max(3, int(round(0.04 * height)))
    filled = max(1, int(round(w * hp_fill)))
    image[y : y + h, x : x + filled] = (40, 220, 50)
    if filled < w:
        image[y : y + h, x + filled : x + w] = (30, 30, 30)
    if resource_fill is not None:
        ry = min(height - 1, y + h + 2)
        rh = max(2, int(round(h * 0.7)))
        rf = max(1, int(round(w * resource_fill)))
        image[ry : ry + rh, x : x + rf] = (40, 90, 220)
        if rf < w:
            image[ry : ry + rh, x + rf : x + w] = (30, 30, 30)
    return image


def frame_with_minimap_pip(*, width: int = 640, height: int = 360) -> RgbImage:
    image = blank_frame(width, height)
    # minimap ≈ (0, 0.68, 0.18, 0.32)
    x = int(round(0.05 * width))
    y = int(round(0.80 * height))
    image[y : y + 4, x : x + 4] = (240, 240, 240)
    return image
