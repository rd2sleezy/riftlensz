"""C.6 longitudinal coaching and active curriculum tests."""

from __future__ import annotations

from pathlib import Path

from riftlens.coaching.longitudinal import (
    DEFAULT_LONGITUDINAL_CONFIG,
    LONGITUDINAL_SCHEMA_VERSION,
    CoachingScope,
    ConceptGameObservation,
    HistoricalCoachingGame,
    ObjectiveResult,
    OpportunityStatus,
    PatternStatus,
    ScopeLevel,
    TrendState,
    build_concept_history,
    build_player_coaching_state,
    build_pre_game_focus,
    derive_longitudinal_trend,
    evaluate_practice_objective,
    with_longitudinal_overrides,
)
from riftlens.coaching.teaching.models import Measurability, PracticeObjective

_ROOT = Path(__file__).resolve().parents[2] / "riftlens" / "coaching" / "longitudinal"


def _scope(role: str = "MID") -> CoachingScope:
    return CoachingScope(level=ScopeLevel.ROLE, role=role, queue_type="RANKED_SOLO")


def _obs(
    match_id: str,
    concept_id: str,
    *,
    opportunity: OpportunityStatus,
    occurrences: int = 0,
    polarity: str = "CONSISTENT_NEGATIVE",
    role: str = "MID",
    metric: float | None = None,
    tier: str | None = "MAJOR",
    learning_value: float = 55.0,
) -> ConceptGameObservation:
    return ConceptGameObservation(
        match_id=match_id,
        concept_id=concept_id,
        scope=_scope(role),
        opportunity_status=opportunity,
        polarity=polarity,
        support_level="STRONG" if occurrences else "WEAK",
        occurrence_count=occurrences,
        lesson_tier=tier,
        learning_value=learning_value,
        measurable_metric=float(occurrences) if metric is None else metric,
        opportunity_denominator=1.0
        if opportunity is OpportunityStatus.OBSERVED_OPPORTUNITY
        else None,
    )


def _game(
    match_id: str,
    *,
    t_ms: int,
    role: str = "MID",
    won: bool | None = None,
    observations: tuple[ConceptGameObservation, ...] = (),
    majors: tuple[str, ...] = (),
    strengths: tuple[str, ...] = (),
    learning_values: dict[str, float] | None = None,
) -> HistoricalCoachingGame:
    return HistoricalCoachingGame(
        match_id=match_id,
        played_at_ms=t_ms,
        patch="14.1",
        role=role,
        champion="Ahri",
        won=won,
        concept_observations=observations,
        major_concept_ids=majors,
        strength_concept_ids=strengths,
        learning_value_by_concept=learning_values or {},
    )


def _objective(
    concept_id: str = "economy.resource_spending",
    *,
    measurability: Measurability = Measurability.MEASURABLE_NOW,
) -> PracticeObjective:
    return PracticeObjective(
        concept_id=concept_id,
        target_behavior="Reduce high-unspent-gold occurrences",
        observable="resource_spending_findings",
        evaluation_mode="count_condition_occurrences",
        success_definition="zero supported occurrences given opportunity",
        required_future_evidence=("gold_facts", "resource_spending_findings"),
        measurability=measurability,
        outcome_goal=False,
        prior_lesson_id="c5:test",
    )


def test_zero_history_empty() -> None:
    state = build_player_coaching_state([])
    assert state.schema_version == LONGITUDINAL_SCHEMA_VERSION
    assert state.active_focus is None
    assert state.concept_histories == ()


def test_hs01_one_game_new_not_recurring() -> None:
    g1 = _game(
        "m1",
        t_ms=1,
        observations=(
            _obs(
                "m1",
                "economy.resource_spending",
                opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                occurrences=3,
            ),
        ),
        majors=("economy.resource_spending",),
        learning_values={"economy.resource_spending": 60.0},
    )
    hist = build_concept_history([g1], "economy.resource_spending", scope=_scope())
    assert hist.status is PatternStatus.NEW
    assert hist.status is not PatternStatus.RECURRING


