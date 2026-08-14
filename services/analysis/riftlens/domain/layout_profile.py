"""Runtime LayoutProfile for H.9.1 clock OCR. Maps to LayoutProfileRecord."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from riftlens.domain.ports import LayoutProfileRecord


@dataclass(frozen=True)
class PixelRect:
    """Axis-aligned pixel rectangle. Inclusive origin, exclusive conceptually for crops."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        for name, value in (
            ("x", self.x),
            ("y", self.y),
            ("width", self.width),
            ("height", self.height),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be int")
            if name in {"width", "height"} and value <= 0:
                raise ValueError(f"{name} must be positive")

    def clamp(self, frame_w: int, frame_h: int) -> PixelRect:
        """Return a rect clipped to the frame. Assumes positive frame size."""
        x = max(0, min(self.x, max(0, frame_w - 1)))
        y = max(0, min(self.y, max(0, frame_h - 1)))
        w = max(1, min(self.width, frame_w - x))
        h = max(1, min(self.height, frame_h - y))
        return PixelRect(x=x, y=y, width=w, height=h)

    def to_list(self) -> list[int]:
        return [self.x, self.y, self.width, self.height]

    @classmethod
    def from_list(cls, values: list[object] | tuple[object, ...]) -> PixelRect:
        if len(values) != 4:
            raise ValueError("rect list must have 4 ints")
        coords: list[int] = []
        for item in values:
            if isinstance(item, bool) or not isinstance(item, (int, float, str)):
                raise TypeError("rect values must be numeric")
            coords.append(int(item))
        return cls(x=coords[0], y=coords[1], width=coords[2], height=coords[3])


@dataclass(frozen=True)
class LayoutProfile:
    """Per-VOD HUD geometry for clock OCR. Not a minimap gameplay model."""

    width: int
    height: int
    ui_scale: float
    minimap_rect: PixelRect
    clock_rect: PixelRect
    minimap_flipped: bool = False
    confidence: float = 0.0
    version: str = "h9.1"
    regions: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("frame dimensions must be positive")
        if self.ui_scale <= 0:
            raise ValueError("ui_scale must be positive")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be in [0, 1]")

    def to_record(self, *, profile_id: str, created_at: int) -> LayoutProfileRecord:
        """Serialize into the existing persistence shell."""
        regions = dict(self.regions or {})
        regions["version"] = self.version
        regions["confidence"] = self.confidence
        return LayoutProfileRecord(
            id=profile_id,
            width=self.width,
            height=self.height,
            ui_scale_estimate=float(self.ui_scale),
            minimap_flipped=1 if self.minimap_flipped else 0,
            minimap_rect=json.dumps(self.minimap_rect.to_list()),
            clock_rect=json.dumps(self.clock_rect.to_list()),
            regions=json.dumps(regions),
            occluded_regions=None,
            world_to_minimap_affine=None,
            created_at=created_at,
        )

    @classmethod
    def from_record(cls, row: LayoutProfileRecord) -> LayoutProfile:
        """Rebuild runtime profile from a persisted row."""
        regions_raw = json.loads(row.regions) if row.regions else {}
        if not isinstance(regions_raw, dict):
            regions_raw = {}
        conf = regions_raw.get("confidence", 0.0)
        version = str(regions_raw.get("version", "h9.1"))
        return cls(
            width=int(row.width or 0),
            height=int(row.height or 0),
            ui_scale=float(row.ui_scale_estimate or 1.0),
            minimap_rect=PixelRect.from_list(json.loads(row.minimap_rect)),
            clock_rect=PixelRect.from_list(json.loads(row.clock_rect)),
            minimap_flipped=bool(row.minimap_flipped),
            confidence=float(conf) if isinstance(conf, (int, float)) else 0.0,
            version=version,
            regions=regions_raw,
        )
