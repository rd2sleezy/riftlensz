"""Build concept histories and trends from historical games."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from riftlens.coaching.longitudinal.config import (
    DEFAULT_LONGITUDINAL_CONFIG,
    LongitudinalCoachingConfig,
)
from riftlens.coaching.longitudinal.models import (
    CoachingScope,
    ConceptGameObservation,
    ConceptHistory,
    HistoricalCoachingGame,
    ObjectiveEvaluation,
    OpportunityStatus,
    PatternStatus,
    ReasonCode,
    ScopeLevel,
    StrengthHistory,
    StrengthStatus,
    TrendState,
)
from riftlens.coaching.longitudinal.objective_eval import evaluate_practice_objective
from riftlens.coaching.teaching.models import PracticeObjective


def scopes_compatible(left: CoachingScope, right: CoachingScope) -> bool:
    """Role-level histories do not mix incompatible roles."""
    if left.level is ScopeLevel.GLOBAL or right.level is ScopeLevel.GLOBAL:
        return True
    if left.role and right.role and left.role != right.role:
        return False
    if (
        left.level is ScopeLevel.CHAMPION
        and right.level is ScopeLevel.CHAMPION
        and left.champion
        and right.champion
        and left.champion != right.champion
    ):
        return False
    return True


def derive_longitudinal_trend(
    observations: Sequence[ConceptGameObservation],
    *,
    config: LongitudinalCoachingConfig | None = None,
) -> TrendState:
    """Derive trend from comparable opportunity observations only.

    Win/loss is ignored. Missing opportunities are excluded.
    """
    cfg = config or DEFAULT_LONGITUDINAL_CONFIG
    usable = [
        item
        for item in observations
        if item.opportunity_status is OpportunityStatus.OBSERVED_OPPORTUNITY
    ]
    if len(usable) < cfg.improving_min_comparable:
        return TrendState.UNKNOWN

    # Prefer measurable_metric; else occurrence_count
    metrics: list[float] = []
    for item in usable:
        if item.measurable_metric is not None:
            metrics.append(float(item.measurable_metric))
        else:
            metrics.append(float(item.occurrence_count))

    split = max(1, len(metrics) // 2)
    prior = metrics[:-split] or metrics[:1]
    recent = metrics[-split:]
    prior_avg = sum(prior) / len(prior)
    recent_avg = sum(recent) / len(recent)
    if prior_avg <= 1e-9:
        if recent_avg <= prior_avg:
            return TrendState.STABLE
        return TrendState.REGRESSING

    drop = (prior_avg - recent_avg) / prior_avg
    rise = (recent_avg - prior_avg) / prior_avg
    if drop >= cfg.improving_drop_ratio:
        return TrendState.IMPROVING
    if rise >= cfg.regressing_rise_ratio:
        return TrendState.REGRESSING
    if abs(drop) <= cfg.stable_band or abs(rise) <= cfg.stable_band:
        return TrendState.STABLE
    return TrendState.UNKNOWN


def _pattern_status(
    *,
    opportunity_games: int,
    negative_games: int,
    trend: TrendState,
    is_active: bool,
    resolved: bool,
    config: LongitudinalCoachingConfig,
) -> tuple[PatternStatus, list[ReasonCode]]:
    codes: list[ReasonCode] = []
    if opportunity_games <= 0:
        return PatternStatus.INSUFFICIENT_EVIDENCE, [
            ReasonCode("INSUFFICIENT_OBSERVATION_OPPORTUNITY")
        ]
    if resolved:
        return PatternStatus.RESOLVED, [ReasonCode("FOCUS_RESOLVED")]
    if is_active and trend is TrendState.IMPROVING:
        codes.append(ReasonCode("TREND_IMPROVING"))
        return PatternStatus.IMPROVING, codes
    if is_active and trend is TrendState.REGRESSING:
        codes.append(ReasonCode("TREND_REGRESSING"))
        return PatternStatus.REGRESSING, codes
    if is_active:
        return PatternStatus.ACTIVE_FOCUS, [ReasonCode("KEEP_ACTIVE_FOCUS")]
    if (
        opportunity_games >= config.recurring_min_games
        and negative_games / max(opportunity_games, 1)
        >= config.recurring_min_negative_ratio
    ):
        codes.append(ReasonCode("REPEATED_ACROSS_GAMES"))
        return PatternStatus.RECURRING, codes
    if opportunity_games >= config.emerging_min_games and negative_games >= 1:
        return PatternStatus.EMERGING, [ReasonCode("EMERGING_PATTERN")]
    if negative_games == 1 and opportunity_games == 1:
        return PatternStatus.NEW, [ReasonCode("FIRST_SUPPORTED_OCCURRENCE")]
    if negative_games == 0:
        return PatternStatus.INSUFFICIENT_EVIDENCE, [
            ReasonCode("ONE_OFF_NOT_HABIT")
            if opportunity_games < config.recurring_min_games
            else ReasonCode("NO_NEGATIVE_PATTERN")
        ]
    return PatternStatus.NEW, [ReasonCode("FIRST_SUPPORTED_OCCURRENCE")]


def build_concept_history(
    games: Sequence[HistoricalCoachingGame],
    concept_id: str,
    *,
    scope: CoachingScope,
    config: LongitudinalCoachingConfig | None = None,
    objective: PracticeObjective | None = None,
    active_concept_id: str | None = None,
    force_resolved: bool = False,
) -> ConceptHistory:
    """Aggregate one concept across compatible games in chronological order."""
    cfg = config or DEFAULT_LONGITUDINAL_CONFIG
    ordered = sorted(games, key=lambda item: (item.played_at_ms, item.match_id))
    ordered = ordered[-cfg.max_games :]

    observations: list[ConceptGameObservation] = []
    evaluations: list[ObjectiveEvaluation] = []
    for game in ordered:
        game_scope = CoachingScope(
            level=scope.level,
            role=game.role,
            champion=game.champion if scope.level is ScopeLevel.CHAMPION else None,
            queue_type=game.queue_type,
        )
        if not scopes_compatible(scope, game_scope):
            continue
        for obs in game.concept_observations:
            if obs.concept_id != concept_id:
                continue
            if not scopes_compatible(scope, obs.scope):
                continue
            observations.append(obs)
        if objective is not None and objective.concept_id == concept_id:
            evaluations.append(
                evaluate_practice_objective(objective, game, config=cfg)
            )

    opportunity_games = sum(
        1
        for item in observations
        if item.opportunity_status is OpportunityStatus.OBSERVED_OPPORTUNITY
    )
    negative_games = sum(
        1
        for item in observations
        if item.opportunity_status is OpportunityStatus.OBSERVED_OPPORTUNITY
        and (
            item.occurrence_count > 0
            or item.polarity in {"CONSISTENT_NEGATIVE", "MIXED"}
        )
    )
    positive_games = sum(
        1
        for item in observations
        if item.opportunity_status is OpportunityStatus.OBSERVED_OPPORTUNITY
        and item.polarity == "CONSISTENT_POSITIVE"
        and item.occurrence_count >= 0
        and item.concept_id.startswith("strength.")
    )
    # For non-strength: positive = opportunity with zero negative occurrences
    if not concept_id.startswith("strength."):
        positive_games = sum(
            1
            for item in observations
            if item.opportunity_status is OpportunityStatus.OBSERVED_OPPORTUNITY
            and item.occurrence_count <= 0
        )
    mixed_games = sum(1 for item in observations if item.polarity == "MIXED")
    unknown_games = sum(
        1
        for item in observations
        if item.opportunity_status
        in {
            OpportunityStatus.UNKNOWN_OPPORTUNITY,
            OpportunityStatus.NO_OBSERVABLE_OPPORTUNITY,
        }
    )
    total_occ = sum(item.occurrence_count for item in observations)
    trend = derive_longitudinal_trend(observations, config=cfg)
    status, codes = _pattern_status(
        opportunity_games=opportunity_games,
        negative_games=negative_games,
        trend=trend,
        is_active=active_concept_id == concept_id,
        resolved=force_resolved,
        config=cfg,
    )
    if len(observations) == 1 and status is PatternStatus.NEW:
        codes.append(ReasonCode("ONE_OFF_NOT_HABIT"))

    conf = min(
        cfg.confidence_cap, opportunity_games * cfg.confidence_per_opportunity_game
    )
    support = "INSUFFICIENT"
    if opportunity_games >= cfg.recurring_min_games:
        support = "MODERATE"
    elif opportunity_games >= 1:
        support = "WEAK"

    return ConceptHistory(
        concept_id=concept_id,
        scope=scope,
        status=status,
        trend=trend,
        games_observed=len({item.match_id for item in observations}),
        games_with_opportunity=opportunity_games,
        negative_games=negative_games,
        positive_games=positive_games,
        mixed_games=mixed_games,
        unknown_games=unknown_games,
        total_occurrences=total_occ,
        support_level=support,
        confidence=conf,
        first_match_id=observations[0].match_id if observations else None,
        latest_match_id=observations[-1].match_id if observations else None,
        observations=tuple(observations),
        evaluations=tuple(evaluations),
        reason_codes=tuple(codes),
        gaps=(),
    )


def build_strength_histories(
    games: Sequence[HistoricalCoachingGame],
    *,
    scope: CoachingScope,
    config: LongitudinalCoachingConfig | None = None,
) -> tuple[StrengthHistory, ...]:
    """Track repeated positive strength concepts conservatively."""
    cfg = config or DEFAULT_LONGITUDINAL_CONFIG
    counts: dict[str, int] = defaultdict(int)
    for game in games:
        game_scope = CoachingScope(
            level=scope.level, role=game.role, queue_type=game.queue_type
        )
        if not scopes_compatible(scope, game_scope):
            continue
        for concept_id in game.strength_concept_ids:
            counts[concept_id] += 1
    rows: list[StrengthHistory] = []
    for concept_id, n in sorted(counts.items()):
        if n >= cfg.recurring_min_games:
            status = StrengthStatus.CONSISTENT_STRENGTH
        elif n >= cfg.emerging_min_games:
            status = StrengthStatus.EMERGING_STRENGTH
        else:
            status = StrengthStatus.POSITIVE_SIGNAL
        rows.append(
            StrengthHistory(
                concept_id=concept_id,
                status=status,
                positive_games=n,
                reason_codes=(ReasonCode("STRENGTH_HISTORY", f"games={n}"),),
            )
        )
    return tuple(rows)