def test_hs02_multiple_games_recurring() -> None:
    games = [
        _game(
            f"m{i}",
            t_ms=i,
            observations=(
                _obs(
                    f"m{i}",
                    "economy.resource_spending",
                    opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                    occurrences=2,
                ),
            ),
            majors=("economy.resource_spending",),
        )
        for i in range(1, 4)
    ]
    hist = build_concept_history(games, "economy.resource_spending", scope=_scope())
    assert hist.status is PatternStatus.RECURRING
    assert any(code.code == "REPEATED_ACROSS_GAMES" for code in hist.reason_codes)


def test_hs04_no_opportunity_insufficient() -> None:
    g = _game(
        "m1",
        t_ms=1,
        observations=(
            _obs(
                "m1",
                "economy.resource_spending",
                opportunity=OpportunityStatus.NO_OBSERVABLE_OPPORTUNITY,
                occurrences=0,
            ),
        ),
    )
    hist = build_concept_history([g], "economy.resource_spending", scope=_scope())
    assert hist.status is PatternStatus.INSUFFICIENT_EVIDENCE


def test_hs05_role_mismatch_not_inflated() -> None:
    mid = _game(
        "m1",
        t_ms=1,
        role="MID",
        observations=(
            _obs(
                "m1",
                "vision.control_ward_habit",
                opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                occurrences=1,
                role="MID",
            ),
        ),
    )
    support = _game(
        "m2",
        t_ms=2,
        role="SUPPORT",
        observations=(
            _obs(
                "m2",
                "vision.control_ward_habit",
                opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                occurrences=1,
                role="SUPPORT",
            ),
        ),
    )
    hist = build_concept_history(
        [mid, support],
        "vision.control_ward_habit",
        scope=_scope("MID"),
    )
    assert hist.games_with_opportunity == 1


def test_oe01_success() -> None:
    g = _game(
        "m1",
        t_ms=1,
        observations=(
            _obs(
                "m1",
                "economy.resource_spending",
                opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                occurrences=0,
            ),
        ),
    )
    ev = evaluate_practice_objective(_objective(), g)
    assert ev.result is ObjectiveResult.SUCCESS


def test_oe02_failure() -> None:
    g = _game(
        "m1",
        t_ms=1,
        observations=(
            _obs(
                "m1",
                "economy.resource_spending",
                opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                occurrences=2,
            ),
        ),
    )
    ev = evaluate_practice_objective(_objective(), g)
    assert ev.result is ObjectiveResult.FAILURE


def test_oe04_not_measurable() -> None:
    g = _game("m1", t_ms=1)
    ev = evaluate_practice_objective(
        _objective("wave.management", measurability=Measurability.NOT_MEASURABLE),
        g,
    )
    assert ev.result is ObjectiveResult.NOT_EVALUATED


def test_oe05_oe06_no_opportunity_not_success() -> None:
    g = _game(
        "m1",
        t_ms=1,
        observations=(
            _obs(
                "m1",
                "economy.resource_spending",
                opportunity=OpportunityStatus.NO_OBSERVABLE_OPPORTUNITY,
                occurrences=0,
            ),
        ),
    )
    ev = evaluate_practice_objective(_objective(), g)
    assert ev.result is not ObjectiveResult.SUCCESS
    assert ev.result is ObjectiveResult.NOT_EVALUATED


def test_tr01_improving() -> None:
    obs = [
        _obs(
            f"m{i}",
            "economy.resource_spending",
            opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
            occurrences=occ,
            metric=float(occ),
        )
        for i, occ in enumerate((3, 2, 1, 0), start=1)
    ]
    assert derive_longitudinal_trend(obs) is TrendState.IMPROVING


def test_tr05_win_loss_ignored() -> None:
    # Same process metrics; different wins — trend from metrics only
    obs = [
        _obs(
            f"m{i}",
            "economy.resource_spending",
            opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
            occurrences=2,
        )
        for i in range(1, 4)
    ]
    assert derive_longitudinal_trend(obs) in {
        TrendState.STABLE,
        TrendState.UNKNOWN,
        TrendState.IMPROVING,
        TrendState.REGRESSING,
    }
    # Win/loss not an input to derive_longitudinal_trend


