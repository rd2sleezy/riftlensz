"""Glyph atlas loader for classical digit OCR (H.9.1)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

GrayImage = NDArray[np.uint8]

_GLYPH_NAMES = {
    "0": "0.png",
    "1": "1.png",
    "2": "2.png",
    "3": "3.png",
    "4": "4.png",
    "5": "5.png",
    "6": "6.png",
    "7": "7.png",
    "8": "8.png",
    "9": "9.png",
    ":": "colon.png",
}


def default_glyphs_root() -> Path:
    """Return ``riftlens/resources/vision/glyphs`` next to the package resources."""
    return Path(__file__).resolve().parents[2] / "resources" / "vision" / "glyphs"


@dataclass(frozen=True)
class GlyphAtlas:
    """One glyph height's templates. Source may be SYNTHETIC or LEAGUE_CROP."""

    height_px: int
    templates: dict[str, GrayImage]
    source: str

    def available(self) -> bool:
        return bool(self.templates) and all(ch in self.templates for ch in _GLYPH_NAMES)


def load_atlas(height_px: int, *, root: Path | None = None) -> GlyphAtlas:
    """Load PNGs for ``height_px``. Missing files yield an empty templates map."""
    base = (root or default_glyphs_root()) / f"{height_px}px"
    templates: dict[str, GrayImage] = {}
    source = "unknown"
    source_file = base / "SOURCE.txt"
    if source_file.is_file():
        source = source_file.read_text(encoding="utf-8").strip().splitlines()[0][:120]
    if not base.is_dir():
        return GlyphAtlas(height_px=height_px, templates={}, source=source)
    for ch, filename in _GLYPH_NAMES.items():
        path = base / filename
        if not path.is_file():
            continue
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None or img.size == 0:
            continue
        templates[ch] = np.asarray(img, dtype=np.uint8)
    return GlyphAtlas(height_px=height_px, templates=templates, source=source)


def choose_atlas(
    roi_height: int,
    *,
    root: Path | None = None,
    prefer_league: bool = True,
) -> GlyphAtlas:
    """Pick the closest atlas height. Prefer ``glyphs/league/`` when available."""
    root = root or default_glyphs_root()
    if prefer_league:
        league_root = root / "league"
        if league_root.is_dir():
            league = _choose_height(roi_height, league_root)
            if league.available():
                return league
    return _choose_height(roi_height, root)


def _choose_height(roi_height: int, root: Path) -> GlyphAtlas:
    candidates = sorted(
        int(p.name.replace("px", ""))
        for p in root.glob("*px")
        if p.is_dir() and p.name[:-2].isdigit()
    )
    if not candidates:
        return GlyphAtlas(height_px=roi_height, templates={}, source="missing")
    best = min(candidates, key=lambda h: abs(h - max(8, roi_height)))
    return load_atlas(best, root=root)
