"""Resolution-relative HUD seeds for H.9.1 layout detection."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NormRect:
    """Normalized [0,1] rectangle: x, y, w, h relative to frame size."""

    x: float
    y: float
    w: float
    h: float


# Top-center scoreboard clock seeds (League HUD). Relative fractions.
CLOCK_SEEDS: tuple[NormRect, ...] = (
    NormRect(0.46, 0.005, 0.08, 0.045),
    NormRect(0.455, 0.0, 0.09, 0.05),
    NormRect(0.47, 0.01, 0.06, 0.04),
    NormRect(0.44, 0.0, 0.12, 0.055),
)

# Bottom-right minimap search band.
MINIMAP_BAND = NormRect(0.78, 0.68, 0.22, 0.32)


def supported_heights() -> tuple[int, ...]:
    """Heights the layout table is designed around (not a validation claim)."""
    return (720, 1080, 1440)