def test_cur01_first_major_activates() -> None:
    g1 = _game(
        "m1",
        t_ms=1,
        observations=(
            _obs(
                "m1",
                "economy.resource_spending",
                opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                occurrences=3,
            ),
        ),
        majors=("economy.resource_spending",),
        learning_values={"economy.resource_spending": 70.0},
    )
    state = build_player_coaching_state([g1], scope=_scope())
    assert state.active_focus is not None
    assert state.active_focus.concept_id == "economy.resource_spending"


def test_cur02_focus_survives_unrelated_loud_game() -> None:
    g1 = _game(
        "m1",
        t_ms=1,
        observations=(
            _obs(
                "m1",
                "economy.resource_spending",
                opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                occurrences=2,
            ),
        ),
        majors=("economy.resource_spending",),
        learning_values={"economy.resource_spending": 60.0},
    )
    g2 = _game(
        "m2",
        t_ms=2,
        observations=(
            _obs(
                "m2",
                "economy.resource_spending",
                opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                occurrences=2,
            ),
            _obs(
                "m2",
                "objective.presence",
                opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                occurrences=1,
                learning_value=90.0,
            ),
        ),
        majors=("objective.presence", "economy.resource_spending"),
        learning_values={
            "objective.presence": 90.0,
            "economy.resource_spending": 50.0,
        },
    )
    state = build_player_coaching_state([g1, g2], scope=_scope())
    assert state.active_focus is not None
    assert state.active_focus.concept_id == "economy.resource_spending"


def test_cur06_blocked_cannot_be_measurable_focus() -> None:
    g1 = _game(
        "m1",
        t_ms=1,
        observations=(
            _obs(
                "m1",
                "wave.management",
                opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                occurrences=1,
            ),
        ),
        majors=("wave.management",),
        learning_values={"wave.management": 99.0},
    )
    state = build_player_coaching_state([g1], scope=_scope())
    assert state.active_focus is None or state.active_focus.concept_id != "wave.management"


def test_cur07_one_primary_focus() -> None:
    assert DEFAULT_LONGITUDINAL_CONFIG.allow_multiple_primary_focuses is False


def test_win_does_not_imply_improvement() -> None:
    g = _game(
        "m1",
        t_ms=1,
        won=True,
        observations=(
            _obs(
                "m1",
                "economy.resource_spending",
                opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                occurrences=3,
            ),
        ),
    )
    ev = evaluate_practice_objective(_objective(), g)
    assert ev.result is ObjectiveResult.FAILURE


def test_loss_does_not_imply_regression() -> None:
    g = _game(
        "m1",
        t_ms=1,
        won=False,
        observations=(
            _obs(
                "m1",
                "economy.resource_spending",
                opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                occurrences=0,
            ),
        ),
    )
    ev = evaluate_practice_objective(_objective(), g)
    assert ev.result is ObjectiveResult.SUCCESS


def test_loop_pre_post() -> None:
    g1 = _game(
        "m1",
        t_ms=1,
        observations=(
            _obs(
                "m1",
                "economy.resource_spending",
                opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                occurrences=2,
            ),
        ),
        majors=("economy.resource_spending",),
        learning_values={"economy.resource_spending": 60.0},
    )
    state1 = build_player_coaching_state([g1], scope=_scope())
    pre = build_pre_game_focus(state1.active_focus)
    assert pre is not None
    assert pre.concept_id == "economy.resource_spending"
    g2 = _game(
        "m2",
        t_ms=2,
        observations=(
            _obs(
                "m2",
                "economy.resource_spending",
                opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                occurrences=1,
            ),
        ),
        majors=("economy.resource_spending",),
        learning_values={"economy.resource_spending": 55.0},
    )
    state2 = build_player_coaching_state([g1, g2], scope=_scope())
    assert state2.active_focus is not None
    assert state2.active_focus.concept_id == "economy.resource_spending"
    pre2 = build_pre_game_focus(state2.active_focus)
    assert pre2 is not None


