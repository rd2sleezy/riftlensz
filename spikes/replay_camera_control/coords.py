"""Riot map ↔ Replay API camera coordinate helpers (spike-only)."""

from __future__ import annotations

from typing import Any


def riot_xy_to_camera_position(
    x: float,
    y: float,
    *,
    height: float = 1910.0,
) -> dict[str, float]:
    """Map Riot timeline ``(x, y)`` ground coords to Replay API ``cameraPosition``.

    Observed Mac render uses ``{x, y=height, z}`` with ground on xz. Assumes
    Riot ``y`` maps to camera ``z`` (standard League Director convention).
    """
    return {"x": float(x), "y": float(height), "z": float(y)}


def camera_position_to_riot_xy(pos: dict[str, Any] | None) -> tuple[float, float] | None:
    """Inverse of ``riot_xy_to_camera_position`` when ``pos`` has x/z."""
    if not isinstance(pos, dict):
        return None
    try:
        return float(pos["x"]), float(pos["z"])
    except (KeyError, TypeError, ValueError):
        return None


def ground_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Euclidean distance on the Riot ground plane."""
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
