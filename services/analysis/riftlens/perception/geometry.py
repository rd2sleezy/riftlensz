"""Normalized screen geometry and ROI definitions for RP.1."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from riftlens.domain.observation.common import ScreenRect
from riftlens.perception.models import NormalizedPoint, NormalizedRect
from riftlens.visual.hud_mask import hud_rects


class LayoutSupport(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


# Fractions match V.2 HUD mask intent (resolution-relative).
_ROI_FRACTIONS: dict[str, tuple[float, float, float, float]] = {
    # x, y, w, h as fractions of full frame
    "gameplay_viewport": (0.02, 0.08, 0.96, 0.74),
    "player_hud": (0.28, 0.84, 0.44, 0.16),
    "ability_bar": (0.34, 0.90, 0.24, 0.08),
    "resource_hp_area": (0.36, 0.86, 0.20, 0.04),
    "item_area": (0.58, 0.90, 0.14, 0.08),
    "minimap": (0.00, 0.68, 0.18, 0.32),
    "scoreboard": (0.78, 0.00, 0.22, 0.08),
    "top_objective_ui": (0.35, 0.00, 0.30, 0.08),
}

_ABILITY_SLOTS: tuple[tuple[str, float, float, float, float], ...] = (
    # Relative to ability_bar ROI: Q W E R then summoners
    ("Q", 0.00, 0.15, 0.18, 0.70),
    ("W", 0.20, 0.15, 0.18, 0.70),
    ("E", 0.40, 0.15, 0.18, 0.70),
    ("R", 0.60, 0.15, 0.18, 0.70),
    ("SUMMONER_1", 0.80, 0.05, 0.10, 0.45),
    ("SUMMONER_2", 0.80, 0.50, 0.10, 0.45),
)

_ITEM_SLOTS: tuple[tuple[str, float, float, float, float], ...] = tuple(
    (f"ITEM_{index}", index * 0.16, 0.15, 0.15, 0.70) for index in range(6)
)

# Layouts we have exercised with classical CV (V.0–V.6 captures).
_SUPPORTED_MIN_WIDTH = 320
_SUPPORTED_MIN_HEIGHT = 180
_SUPPORTED_MAX_WIDTH = 3840
_SUPPORTED_MAX_HEIGHT = 2160


@dataclass(frozen=True)
class ScreenGeometry:
    """Pixel ↔ normalized conversion for one frame size."""

    width: int
    height: int
    layout_support: LayoutSupport
    layout_notes: str = ""

    @classmethod
    def from_frame(cls, width: int, height: int) -> ScreenGeometry:
        if width <= 0 or height <= 0:
            return cls(
                width=max(0, width),
                height=max(0, height),
                layout_support=LayoutSupport.UNSUPPORTED,
                layout_notes="non-positive frame dimensions",
            )
        if (
            width < _SUPPORTED_MIN_WIDTH
            or height < _SUPPORTED_MIN_HEIGHT
            or width > _SUPPORTED_MAX_WIDTH
            or height > _SUPPORTED_MAX_HEIGHT
        ):
            return cls(
                width=width,
                height=height,
                layout_support=LayoutSupport.UNSUPPORTED,
                layout_notes=(
                    f"frame {width}x{height} outside supported "
                    f"{_SUPPORTED_MIN_WIDTH}x{_SUPPORTED_MIN_HEIGHT}–"
                    f"{_SUPPORTED_MAX_WIDTH}x{_SUPPORTED_MAX_HEIGHT}"
                ),
            )
        return cls(
            width=width,
            height=height,
            layout_support=LayoutSupport.SUPPORTED,
            layout_notes="resolution-relative ROI fractions (V.2-compatible)",
        )

    def normalize_point(self, x: float, y: float) -> NormalizedPoint:
        if self.width <= 0 or self.height <= 0:
            return NormalizedPoint(0.0, 0.0)
        return NormalizedPoint(
            x=round(float(x) / float(self.width), 6),
            y=round(float(y) / float(self.height), 6),
        )

    def denormalize_point(self, point: NormalizedPoint) -> tuple[int, int]:
        return (
            int(round(point.x * self.width)),
            int(round(point.y * self.height)),
        )

    def normalize_rect(self, rect: ScreenRect) -> NormalizedRect:
        if self.width <= 0 or self.height <= 0:
            return NormalizedRect(0.0, 0.0, 0.0, 0.0)
        return NormalizedRect(
            x=round(rect.x / float(self.width), 6),
            y=round(rect.y / float(self.height), 6),
            width=round(rect.width / float(self.width), 6),
            height=round(rect.height / float(self.height), 6),
        )

    def denormalize_rect(self, rect: NormalizedRect) -> ScreenRect:
        x = int(round(rect.x * self.width))
        y = int(round(rect.y * self.height))
        width = int(round(rect.width * self.width))
        height = int(round(rect.height * self.height))
        return ScreenRect(x=x, y=y, width=max(0, width), height=max(0, height))

    def roi(self, name: str) -> ScreenRect | None:
        """Return a named ROI, or None when layout is unsupported / unknown name."""
        if self.layout_support is LayoutSupport.UNSUPPORTED:
            return None
        frac = _ROI_FRACTIONS.get(name)
        if frac is None:
            return None
        return self._frac_rect(*frac)

    def all_rois(self) -> dict[str, ScreenRect]:
        if self.layout_support is LayoutSupport.UNSUPPORTED:
            return {}
        return {name: self._frac_rect(*frac) for name, frac in _ROI_FRACTIONS.items()}

    def masked_hud_bands(self) -> tuple[ScreenRect, ...]:
        """Reuse V.2 HUD mask bands for the current size."""
        return hud_rects(self.width, self.height)

    def ability_slot_rects(self) -> tuple[tuple[str, ScreenRect], ...]:
        bar = self.roi("ability_bar")
        if bar is None:
            return ()
        return tuple(
            (slot_id, self._nested(bar, fx, fy, fw, fh))
            for slot_id, fx, fy, fw, fh in _ABILITY_SLOTS
        )

    def item_slot_rects(self) -> tuple[tuple[str, ScreenRect], ...]:
        area = self.roi("item_area")
        if area is None:
            return ()
        return tuple(
            (slot_id, self._nested(area, fx, fy, fw, fh))
            for slot_id, fx, fy, fw, fh in _ITEM_SLOTS
        )

    def _frac_rect(self, fx: float, fy: float, fw: float, fh: float) -> ScreenRect:
        x = int(round(fx * self.width))
        y = int(round(fy * self.height))
        width = max(1, int(round(fw * self.width)))
        height = max(1, int(round(fh * self.height)))
        x = max(0, min(x, max(0, self.width - 1)))
        y = max(0, min(y, max(0, self.height - 1)))
        width = min(width, self.width - x)
        height = min(height, self.height - y)
        return ScreenRect(x=x, y=y, width=width, height=height)

    def _nested(
        self,
        parent: ScreenRect,
        fx: float,
        fy: float,
        fw: float,
        fh: float,
    ) -> ScreenRect:
        x = parent.x + int(round(fx * parent.width))
        y = parent.y + int(round(fy * parent.height))
        width = max(1, int(round(fw * parent.width)))
        height = max(1, int(round(fh * parent.height)))
        return ScreenRect(x=x, y=y, width=width, height=height)
