"""Build and update PlayerCoachingState from historical games."""

from __future__ import annotations

from collections.abc import Sequence

from riftlens.coaching.longitudinal.config import (
    DEFAULT_LONGITUDINAL_CONFIG,
    LongitudinalCoachingConfig,
)
from riftlens.coaching.longitudinal.focus import (
    build_pre_game_focus,
    update_active_focus,
)
from riftlens.coaching.longitudinal.history import (
    build_concept_history,
    build_strength_histories,
)
from riftlens.coaching.longitudinal.models import (
    LONGITUDINAL_METHOD,
    LONGITUDINAL_METHOD_VERSION,
    LONGITUDINAL_PRODUCER,
    LONGITUDINAL_PRODUCER_VERSION,
    LONGITUDINAL_SCHEMA_VERSION,
    ActiveFocus,
    CoachingProfile,
    CoachingScope,
    ConceptHistory,
    FocusUpdate,
    HistoricalCoachingGame,
    PatternStatus,
    PlayerCoachingState,
    PreGameFocus,
    ReasonCode,
    ScopeLevel,
    StrengthHistory,
    empty_player_state,
)
from riftlens.domain.fact import Provenance


def _collect_concept_ids(games: Sequence[HistoricalCoachingGame]) -> tuple[str, ...]:
    found: set[str] = set()
    for game in games:
        found.update(game.major_concept_ids)
        found.update(game.secondary_concept_ids)
        found.update(game.strength_concept_ids)
        for obs in game.concept_observations:
            found.add(obs.concept_id)
    return tuple(sorted(found))


def _profile_from(
    histories: Sequence[ConceptHistory],
    active: ActiveFocus | None,
    strengths: Sequence[StrengthHistory],
) -> CoachingProfile:
    recurring = tuple(
        item.concept_id
        for item in histories
        if item.status is PatternStatus.RECURRING
    )
    improving = tuple(
        item.concept_id
        for item in histories
        if item.status is PatternStatus.IMPROVING
    )
    resolved = tuple(
        item.concept_id
        for item in histories
        if item.status is PatternStatus.RESOLVED
    )
    watch = tuple(
        item.concept_id
        for item in histories
        if item.status in {PatternStatus.EMERGING, PatternStatus.NEW}
    )
    insufficient = tuple(
        item.concept_id
        for item in histories
        if item.status is PatternStatus.INSUFFICIENT_EVIDENCE
    )
    strength_ids = tuple(item.concept_id for item in strengths)
    return CoachingProfile(
        active_focus_concept_id=active.concept_id if active else None,
        recurring_concepts=recurring,
        improving_concepts=improving,
        resolved_concepts=resolved,
        watchlist_concepts=watch,
        persistent_strengths=strength_ids,
        insufficient_evidence_concepts=insufficient,
    )


