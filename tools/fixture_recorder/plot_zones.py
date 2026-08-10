from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

_ANALYSIS_ROOT = Path(__file__).resolve().parents[2] / "services" / "analysis"
if str(_ANALYSIS_ROOT) not in sys.path:
    sys.path.insert(0, str(_ANALYSIS_ROOT))

from riftlens.domain.geometry import (  # noqa: E402
    MAP_X_MAX,
    MAP_X_MIN,
    MAP_Y_MAX,
    MAP_Y_MIN,
    zone_polygons,
)

_COLORS = [
    (60, 90, 200),
    (200, 70, 70),
    (40, 180, 80),
    (40, 200, 200),
    (200, 180, 40),
    (160, 80, 200),
    (80, 160, 220),
    (30, 90, 40),
    (50, 120, 70),
    (90, 40, 40),
    (120, 50, 50),
    (20, 60, 120),
    (20, 100, 140),
]


def _world_to_px(x: float, y: float, width: int, height: int) -> tuple[int, int]:
    px = int((x - MAP_X_MIN) / (MAP_X_MAX - MAP_X_MIN) * (width - 1))
    py = int((1.0 - (y - MAP_Y_MIN) / (MAP_Y_MAX - MAP_Y_MIN)) * (height - 1))
    return px, py


def render_zones(map_image: Path | None, out_path: Path, size: int = 1024) -> Path:
    """Write a PNG of named SR zones. Assumes world bounds match geometry constants."""
    if map_image is not None:
        canvas = cv2.imread(str(map_image), cv2.IMREAD_COLOR)
        if canvas is None:
            raise FileNotFoundError(map_image)
    else:
        canvas = np.full((size, size, 3), 28, dtype=np.uint8)
    height, width = canvas.shape[:2]
    overlay = canvas.copy()
    for index, (name, polygon) in enumerate(zone_polygons().items()):
        pts = np.array(
            [_world_to_px(point.x, point.y, width, height) for point in polygon],
            dtype=np.int32,
        )
        color = _COLORS[index % len(_COLORS)]
        cv2.fillPoly(overlay, [pts], color)
        cv2.polylines(canvas, [pts], isClosed=True, color=(240, 240, 240), thickness=2)
        centroid = pts.mean(axis=0).astype(int)
        cv2.putText(
            canvas,
            name,
            (int(centroid[0]) - 40, int(centroid[1])),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    blended = cv2.addWeighted(overlay, 0.35, canvas, 0.65, 0)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(out_path), blended):
        raise RuntimeError(f"failed to write {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render Summoner's Rift zone polygons for eyeballing."
    )
    parser.add_argument("--map", type=Path, default=None, help="Optional background map image.")
    parser.add_argument("--out", type=Path, default=Path("zones_preview.png"))
    parser.add_argument("--size", type=int, default=1024)
    args = parser.parse_args()
    path = render_zones(args.map, args.out, size=args.size)
    print(path)


if __name__ == "__main__":
    main()
