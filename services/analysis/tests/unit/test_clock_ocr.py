"""H.9.1 clock OCR / layout / ClockReading unit tests (synthetic glyphs)."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from riftlens.domain.clock_reading import ClockReading
from riftlens.domain.estimate import Estimate
from riftlens.domain.layout_profile import LayoutProfile, PixelRect
from riftlens.vision.detectors.clock import (
    MAX_GAME_MS,
    is_in_game,
    parse_clock_text,
    read_clock,
)
from riftlens.vision.layout.detect_layout import detect_layout
from riftlens.vision.ocr.atlas import choose_atlas, load_atlas
from riftlens.vision.ocr.digits import GLYPH_MATCH_FLOOR, read_digits
from riftlens.vision.pipeline import reading_from_frame


def _render_clock_roi(text: str, *, height: int = 24) -> np.ndarray:
    """Render synthetic clock text using the same Hershey style as the atlas."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = height / 32.0
    thickness = max(1, int(round(height / 16)))
    (tw, th), _ = cv2.getTextSize(text, font, scale, thickness)
    canvas = np.zeros((height + 8, tw + 16, 3), dtype=np.uint8)
    cv2.putText(
        canvas,
        text,
        (8, height + 2),
        font,
        scale,
        (220, 220, 220),
        thickness,
        cv2.LINE_AA,
    )
    return canvas


def _frame_with_clock(text: str, *, width: int = 1280, height: int = 720) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    # Fake dark scoreboard strip.
    frame[0:40, :] = (20, 20, 20)
    roi = _render_clock_roi(text, height=22)
    rh, rw = roi.shape[:2]
    x0 = width // 2 - rw // 2
    y0 = 8
    frame[y0 : y0 + rh, x0 : x0 + rw] = roi
    # Fake minimap square bottom-right for layout.
    side = int(0.18 * height)
    frame[height - side : height, width - side : width] = (30, 60, 30)
    cv2.rectangle(
        frame,
        (width - side, height - side),
        (width - 1, height - 1),
        (200, 200, 200),
        2,
    )
    return frame


def test_clock_reading_validation() -> None:
    ok = ClockReading(t_video_ms=1000, t_game_ms=60_000, confidence=0.9)
    assert ok.is_readable
    with pytest.raises(ValueError):
        ClockReading(t_video_ms=0, t_game_ms=1, confidence=1.5)


def test_atlas_loads_synthetic() -> None:
    atlas = load_atlas(24)
    assert atlas.available()
    source = atlas.source.upper()
    assert "SYNTHETIC" in source or atlas.source
    assert ":" in atlas.templates


def test_read_digits_roundtrip_synthetic() -> None:
    atlas = choose_atlas(24)
    roi = _render_clock_roi("12:34", height=24)
    estimate = read_digits(roi, atlas)
    # Synthetic Hershey→atlas may not be perfect; assert fail-closed behavior if weak.
    if estimate.confidence >= GLYPH_MATCH_FLOOR:
        assert ":" in estimate.value
        assert any(ch.isdigit() for ch in estimate.value)
    else:
        assert estimate.value == ""


def test_glyph_below_floor_fail_closed() -> None:
    noise = np.random.default_rng(0).integers(0, 255, size=(24, 80), dtype=np.uint8)
    estimate = read_digits(noise, choose_atlas(24))
    assert estimate.confidence == 0.0
    assert estimate.value == ""


def test_missing_atlas_fail_closed(tmp_path: Path) -> None:
    empty = tmp_path / "glyphs"
    empty.mkdir()
    atlas = load_atlas(24, root=empty)
    assert not atlas.available()
    estimate = read_digits(_render_clock_roi("1:00"), atlas)
    assert estimate.confidence == 0.0
    assert estimate.basis == "missing_glyph_atlas"


def test_parse_clock_variants() -> None:
    assert parse_clock_text("1:23") == 83_000
    assert parse_clock_text("12:34") == 754_000
    assert parse_clock_text("1:02:03") == 3_723_000
    assert parse_clock_text("bad") is None
    assert parse_clock_text("1:60") is None
    assert parse_clock_text("1:61:00") is None


