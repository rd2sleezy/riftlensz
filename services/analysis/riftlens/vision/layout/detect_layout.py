"""Layout detection / calibration for H.9.1 clock OCR."""

from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np
from numpy.typing import NDArray

from riftlens.domain.layout_profile import LayoutProfile, PixelRect
from riftlens.vision.layout.resolutions import CLOCK_SEEDS, MINIMAP_BAND, NormRect
from riftlens.vision.ocr.atlas import GlyphAtlas, choose_atlas
from riftlens.vision.ocr.digits import GLYPH_MATCH_FLOOR, read_digits

BgrImage = NDArray[np.uint8]


def detect_layout(frames: Sequence[BgrImage]) -> LayoutProfile:
    """Estimate HUD layout from one or more mid-game sample frames.

    Uses minimap-band heuristics + clock ROI seed search scored by digit OCR.
    Returns low confidence when evidence is weak (fail closed for callers).
    """
    if not frames:
        raise ValueError("detect_layout requires at least one frame")
    frame = frames[0]
    height, width = frame.shape[:2]
    minimap = _estimate_minimap(frame)
    ui_scale = _ui_scale_from_minimap(minimap, frame_h=height)
    flipped = _estimate_minimap_flip(frame, minimap)
    clock, clock_conf = _search_clock_roi(frames, ui_scale=ui_scale)
    conf = float(min(1.0, 0.35 * ui_scale_confidence(ui_scale) + 0.65 * clock_conf))
    return LayoutProfile(
        width=width,
        height=height,
        ui_scale=ui_scale,
        minimap_rect=minimap,
        clock_rect=clock,
        minimap_flipped=flipped,
        confidence=conf,
        version="h9.1",
        regions={
            "method": "minimap_band+clock_seed_search",
            "clock_search_confidence": clock_conf,
        },
    )


def ui_scale_confidence(ui_scale: float) -> float:
    """Soft confidence that ui_scale is in a plausible band."""
    if 0.5 <= ui_scale <= 2.0:
        return 1.0
    if 0.35 <= ui_scale <= 2.5:
        return 0.5
    return 0.1


def _norm_to_pixel(norm: NormRect, *, width: int, height: int) -> PixelRect:
    return PixelRect(
        x=int(round(norm.x * width)),
        y=int(round(norm.y * height)),
        width=max(1, int(round(norm.w * width))),
        height=max(1, int(round(norm.h * height))),
    ).clamp(width, height)


def _estimate_minimap(frame: BgrImage) -> PixelRect:
    height, width = frame.shape[:2]
    band = _norm_to_pixel(MINIMAP_BAND, width=width, height=height)
    crop = frame[band.y : band.y + band.height, band.x : band.x + band.width]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 160)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best: PixelRect | None = None
    best_score = 0.0
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < 40 or h < 40:
            continue
        aspect = w / max(1, h)
        if abs(aspect - 1.0) > 0.35:
            continue
        score = float(w * h) / (1.0 + abs(aspect - 1.0))
        if score > best_score:
            best_score = score
            best = PixelRect(x=band.x + x, y=band.y + y, width=w, height=h)
    if best is None:
        side = min(band.width, band.height)
        return PixelRect(
            x=band.x + band.width - side,
            y=band.y + band.height - side,
            width=side,
            height=side,
        ).clamp(width, height)
    return best.clamp(width, height)


def _ui_scale_from_minimap(minimap: PixelRect, *, frame_h: int) -> float:
    ref = 0.18 * float(frame_h)
    return max(0.35, min(2.5, float(minimap.height) / max(1.0, ref)))


def _estimate_minimap_flip(frame: BgrImage, minimap: PixelRect) -> bool:
    """Heuristic corner-blue comparison. False when uncertain."""
    if minimap.width < 20 or minimap.height < 20:
        return False
    crop = frame[
        minimap.y : minimap.y + minimap.height, minimap.x : minimap.x + minimap.width
    ]
    h, w = crop.shape[:2]
    bl = crop[int(h * 0.75) : h, 0 : int(w * 0.25)]
    br = crop[int(h * 0.75) : h, int(w * 0.75) : w]
    if bl.size == 0 or br.size == 0:
        return False
    bl_blue = float(np.mean(bl[:, :, 0]))
    br_blue = float(np.mean(br[:, :, 0]))
    return br_blue > bl_blue + 15.0


def _search_clock_roi(
    frames: Sequence[BgrImage], *, ui_scale: float
) -> tuple[PixelRect, float]:
    frame = frames[0]
    height, width = frame.shape[:2]
    best_rect = _norm_to_pixel(CLOCK_SEEDS[0], width=width, height=height)
    best_conf = 0.0
    atlas = choose_atlas(max(12, int(round(24 * ui_scale))))
    for seed in CLOCK_SEEDS:
        base = _norm_to_pixel(seed, width=width, height=height)
        for dy in (-4, 0, 4, 8):
            for dx in (-8, -4, 0, 4, 8):
                for scale in (0.9, 1.0, 1.15):
                    rect = PixelRect(
                        x=base.x + dx,
                        y=max(0, base.y + dy),
                        width=max(8, int(round(base.width * scale))),
                        height=max(8, int(round(base.height * scale * ui_scale))),
                    ).clamp(width, height)
                    scores = [
                        _score_clock_candidate(item, rect, atlas=atlas)
                        for item in frames[:3]
                    ]
                    score = float(np.mean(scores))
                    if score > best_conf:
                        best_conf = score
                        best_rect = rect
    return best_rect, best_conf


def _score_clock_candidate(
    frame: BgrImage, rect: PixelRect, *, atlas: GlyphAtlas
) -> float:
    crop = frame[rect.y : rect.y + rect.height, rect.x : rect.x + rect.width]
    if crop.size == 0:
        return 0.0
    estimate = read_digits(crop, atlas=atlas)
    text = estimate.value
    if not text or estimate.confidence < GLYPH_MATCH_FLOOR:
        return 0.0
    if ":" not in text:
        return float(estimate.confidence) * 0.25
    if _looks_like_clock(text):
        return float(estimate.confidence)
    return float(estimate.confidence) * 0.4


def _looks_like_clock(text: str) -> bool:
    parts = text.split(":")
    if len(parts) not in {2, 3}:
        return False
    return all(part.isdigit() for part in parts)
