"""Resolution-relative HUD/UI masks for V.2. Not minimap understanding."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from riftlens.domain.observation.common import ScreenRect

RgbImage = NDArray[np.uint8]


def hud_rects(width: int, height: int) -> tuple[ScreenRect, ...]:
    """Return persistent UI bands to ignore as champion-like entities.

    Fractions are relative to the full captured frame. Gameplay entities sitting
    just above the bottom HUD are kept; the mask starts at 84% height.
    """
    if width <= 0 or height <= 0:
        return ()
    header = ScreenRect(x=0, y=0, width=width, height=max(1, int(round(height * 0.08))))
    bottom = ScreenRect(
        x=0,
        y=int(round(height * 0.84)),
        width=width,
        height=max(1, height - int(round(height * 0.84))),
    )
    minimap = ScreenRect(
        x=0,
        y=int(round(height * 0.68)),
        width=max(1, int(round(width * 0.18))),
        height=max(1, height - int(round(height * 0.68))),
    )
    kill_feed = ScreenRect(
        x=int(round(width * 0.78)),
        y=int(round(height * 0.08)),
        width=max(1, width - int(round(width * 0.78))),
        height=max(1, int(round(height * 0.22))),
    )
    replay_controls = ScreenRect(
        x=int(round(width * 0.70)),
        y=int(round(height * 0.88)),
        width=max(1, width - int(round(width * 0.70))),
        height=max(1, height - int(round(height * 0.88))),
    )
    edge = max(1, int(round(width * 0.035)))
    left_edge = ScreenRect(x=0, y=0, width=edge, height=height)
    right_edge = ScreenRect(x=max(0, width - edge), y=0, width=edge, height=height)
    return (header, bottom, minimap, kill_feed, replay_controls, left_edge, right_edge)


def center_in_hud(region: ScreenRect, *, width: int, height: int) -> bool:
    """True when the region's center sits inside a masked HUD/UI band."""
    cx = region.x + region.width / 2.0
    cy = region.y + region.height / 2.0
    for band in hud_rects(width, height):
        if band.x <= cx <= band.x + band.width and band.y <= cy <= band.y + band.height:
            return True
    return False


def apply_hud_mask(pixels: RgbImage) -> RgbImage:
    """Return a copy with HUD/UI bands zeroed. Does not mutate ``pixels``."""
    if pixels.ndim != 3 or pixels.shape[2] != 3:
        return pixels
    masked = np.array(pixels, copy=True)
    height, width = int(masked.shape[0]), int(masked.shape[1])
    for band in hud_rects(width, height):
        y1 = min(height, band.y + band.height)
        x1 = min(width, band.x + band.width)
        y0 = max(0, band.y)
        x0 = max(0, band.x)
        if y1 > y0 and x1 > x0:
            masked[y0:y1, x0:x1] = 0
    return masked


def clamp_rect(region: ScreenRect, *, width: int, height: int) -> ScreenRect:
    """Clamp a rect to the frame. Empty after clamp stays empty."""
    x = max(0, min(int(region.x), max(0, width - 1)))
    y = max(0, min(int(region.y), max(0, height - 1)))
    max_w = max(0, width - x)
    max_h = max(0, height - y)
    return ScreenRect(
        x=x,
        y=y,
        width=max(0, min(int(region.width), max_w)),
        height=max(0, min(int(region.height), max_h)),
    )


def union_rects(rects: Sequence[ScreenRect]) -> ScreenRect | None:
    """Return the axis-aligned union, or None when ``rects`` is empty."""
    if not rects:
        return None
    x0 = min(item.x for item in rects)
    y0 = min(item.y for item in rects)
    x1 = max(item.x + item.width for item in rects)
    y1 = max(item.y + item.height for item in rects)
    return ScreenRect(x=x0, y=y0, width=x1 - x0, height=y1 - y0)
