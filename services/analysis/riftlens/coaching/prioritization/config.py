"""Provisional C.4 learning-value configuration.

Weights are intentionally provisional — not scientifically calibrated.
They exist to make ranking explainable and config-driven.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class LearningValueConfig:
    """Versioned deterministic learning-value knobs.

    Does NOT include a required major_count. Thresholds decide how many
    lessons qualify. ``max_major_safety_cap`` is a pathological-output guard
    only — not a normal selection target.
    """

    version: str = "c4.0-provisional-1"

    # Evidence support (additive)
    support_strong: float = 35.0
    support_moderate: float = 22.0
    support_weak: float = 8.0
    support_insufficient: float = 0.0

    # Within-match recurrence
    recurrence_per_occurrence: float = 6.0
    recurrence_cap: float = 18.0
    # Deduplicate occurrences that share all episode ids (avoid double count)
    recurrence_use_episode_count: bool = True

    # Impact (gold-equivalent style). Cap prevents impact domination.
    impact_weight: float = 0.02
    impact_cap: float = 18.0
    default_impact: float = 40.0

    # Causal leverage (C.3 has zero SUPPORTED contracts today)
    causal_plausible_bonus: float = 4.0
    causal_supported_bonus: float = 12.0
    causal_plausible_cap: float = 8.0
    causal_supported_cap: float = 24.0

    # Actionability
    not_actionable_penalty: float = -25.0
    # UNKNOWN actionability → 0 (not treated as actionable)

    # Teachability (0..1 prior × weight)
    teachability_weight: float = 14.0
    default_teachability: float = 0.7

    # Specificity
    specificity_specific: float = 6.0
    specificity_general: float = 10.0
    specificity_broad: float = 2.0
    specificity_unresolved: float = -8.0
    # Penalize SPECIFIC when support is weak/insufficient
    unsupported_specificity_penalty: float = -15.0

    # Capability readiness
    capability_blocked_penalty: float = -45.0
    capability_partial_bonus: float = 0.0
    capability_ready_bonus: float = 2.0
    capability_unknown_penalty: float = -5.0

    # Conflicts / gaps / resolution
    conflict_mixed_penalty: float = -12.0
    gap_penalty_per_item: float = -2.5
    gap_penalty_cap: float = -12.0
    # Material gap tokens that always count for jungle/vision-style claims
    material_gap_tokens: tuple[str, ...] = (
        "true_player_fog_or_vision",
        "ward_positions_and_coverage",
        "minion_counts_hp_wave_direction",
        "pov_mechanical_or_visual_evidence",
        "summoner_loadout_and_cooldown_state",
        "PLAYER_COULD_NOT_SEE_JUNGLER",
        "FAILED_JUNGLE_TRACKING",
        "WAVE_MANAGEMENT_ERROR",
        "WARD_COVERAGE_QUALITY",
    )
    resolution_penalty: float = -8.0

    # Role / rank priors (optional; neutral when absent)
    role_relevance_weight: float = 5.0
    rank_relevance_weight: float = 8.0
    default_role_relevance: float = 0.0  # additive offset from 0 baseline
    default_rank_relevance: float = 1.0  # multiplier-like 0..1 → contribution

    # Thresholds (evidence-driven counts)
    major_threshold: float = 42.0
    secondary_threshold: float = 24.0
    strength_threshold: float = 18.0

    # INSUFFICIENT support cannot be MAJOR
    block_major_if_insufficient_support: bool = True
    # BLOCKED readiness / capability cannot be MAJOR
    block_major_if_capability_blocked: bool = True
    block_major_if_readiness_blocked: bool = True
    block_major_if_not_actionable: bool = True

    # Redundancy
    duplicative_jaccard: float = 0.85
    high_overlap_jaccard: float = 0.55
    related_jaccard: float = 0.25
    redundancy_penalty_duplicative: float = -40.0
    redundancy_penalty_high_overlap: float = -22.0
    redundancy_penalty_related: float = -6.0
    # Same domain alone is NOT automatic duplicate
    same_domain_related_bonus_jaccard: float = 0.05

    # Safety cap only (not a quota). None disables.
    max_major_safety_cap: int | None = 8
    max_secondary_safety_cap: int | None = 12
    max_strength_safety_cap: int | None = 8

    # Diversity is tie-break only — never forces weak promotion
    diversity_tiebreak_epsilon: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "major_threshold": self.major_threshold,
            "secondary_threshold": self.secondary_threshold,
            "strength_threshold": self.strength_threshold,
            "max_major_safety_cap": self.max_major_safety_cap,
            "support_strong": self.support_strong,
            "support_moderate": self.support_moderate,
            "impact_cap": self.impact_cap,
            "recurrence_cap": self.recurrence_cap,
        }


DEFAULT_LEARNING_VALUE_CONFIG = LearningValueConfig()


def with_config_overrides(
    base: LearningValueConfig | None = None,
    **overrides: Any,
) -> LearningValueConfig:
    """Return config with selected fields overridden (tests / sensitivity)."""
    cfg = base or DEFAULT_LEARNING_VALUE_CONFIG
    return replace(cfg, **overrides)
