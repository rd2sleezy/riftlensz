"""Player HUD HP / resource fraction primitives."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from riftlens.domain.enums import Source
from riftlens.domain.observation.common import ScreenRect
from riftlens.perception.geometry import LayoutSupport, ScreenGeometry
from riftlens.perception.models import (
    ObservationStatus,
    PlayerHudState,
    VisualClaim,
    unavailable_claim,
    unknown_claim,
)

RgbImage = NDArray[np.uint8]

_GREEN_LOW = np.array([40, 100, 100], dtype=np.uint8)
_GREEN_HIGH = np.array([90, 255, 255], dtype=np.uint8)
_BLUE_LOW = np.array([95, 80, 80], dtype=np.uint8)
_BLUE_HIGH = np.array([130, 255, 255], dtype=np.uint8)


def extract_player_hud(pixels: RgbImage, geometry: ScreenGeometry) -> PlayerHudState:
    """Estimate own HP/resource fractions from the bottom HUD ROI.

    Exact numeric HP/mana is not required. Missing resource → UNKNOWN, never 0.
    """
    if geometry.layout_support is LayoutSupport.UNSUPPORTED:
        return PlayerHudState(
            usable=unavailable_claim(notes=geometry.layout_notes),
            hp_fraction=unavailable_claim(notes="unsupported_layout"),
            resource_fraction=unavailable_claim(notes="unsupported_layout"),
            layout_notes=geometry.layout_notes,
        )
    roi = geometry.roi("resource_hp_area")
    if roi is None or pixels.ndim != 3:
        return PlayerHudState(
            usable=unavailable_claim(notes="missing_hud_roi"),
            hp_fraction=unknown_claim(notes="missing_hud_roi"),
            resource_fraction=unknown_claim(notes="missing_hud_roi"),
        )
    hp = _fraction_in_roi(pixels, roi, kind="hp")
    # Resource bar sits just below HP in the player HUD band.
    resource_roi = ScreenRect(
        x=roi.x,
        y=min(geometry.height - 1, roi.y + roi.height + 2),
        width=roi.width,
        height=max(2, int(round(roi.height * 0.7))),
    )
    resource = _fraction_in_roi(pixels, resource_roi, kind="resource")
    usable = VisualClaim(
        status=ObservationStatus.OBSERVED,
        value=hp.status is ObservationStatus.OBSERVED,
        confidence=0.6 if hp.status is ObservationStatus.OBSERVED else 0.3,
        source=Source.VISUAL,
        notes="hud_roi_present",
    )
    return PlayerHudState(
        usable=usable,
        hp_fraction=hp,
        resource_fraction=resource,
        layout_notes="fractional HUD estimate; champion-specific layouts may be UNKNOWN",
    )


def _fraction_in_roi(pixels: RgbImage, roi: ScreenRect, *, kind: str) -> VisualClaim:
    import cv2

    y0 = max(0, roi.y)
    y1 = min(pixels.shape[0], roi.y + roi.height)
    x0 = max(0, roi.x)
    x1 = min(pixels.shape[1], roi.x + roi.width)
    if y1 <= y0 or x1 <= x0:
        return unknown_claim(notes=f"{kind}_roi_empty")
    crop = pixels[y0:y1, x0:x1]
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    if kind == "hp":
        mask = cv2.inRange(hsv, _GREEN_LOW, _GREEN_HIGH)
    else:
        mask = cv2.inRange(hsv, _BLUE_LOW, _BLUE_HIGH)
    cols = mask.max(axis=0) > 0
    if int(np.count_nonzero(cols)) == 0:
        # Explicit: unavailable color → UNKNOWN, never fabricate 0.0.
        return unknown_claim(
            notes=f"{kind}_color_not_detected; not_zero",
        )
    fraction = round(int(np.count_nonzero(cols)) / float(cols.size), 3)
    return VisualClaim(
        status=ObservationStatus.OBSERVED,
        value=fraction,
        confidence=0.5,
        source=Source.VISUAL,
        notes=f"{kind}_column_fill",
    )
