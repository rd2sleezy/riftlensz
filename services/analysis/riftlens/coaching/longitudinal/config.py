"""Provisional C.6 longitudinal configuration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class LongitudinalCoachingConfig:
    """Versioned provisional thresholds for longitudinal coaching.

    Not scientifically calibrated — explainable and testable.
    """

    version: str = "c6.0-provisional-1"

    # History window
    max_games: int = 20
    recent_window: int = 5

    # Pattern thresholds (independent games with opportunity)
    emerging_min_games: int = 2
    recurring_min_games: int = 3
    recurring_min_negative_ratio: float = 0.5

    # Trend (comparable opportunity games only)
    improving_min_comparable: int = 3
    improving_drop_ratio: float = 0.35  # recent avg metric <= prior * (1-drop)
    regressing_rise_ratio: float = 0.35
    stable_band: float = 0.20

    # Resolution
    resolve_min_success_evals: int = 2
    resolve_min_opportunity_games: int = 2
    resolve_max_recent_failures: int = 0
    resolve_cooldown_games: int = 2

    # Focus hysteresis
    focus_switch_margin: float = 15.0  # learning-value margin required to switch
    min_focus_continuity_games: int = 2
    allow_multiple_primary_focuses: bool = False  # always one primary

    # Confidence
    confidence_per_opportunity_game: float = 0.15
    confidence_cap: float = 0.9

    # Blocked concepts that cannot become measurable active focuses
    blocked_concepts: tuple[str, ...] = (
        "wave.management",
        "mechanics.execution",
        "combat.summoner_usage",
        "risk.information_discipline",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "max_games": self.max_games,
            "recent_window": self.recent_window,
            "emerging_min_games": self.emerging_min_games,
            "recurring_min_games": self.recurring_min_games,
            "focus_switch_margin": self.focus_switch_margin,
            "resolve_min_success_evals": self.resolve_min_success_evals,
        }


DEFAULT_LONGITUDINAL_CONFIG = LongitudinalCoachingConfig()


def with_longitudinal_overrides(
    base: LongitudinalCoachingConfig | None = None,
    **overrides: Any,
) -> LongitudinalCoachingConfig:
    """Return config with selected overrides."""
    return replace(base or DEFAULT_LONGITUDINAL_CONFIG, **overrides)
