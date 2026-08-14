"""Detector protocol for H.9.1 classical HUD readers."""

from __future__ import annotations

from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from riftlens.domain.layout_profile import LayoutProfile

BgrImage = NDArray[np.uint8]


class Detector(Protocol):
    """Pure frame+layout → observations. No I/O beyond loaded templates."""

    def detect(self, frame: BgrImage, layout: LayoutProfile) -> object:
        """Return detector-specific observations for ``frame``."""
