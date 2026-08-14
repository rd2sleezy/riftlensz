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

    binaries = _candidate_binaries(gray)
    best: Estimate[str] | None = None
    for binary in binaries:
        components = _segment_glyphs(binary, expected_height=atlas.height_px)
        if not (4 <= len(components) <= 7):
            continue
        chars: list[str] = []
        scores: list[float] = []
        ok = True
        for crop in components:
            ch, score = _match_glyph(crop, atlas)
            if score < GLYPH_MATCH_FLOOR or ch == "":
                ok = False
                break
            chars.append(ch)
            scores.append(score)
        if not ok:
            continue
        text = "".join(chars)
        if ":" not in text:
            continue
        conf = float(combine(scores))
        estimate = Estimate(text, conf, basis="template_match")
        if len(components) == 5:
            return estimate
        if best is None or estimate.confidence > best.confidence:
            best = estimate
    if best is not None:
        return best
    return Estimate("", 0.0, basis="glyph_below_floor")


def _candidate_binaries(gray: GrayImage) -> list[GrayImage]:
    """Try peak-scaled bright masks, then adaptive (synthetic) fallback."""
    out: list[GrayImage] = []
    peak = float(np.percentile(gray, 99.5))
    if peak >= 150.0:
        for scale in (0.82, 0.86, 0.78, 0.90):
            thr_val = max(150, int(round(peak * scale)))
            mask = np.asarray((gray >= thr_val).astype(np.uint8) * 255, dtype=np.uint8)
            if int(np.count_nonzero(mask)) >= 15:
                out.append(mask)
    out.append(_prepare_binary_adaptive(gray))
    return out


def _prepare_binary(gray: GrayImage) -> GrayImage:
    """Binarize ROI so glyphs are white (primary bright-peak mask)."""
    return _candidate_binaries(gray)[0]


def _prepare_binary_adaptive(gray: GrayImage) -> GrayImage:
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    thr = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    if float(np.mean(thr)) > 127:
        thr = cv2.bitwise_not(thr)
    return np.asarray(thr, dtype=np.uint8)


def _segment_glyphs(binary: GrayImage, *, expected_height: int) -> list[GrayImage]:
    """Split glyphs via content-row trim + horizontal projection runs."""
    rows = np.where(binary.max(axis=1) > 0)[0]
    if rows.size == 0:
        return []
    y0 = int(rows[0])
    y1 = int(rows[-1]) + 1
    band = binary[y0:y1]
    if band.size == 0:
        return []
    proj = band.max(axis=0)
    runs = _projection_runs(proj)
    runs = _drop_outlier_runs(runs, width=band.shape[1])
    runs = _merge_colon_dot_runs(runs, band=band)
    min_h = max(3, int(0.25 * expected_height))
    crops: list[GrayImage] = []
    for x0, x1 in runs:
        w = x1 - x0
        if w < 1:
            continue
        pad = 1
        xa = max(0, x0 - pad)
        xb = min(band.shape[1], x1 + pad)
        col = band[:, xa:xb]
        crow = np.where(col.max(axis=1) > 0)[0]
        if crow.size == 0:
            continue
        ya = int(crow[0])
        yb = int(crow[-1]) + 1
        crop = col[ya:yb]
        if crop.shape[0] < min_h and w < max(2, expected_height // 5):
            continue
        nh = expected_height
        nw = max(2, int(round(crop.shape[1] * (nh / max(1, crop.shape[0])))))
        resized = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)
        crops.append(np.asarray(resized, dtype=np.uint8))
    if crops:
        return crops
    return _segment_by_contours(binary, expected_height=expected_height)


def _projection_runs(proj: NDArray[np.uint8]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    in_run = False
    start = 0
    for x, value in enumerate(proj.tolist()):
        if value and not in_run:
            start = x
            in_run = True
        elif not value and in_run:
            runs.append((start, x))
            in_run = False
    if in_run:
        runs.append((start, int(proj.shape[0])))
    return runs


def _drop_outlier_runs(
    runs: list[tuple[int, int]], *, width: int
) -> list[tuple[int, int]]:
    """Drop chrome flecks far from the main clock cluster."""
    if len(runs) <= 5:
        # Still drop far-left / far-right flecks when a tight mid cluster exists.
        pass
    if len(runs) < 2:
        return runs
    centers = [0.5 * (a + b) for a, b in runs]
    mid = float(np.median(centers))
    max_dist = max(28.0, 0.22 * float(width))
    kept = [run for run, c in zip(runs, centers, strict=True) if abs(c - mid) <= max_dist]
    return kept or runs


def _run_content_height(band: GrayImage, x0: int, x1: int) -> int:
    col = band[:, max(0, x0) : min(band.shape[1], x1)]
    if col.size == 0:
        return 0
    rows = np.where(col.max(axis=1) > 0)[0]
    if rows.size == 0:
        return 0
    return int(rows[-1] - rows[0] + 1)


def _merge_colon_dot_runs(
    runs: list[tuple[int, int]], *, band: GrayImage
) -> list[tuple[int, int]]:
    """Merge two tiny adjacent *short* runs that form a colon into one glyph box.

    Narrow full-height strokes (digit ``1``) must not merge with the next digit.
    """
    if len(runs) < 2:
        return runs
    band_height = band.shape[0]
    merged: list[tuple[int, int]] = []
    i = 0
    max_colon_w = max(3, band_height // 3)
    max_dot_h = max(3, int(0.45 * band_height))
    while i < len(runs):
        if i + 1 < len(runs):
            a0, a1 = runs[i]
            b0, b1 = runs[i + 1]
            aw, bw = a1 - a0, b1 - b0
            gap = b0 - a1
            ha = _run_content_height(band, a0, a1)
            hb = _run_content_height(band, b0, b1)
            if (
                aw <= max_colon_w
                and bw <= max_colon_w
                and ha <= max_dot_h
                and hb <= max_dot_h
                and 0 <= gap <= max_colon_w
            ):
                merged.append((a0, b1))
                i += 2
                continue
        merged.append(runs[i])
        i += 1
    return merged


def _segment_by_contours(binary: GrayImage, *, expected_height: int) -> list[GrayImage]:
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
        result = cv2.matchTemplate(work, template, cv2.TM_CCOEFF_NORMED)
        return float(result.max()) if result.size else -1.0
    result = cv2.matchTemplate(work, template, cv2.TM_CCOEFF_NORMED)
    return float(result.max()) if result.size else -1.0