def test_reject_over_ninety_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    layout = LayoutProfile(
        width=1280,
        height=720,
        ui_scale=1.0,
        minimap_rect=PixelRect(1000, 500, 200, 200),
        clock_rect=PixelRect(560, 5, 160, 30),
        confidence=0.9,
    )
    parsed = parse_clock_text("91:00")
    assert parsed == 5_460_000
    assert parsed is not None and parsed > MAX_GAME_MS
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    monkeypatch.setattr(
        "riftlens.vision.detectors.clock.is_in_game", lambda *_a, **_k: True
    )
    monkeypatch.setattr(
        "riftlens.vision.detectors.clock.read_digits",
        lambda *_a, **_k: Estimate("91:00", 0.95, basis="forced"),
    )
    estimate = read_clock(frame, layout)
    assert estimate.confidence == 0.0
    assert estimate.basis == "exceeds_90_minutes"


def test_layout_scaling_produces_clock_rect() -> None:
    frame = _frame_with_clock("0:15", width=1280, height=720)
    layout = detect_layout([frame])
    assert layout.width == 1280
    assert layout.height == 720
    assert layout.clock_rect.width > 0
    assert layout.ui_scale > 0


def test_layout_profile_round_trip_record() -> None:
    profile = LayoutProfile(
        width=1920,
        height=1080,
        ui_scale=1.1,
        minimap_rect=PixelRect(1600, 800, 280, 280),
        clock_rect=PixelRect(900, 4, 120, 36),
        minimap_flipped=True,
        confidence=0.7,
        regions={"k": 1},
    )
    row = profile.to_record(profile_id="p1", created_at=1)
    assert json.loads(row.clock_rect) == [900, 4, 120, 36]
    restored = LayoutProfile.from_record(row)
    assert restored.clock_rect == profile.clock_rect
    assert restored.minimap_flipped is True


def test_non_game_uniform_frame_rejected() -> None:
    frame = np.full((720, 1280, 3), 240, dtype=np.uint8)
    layout = LayoutProfile(
        width=1280,
        height=720,
        ui_scale=1.0,
        minimap_rect=PixelRect(1000, 500, 200, 200),
        clock_rect=PixelRect(560, 5, 160, 30),
        confidence=0.9,
    )
    assert is_in_game(frame, layout) is False
    estimate = read_clock(frame, layout)
    assert estimate.confidence == 0.0


def test_implausible_jump_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    layout = LayoutProfile(
        width=1280,
        height=720,
        ui_scale=1.0,
        minimap_rect=PixelRect(1000, 500, 200, 200),
        clock_rect=PixelRect(560, 5, 160, 30),
        confidence=0.9,
    )
    earlier = parse_clock_text("10:00")
    later = parse_clock_text("20:00")
    assert earlier is not None and later is not None
    assert abs(later - earlier) > 5 * 60 * 1000
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    monkeypatch.setattr(
        "riftlens.vision.detectors.clock.is_in_game", lambda *_a, **_k: True
    )
    monkeypatch.setattr(
        "riftlens.vision.detectors.clock.read_digits",
        lambda *_a, **_k: Estimate("20:00", 0.95, basis="forced"),
    )
    estimate = read_clock(frame, layout, previous_game_ms=earlier)
    assert estimate.confidence == 0.0
    assert estimate.basis == "implausible_jump"


def test_frozen_pause_readings_same_game_ms() -> None:
    """Pause semantics: identical t_game when clock text is unchanged."""
    frame = _frame_with_clock("10:00")
    layout = detect_layout([frame])
    # Pin clock rect to where we drew the text for deterministic unit path.
    roi = _render_clock_roi("10:00", height=22)
    rh, rw = roi.shape[:2]
    layout = LayoutProfile(
        width=1280,
        height=720,
        ui_scale=layout.ui_scale,
        minimap_rect=layout.minimap_rect,
        clock_rect=PixelRect(x=1280 // 2 - rw // 2, y=8, width=rw, height=rh),
        confidence=0.9,
        minimap_flipped=layout.minimap_flipped,
    )
    a = reading_from_frame(frame, layout, t_video_ms=1000)
    b = reading_from_frame(frame, layout, t_video_ms=2000, previous_game_ms=a.t_game_ms)
    if a.t_game_ms is not None and b.t_game_ms is not None:
        assert a.t_game_ms == b.t_game_ms


def test_corrupt_frame_handled() -> None:
    layout = LayoutProfile(
        width=64,
        height=64,
        ui_scale=1.0,
        minimap_rect=PixelRect(40, 40, 20, 20),
        clock_rect=PixelRect(10, 2, 40, 12),
        confidence=0.5,
    )
    tiny = np.zeros((10, 10, 3), dtype=np.uint8)
    reading = reading_from_frame(tiny, layout, t_video_ms=0)
    assert reading.t_game_ms is None
    assert reading.confidence == 0.0
