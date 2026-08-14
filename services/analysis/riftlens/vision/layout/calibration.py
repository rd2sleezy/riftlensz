"""Thin calibration helpers for H.9.1 layout profiles."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from riftlens.domain.layout_profile import LayoutProfile
from riftlens.vision.layout.detect_layout import detect_layout

BgrImage = NDArray[np.uint8]


def calibrate_layout(frames: Sequence[BgrImage]) -> LayoutProfile:
    """Calibrate layout once per VOD from sample frames."""
    return detect_layout(frames)
