"""Classical HUD vision for VIDEO clock OCR (H.9.1). Isolated from ROFL/coaching."""

from __future__ import annotations

from riftlens.vision.detectors.clock import is_in_game, parse_clock_text, read_clock
from riftlens.vision.layout.calibration import calibrate_layout
from riftlens.vision.layout.detect_layout import detect_layout
from riftlens.vision.ocr.digits import GLYPH_MATCH_FLOOR, read_digits
from riftlens.vision.pipeline import collect_clock_readings, reading_from_frame

__all__ = [
    "GLYPH_MATCH_FLOOR",
    "calibrate_layout",
    "collect_clock_readings",
    "detect_layout",
    "is_in_game",
    "parse_clock_text",
    "read_clock",
    "read_digits",
    "reading_from_frame",
]