def build_player_coaching_state(
    games: Sequence[HistoricalCoachingGame],
    *,
    player_key: str = "local",
    scope: CoachingScope | None = None,
    config: LongitudinalCoachingConfig | None = None,
    previous_state: PlayerCoachingState | None = None,
) -> PlayerCoachingState:
    """Derive longitudinal coaching state from explicit structured history.

    Empty history → empty state. Pure — no DB/network/LLM.
    Processes games chronologically, updating active focus with hysteresis.
    """
    cfg = config or DEFAULT_LONGITUDINAL_CONFIG
    if not games:
        return empty_player_state(
            player_key,
            scope=scope or CoachingScope(level=ScopeLevel.ROLE),
            config_version=cfg.version,
        )

    ordered = sorted(games, key=lambda item: (item.played_at_ms, item.match_id))
    ordered = ordered[-cfg.max_games :]
    sc = scope or CoachingScope(
        level=ScopeLevel.ROLE,
        role=ordered[-1].role,
        queue_type=ordered[-1].queue_type,
    )

    active: ActiveFocus | None = (
        previous_state.active_focus if previous_state else None
    )
    cooldown: list[str] = list(
        previous_state.resolved_cooldown_concepts if previous_state else ()
    )
    last_update: FocusUpdate | None = None

    # Walk games to maintain focus continuity
    for index in range(len(ordered)):
        window = ordered[: index + 1]
        concept_ids = _collect_concept_ids(window)
        histories_map = {
            concept_id: build_concept_history(
                window,
                concept_id,
                scope=sc,
                config=cfg,
                objective=(
                    active.objective
                    if active is not None and active.concept_id == concept_id
                    else None
                ),
                active_concept_id=active.concept_id if active else None,
            )
            for concept_id in concept_ids
        }
        game = ordered[index]
        active, last_update = update_active_focus(
            active,
            game,
            histories_map,
            scope=sc,
            config=cfg,
            resolved_cooldown=cooldown,
        )
        if (
            last_update is not None
            and last_update.decision.value in {"RESOLVE_FOCUS", "NO_NEW_FOCUS"}
            and last_update.before_concept_id
        ):
            cooldown.append(last_update.before_concept_id)
            # Keep only recent cooldown
            cooldown = cooldown[-cfg.resolve_cooldown_games * 3 :]

    # Final histories with active flag
    concept_ids = _collect_concept_ids(ordered)
    histories = tuple(
        build_concept_history(
            ordered,
            concept_id,
            scope=sc,
            config=cfg,
            objective=(
                active.objective
                if active is not None and active.concept_id == concept_id
                else None
            ),
            active_concept_id=active.concept_id if active else None,
            force_resolved=concept_id in cooldown
            and (active is None or active.concept_id != concept_id),
        )
        for concept_id in concept_ids
    )
    strengths = build_strength_histories(ordered, scope=sc, config=cfg)
    profile = _profile_from(histories, active, strengths)
    notes = [
        ReasonCode("LONGITUDINAL_STATE_BUILT", f"games={len(ordered)}"),
        ReasonCode("PROCESS_NOT_WINRATE"),
        ReasonCode("PERSISTENCE_DEFERRED"),
    ]
    if last_update is not None:
        notes.append(ReasonCode(last_update.decision.value))

    return PlayerCoachingState(
        schema_version=LONGITUDINAL_SCHEMA_VERSION,
        player_key=player_key,
        scope=sc,
        active_focus=active,
        concept_histories=histories,
        strengths=strengths,
        profile=profile,
        recent_match_ids=tuple(item.match_id for item in ordered[-cfg.recent_window :]),
        config_version=cfg.version,
        reason_codes=tuple(notes),
        gaps=("c_x_outputs_not_persisted_in_production_reviews",),
        provenance=Provenance(
            producer=LONGITUDINAL_PRODUCER,
            producer_version=LONGITUDINAL_PRODUCER_VERSION,
            upstream=tuple(item.match_id for item in ordered),
        ),
        resolved_cooldown_concepts=tuple(dict.fromkeys(cooldown)),
    )


def apply_game_loop(
    state: PlayerCoachingState | None,
    game: HistoricalCoachingGame,
    *,
    player_key: str = "local",
    scope: CoachingScope | None = None,
    config: LongitudinalCoachingConfig | None = None,
) -> tuple[PreGameFocus | None, PlayerCoachingState, FocusUpdate | None]:
    """PRE → play → POST loop helper.

    Returns (pre_game_focus_before, new_state, focus_update).
    """
    cfg = config or DEFAULT_LONGITUDINAL_CONFIG
    prior = state or empty_player_state(
        player_key, scope=scope, config_version=cfg.version
    )
    pre = build_pre_game_focus(prior.active_focus)

    # Rebuild with prior games from provenance + new game is hard without stored games.
    # Callers should pass full history via build_player_coaching_state.
    # This helper updates focus assuming `game` alone against prior active focus.
    from riftlens.coaching.longitudinal.focus import update_active_focus as _uaf

    histories = {
        item.concept_id: item for item in prior.concept_histories
    }
    # Merge this game's observations into temporary histories by rebuilding
    # if we only have this game, build from [game]
    new_state = build_player_coaching_state(
        # Reconstruct minimal history from prior recent ids is insufficient;
        # require callers to use build_player_coaching_state for multi-game.
        # Here we only have the single new game plus prior active focus continuity
        # by passing previous_state.
        [game],
        player_key=player_key,
        scope=scope or prior.scope,
        config=cfg,
        previous_state=prior,
    )
    # Compute update explicitly for return
    _, update = _uaf(
        prior.active_focus,
        game,
        {item.concept_id: item for item in new_state.concept_histories} or histories,
        scope=scope or prior.scope,
        config=cfg,
        resolved_cooldown=prior.resolved_cooldown_concepts,
    )
    return pre, new_state, update


# Re-export method constants for packaging clarity
__all_methods__ = (
    LONGITUDINAL_SCHEMA_VERSION,
    LONGITUDINAL_METHOD,
    LONGITUDINAL_METHOD_VERSION,
)
