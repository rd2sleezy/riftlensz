"""Minimap ROI foundation — no fog/jungle/identity claims."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from riftlens.domain.observation.common import ScreenRect
from riftlens.perception.geometry import LayoutSupport, ScreenGeometry
from riftlens.perception.models import MinimapObservation, NormalizedPoint, NormalizedRect

RgbImage = NDArray[np.uint8]


def extract_minimap(pixels: RgbImage, geometry: ScreenGeometry) -> MinimapObservation:
    """Extract the lower-left minimap ROI. Pip detection is intentionally conservative."""
    if geometry.layout_support is LayoutSupport.UNSUPPORTED:
        empty = ScreenRect(0, 0, 0, 0)
        return MinimapObservation(
            roi=empty,
            roi_norm=NormalizedRect(0.0, 0.0, 0.0, 0.0),
            extracted=False,
            notes="unsupported_layout; minimap ROI unavailable",
        )
    roi = geometry.roi("minimap")
    if roi is None:
        empty = ScreenRect(0, 0, 0, 0)
        return MinimapObservation(
            roi=empty,
            roi_norm=NormalizedRect(0.0, 0.0, 0.0, 0.0),
            extracted=False,
            notes="minimap ROI missing",
        )
    pips = _bright_pips(pixels, roi)
    return MinimapObservation(
        roi=roi,
        roi_norm=geometry.normalize_rect(roi),
        extracted=True,
        pip_candidates=pips,
        notes=(
            "Minimap ROI + conservative bright-pip candidates only. "
            "No participant identity, fog, ward coverage, or jungle path."
        ),
    )


def _bright_pips(pixels: RgbImage, roi: ScreenRect) -> tuple[NormalizedPoint, ...]:
    """Optional generic bright spots inside the minimap — never identified."""
    import cv2

    if pixels.ndim != 3:
        return ()
    y0, y1 = roi.y, min(pixels.shape[0], roi.y + roi.height)
    x0, x1 = roi.x, min(pixels.shape[1], roi.x + roi.width)
    crop = pixels[y0:y1, x0:x1]
    if crop.size == 0:
        return ()
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    points: list[NormalizedPoint] = []
    for contour in contours:
        x, y, w, h = (int(v) for v in cv2.boundingRect(contour))
        if w < 2 or h < 2 or w > 12 or h > 12:
            continue
        cx = x + w / 2.0
        cy = y + h / 2.0
        if roi.width <= 0 or roi.height <= 0:
            continue
        points.append(
            NormalizedPoint(
                x=round(cx / float(roi.width), 6),
                y=round(cy / float(roi.height), 6),
            )
        )
    return tuple(points[:32])
