"""Classical template-matching digit OCR for League HUD clocks (H.9.1).

Uses OpenCV ``TM_CCOEFF_NORMED`` against a glyph atlas. No Tesseract / neural OCR.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

from riftlens.domain.estimate import Estimate, combine
from riftlens.vision.ocr.atlas import GlyphAtlas, choose_atlas

GrayImage = NDArray[np.uint8]
GLYPH_MATCH_FLOOR = 0.72


@dataclass(frozen=True)
class DigitsResult:
    text: str
    confidence: float
    glyph_scores: tuple[float, ...]


def read_digits(
    roi: GrayImage | NDArray[np.uint8],
    atlas: GlyphAtlas | None = None,
) -> Estimate[str]:
    """Read digits+colon from a clock ROI. Fail closed below ``GLYPH_MATCH_FLOOR``."""
    if roi.ndim == 3:
        gray = np.asarray(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), dtype=np.uint8)
    else:
        gray = np.asarray(roi, dtype=np.uint8)
    if gray.size == 0:
        return Estimate("", 0.0, basis="empty_roi")
    if atlas is None:
        atlas = choose_atlas(max(8, int(gray.shape[0]) // 2))
    if not atlas.available():
        return Estimate("", 0.0, basis="missing_glyph_atlas")

    binary = _prepare_binary(gray)
    components = _segment_glyphs(binary, expected_height=atlas.height_px)
    if not components:
        return Estimate("", 0.0, basis="no_glyph_components")

    chars: list[str] = []
    scores: list[float] = []
    for crop in components:
        ch, score = _match_glyph(crop, atlas)
        if score < GLYPH_MATCH_FLOOR or ch == "":
            return Estimate("", 0.0, basis="glyph_below_floor")
        chars.append(ch)
        scores.append(score)
    text = "".join(chars)
    conf = float(combine(scores))
    return Estimate(text, conf, basis="template_match")


def _prepare_binary(gray: GrayImage) -> GrayImage:
    # HUD clocks are light-on-dark; invert if needed so glyphs are white.
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    thr = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    if float(np.mean(thr)) > 127:
        thr = cv2.bitwise_not(thr)
    return np.asarray(thr, dtype=np.uint8)


def _segment_glyphs(binary: GrayImage, *, expected_height: int) -> list[GrayImage]:
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[tuple[int, int, int, int]] = []
    h_img = binary.shape[0]
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if h < max(4, int(0.35 * expected_height)) and w < max(3, expected_height // 4):
            continue
        if h > h_img * 0.98 and w > binary.shape[1] * 0.9:
            continue
        if h < 3 or w < 1:
            continue
        boxes.append((x, y, w, h))
    boxes.sort(key=lambda item: item[0])
    crops: list[GrayImage] = []
    for x, y, w, h in boxes:
        pad = 1
        y0 = max(0, y - pad)
        x0 = max(0, x - pad)
        y1 = min(binary.shape[0], y + h + pad)
        x1 = min(binary.shape[1], x + w + pad)
        crop = binary[y0:y1, x0:x1]
        # Normalize to atlas height.
        nh = expected_height
        nw = max(2, int(round(crop.shape[1] * (nh / max(1, crop.shape[0])))))
        resized = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)
        crops.append(np.asarray(resized, dtype=np.uint8))
    return crops


def _match_glyph(crop: GrayImage, atlas: GlyphAtlas) -> tuple[str, float]:
    best_ch = ""
    best_score = -1.0
    for ch, template in atlas.templates.items():
        score = _template_score(crop, template)
        if score > best_score:
            best_score = score
            best_ch = ch
    return best_ch, float(best_score)


def _template_score(crop: GrayImage, template: GrayImage) -> float:
    th, tw = template.shape[:2]
    ch, cw = crop.shape[:2]
    # Resize crop width to template width while keeping atlas height.
    work: GrayImage = crop
    if ch != th:
        new_w = max(2, int(round(cw * (th / ch))))
        work = np.asarray(
            cv2.resize(work, (new_w, th), interpolation=cv2.INTER_AREA), dtype=np.uint8
        )
        ch, cw = work.shape[:2]
    if cw < tw:
        pad = np.zeros((th, tw), dtype=np.uint8)
        pad[:, :cw] = work
        work = pad
        cw = tw
    elif cw > tw:
        # Slide template across the wider crop; take max.
        result = cv2.matchTemplate(work, template, cv2.TM_CCOEFF_NORMED)
        return float(result.max()) if result.size else -1.0
    result = cv2.matchTemplate(work, template, cv2.TM_CCOEFF_NORMED)
    return float(result.max()) if result.size else -1.0