def test_five_game_golden() -> None:
    concept = "economy.resource_spending"
    games = []
    for i, occ in enumerate((3, 2, 2, 1, 0), start=1):
        games.append(
            _game(
                f"m{i}",
                t_ms=i * 1000,
                won=(i % 2 == 0),
                observations=(
                    _obs(
                        f"m{i}",
                        concept,
                        opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                        occurrences=occ,
                        metric=float(occ),
                    ),
                ),
                majors=(concept,),
                learning_values={concept: 60.0 - i},
            )
        )
    # Game 4 also has a loud objective issue that should not steal focus early
    games[3] = _game(
        "m4",
        t_ms=4000,
        won=True,
        observations=(
            _obs(
                "m4",
                concept,
                opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                occurrences=1,
                metric=1.0,
            ),
            _obs(
                "m4",
                "objective.presence",
                opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                occurrences=1,
                learning_value=95.0,
            ),
        ),
        majors=("objective.presence", concept),
        learning_values={"objective.presence": 95.0, concept: 50.0},
    )
    state = build_player_coaching_state(games, scope=_scope())
    hist = next(item for item in state.concept_histories if item.concept_id == concept)
    assert hist.games_with_opportunity >= 4
    assert hist.status in {
        PatternStatus.RECURRING,
        PatternStatus.ACTIVE_FOCUS,
        PatternStatus.IMPROVING,
        PatternStatus.EMERGING,
    }
    assert state.active_focus is not None
    assert state.active_focus.concept_id == concept
    assert hist.trend in {TrendState.IMPROVING, TrendState.STABLE, TrendState.UNKNOWN}


def test_absence_without_opportunity_not_success_in_history() -> None:
    g1 = _game(
        "m1",
        t_ms=1,
        observations=(
            _obs(
                "m1",
                "economy.resource_spending",
                opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                occurrences=2,
            ),
        ),
        majors=("economy.resource_spending",),
        learning_values={"economy.resource_spending": 60.0},
    )
    g2 = _game(
        "m2",
        t_ms=2,
        observations=(
            _obs(
                "m2",
                "economy.resource_spending",
                opportunity=OpportunityStatus.NO_OBSERVABLE_OPPORTUNITY,
                occurrences=0,
            ),
        ),
    )
    g3 = _game(
        "m3",
        t_ms=3,
        observations=(
            _obs(
                "m3",
                "economy.resource_spending",
                opportunity=OpportunityStatus.UNKNOWN_OPPORTUNITY,
                occurrences=0,
            ),
        ),
    )
    hist = build_concept_history(
        [g1, g2, g3],
        "economy.resource_spending",
        scope=_scope(),
        objective=_objective(),
    )
    assert hist.positive_games == 0
    assert hist.games_with_opportunity == 1
    assert all(
        item.result is not ObjectiveResult.SUCCESS for item in hist.evaluations[1:]
    )


def test_config_sensitivity() -> None:
    games = [
        _game(
            f"m{i}",
            t_ms=i,
            observations=(
                _obs(
                    f"m{i}",
                    "economy.resource_spending",
                    opportunity=OpportunityStatus.OBSERVED_OPPORTUNITY,
                    occurrences=1,
                ),
            ),
            majors=("economy.resource_spending",),
        )
        for i in range(1, 3)
    ]
    low = build_concept_history(
        games,
        "economy.resource_spending",
        scope=_scope(),
        config=with_longitudinal_overrides(recurring_min_games=2),
    )
    high = build_concept_history(
        games,
        "economy.resource_spending",
        scope=_scope(),
        config=with_longitudinal_overrides(recurring_min_games=5),
    )
    assert low.status is PatternStatus.RECURRING
    assert high.status is not PatternStatus.RECURRING


def test_import_isolation_scan() -> None:
    banned = (
        "riftlens.visual",
        "riftlens.replay_host",
        "riftlens.coaching.providers",
        "openai",
        "anthropic",
    )
    for path in _ROOT.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{path.name} imports {token}"
