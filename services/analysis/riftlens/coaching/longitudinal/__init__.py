"""C.6 longitudinal coaching, habit tracking, and active curriculum."""

from __future__ import annotations

from riftlens.coaching.longitudinal.builder import (
    apply_game_loop,
    build_player_coaching_state,
)
from riftlens.coaching.longitudinal.config import (
    DEFAULT_LONGITUDINAL_CONFIG,
    LongitudinalCoachingConfig,
    with_longitudinal_overrides,
)
from riftlens.coaching.longitudinal.focus import (
    build_pre_game_focus,
    update_active_focus,
)
from riftlens.coaching.longitudinal.history import (
    build_concept_history,
    build_strength_histories,
    derive_longitudinal_trend,
    scopes_compatible,
)
from riftlens.coaching.longitudinal.models import (
    LONGITUDINAL_METHOD,
    LONGITUDINAL_METHOD_VERSION,
    LONGITUDINAL_SCHEMA_VERSION,
    ActiveFocus,
    CoachingProfile,
    CoachingScope,
    ConceptGameObservation,
    ConceptHistory,
    FocusDecision,
    FocusUpdate,
    HistoricalCoachingGame,
    ObjectiveEvaluation,
    ObjectiveResult,
    OpportunityStatus,
    PatternStatus,
    PlayerCoachingState,
    PreGameFocus,
    ReasonCode,
    ScopeLevel,
    StrengthHistory,
    StrengthStatus,
    TrendState,
    empty_player_state,
)
from riftlens.coaching.longitudinal.objective_eval import evaluate_practice_objective

__all__ = [
    "DEFAULT_LONGITUDINAL_CONFIG",
    "LONGITUDINAL_METHOD",
    "LONGITUDINAL_METHOD_VERSION",
    "LONGITUDINAL_SCHEMA_VERSION",
    "ActiveFocus",
    "CoachingProfile",
    "CoachingScope",
    "ConceptGameObservation",
    "ConceptHistory",
    "FocusDecision",
    "FocusUpdate",
    "HistoricalCoachingGame",
    "LongitudinalCoachingConfig",
    "ObjectiveEvaluation",
    "ObjectiveResult",
    "OpportunityStatus",
    "PatternStatus",
    "PlayerCoachingState",
    "PreGameFocus",
    "ReasonCode",
    "ScopeLevel",
    "StrengthHistory",
    "StrengthStatus",
    "TrendState",
    "apply_game_loop",
    "build_concept_history",
    "build_player_coaching_state",
    "build_pre_game_focus",
    "build_strength_histories",
    "derive_longitudinal_trend",
    "empty_player_state",
    "evaluate_practice_objective",
    "scopes_compatible",
    "update_active_focus",
    "with_longitudinal_overrides",
]
