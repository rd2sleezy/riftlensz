"""Unit tests for spike coordinate helpers (no League client)."""

from __future__ import annotations

import sys
from pathlib import Path

SPIKE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SPIKE))

from coords import camera_position_to_riot_xy, ground_distance, riot_xy_to_camera_position


def test_riot_xy_maps_to_camera_xz() -> None:
    cam = riot_xy_to_camera_position(1591.0, 9726.0, height=1910.0)
    assert cam == {"x": 1591.0, "y": 1910.0, "z": 9726.0}
    back = camera_position_to_riot_xy(cam)
    assert back == (1591.0, 9726.0)


def test_ground_distance() -> None:
    assert ground_distance((0.0, 0.0), (3.0, 4.0)) == 5.0
