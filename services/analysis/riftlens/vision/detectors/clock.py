"""Game-clock detector: in-game gate + digit OCR + parse to ms (H.9.1)."""

from __future__ import annotations

import re

import cv2
import numpy as np
from numpy.typing import NDArray

from riftlens.domain.estimate import Estimate
from riftlens.domain.layout_profile import LayoutProfile, PixelRect
from riftlens.vision.ocr.digits import GLYPH_MATCH_FLOOR, read_digits

BgrImage = NDArray[np.uint8]
MAX_GAME_MS = 90 * 60 * 1000
MAX_JUMP_MS = 5 * 60 * 1000
IN_GAME_CONFIDENCE_FLOOR = 0.35


def is_in_game(frame: BgrImage, layout: LayoutProfile) -> bool:
    """Return True when HUD/clock evidence suggests an in-game frame.

    Fail closed: loading/menu/post-game should return False more often than
    producing a confident wrong clock.
    """
    if layout.confidence < 0.15:
        return False
    height, width = frame.shape[:2]
    if width != layout.width or height != layout.height:
        # Allow slight mismatch from letterboxing by requiring positive clock crop.
        pass
    clock = layout.clock_rect.clamp(width, height)
    crop = frame[clock.y : clock.y + clock.height, clock.x : clock.x + clock.width]
    if crop.size == 0:
        return False
    # Scoreboard strip should be relatively dark with bright glyphs.
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    mean = float(np.mean(gray))
    std = float(np.std(gray))
    if std < 8.0:
        return False
    # Reject near-uniform bright (loading) or near-black empty crops.
    if mean > 210 or mean < 5:
        return False
    estimate = read_digits(crop)
    if estimate.confidence >= GLYPH_MATCH_FLOOR and ":" in estimate.value:
        return True
    # Weak HUD presence: top-center band has enough edge energy.
    top = frame[0 : max(1, int(0.08 * height)), int(0.35 * width) : int(0.65 * width)]
    edges = cv2.Canny(cv2.cvtColor(top, cv2.COLOR_BGR2GRAY), 50, 150)
    edge_ratio = float(np.mean(edges > 0))
    return edge_ratio > 0.02 and layout.confidence >= IN_GAME_CONFIDENCE_FLOOR


def read_clock(
    frame: BgrImage,
    layout: LayoutProfile,
    *,
    previous_game_ms: int | None = None,
) -> Estimate[int]:
    """Read HUD clock as game milliseconds. Fail closed on weak/malformed evidence."""
    if not is_in_game(frame, layout):
        return Estimate(0, 0.0, basis="not_in_game")
    height, width = frame.shape[:2]
    rect = layout.clock_rect.clamp(width, height)
    crop = _crop(frame, rect)
    digits = read_digits(crop)
    if digits.confidence < GLYPH_MATCH_FLOOR or not digits.value:
        return Estimate(0, 0.0, basis=digits.basis or "unreadable_digits")
    parsed = parse_clock_text(digits.value)
    if parsed is None:
        return Estimate(0, 0.0, basis="malformed_clock_text")
    if parsed > MAX_GAME_MS:
        return Estimate(0, 0.0, basis="exceeds_90_minutes")
    if previous_game_ms is not None and abs(parsed - previous_game_ms) > MAX_JUMP_MS:
        # Allow equal (pause) and small forward/back noise; reject huge jumps.
        return Estimate(0, 0.0, basis="implausible_jump")
    return Estimate(parsed, float(digits.confidence), basis="clock_ocr")


def parse_clock_text(text: str) -> int | None:
    """Parse ``m:ss``, ``mm:ss``, or ``h:mm:ss`` into integer milliseconds."""
    cleaned = text.strip()
    match = re.fullmatch(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})", cleaned)
    if match is None:
        return None
    hour_s, minute_s, second_s = match.groups()
    hours = int(hour_s) if hour_s is not None else 0
    minutes = int(minute_s)
    seconds = int(second_s)
    if seconds >= 60 or seconds < 0 or minutes < 0 or hours < 0:
        return None
    if hour_s is not None and minutes >= 60:
        return None
    total_s = hours * 3600 + minutes * 60 + seconds
    return int(total_s * 1000)


def _crop(frame: BgrImage, rect: PixelRect) -> BgrImage:
    return frame[rect.y : rect.y + rect.height, rect.x : rect.x + rect.width]
