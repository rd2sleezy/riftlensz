"""Active focus selection, hysteresis, PreGameFocus, and FocusUpdate."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from riftlens.coaching.longitudinal.config import (
    DEFAULT_LONGITUDINAL_CONFIG,
    LongitudinalCoachingConfig,
)
from riftlens.coaching.longitudinal.history import build_concept_history
from riftlens.coaching.longitudinal.models import (
    ActiveFocus,
    CoachingScope,
    ConceptHistory,
    FocusDecision,
    FocusUpdate,
    HistoricalCoachingGame,
    ObjectiveEvaluation,
    ObjectiveResult,
    OpportunityStatus,
    PatternStatus,
    PreGameFocus,
    ReasonCode,
    TrendState,
)
from riftlens.coaching.longitudinal.objective_eval import evaluate_practice_objective
from riftlens.coaching.teaching.models import (
    Measurability,
    MemorableRule,
    PracticeDrill,
    PracticeObjective,
    RecognitionCue,
)
from riftlens.coaching.teaching.playbooks import get_concept_playbook


def _objective_from_teaching(
    teaching: Mapping[str, object] | None,
    concept_id: str,
    prior_lesson_id: str,
) -> PracticeObjective | None:
    if not teaching:
        playbook = get_concept_playbook(concept_id)
        if playbook is None:
            return None
        obj = playbook.objective_template
        return PracticeObjective(
            concept_id=obj.concept_id,
            target_behavior=obj.target_behavior,
            observable=obj.observable,
            evaluation_mode=obj.evaluation_mode,
            success_definition=obj.success_definition,
            required_future_evidence=obj.required_future_evidence,
            measurability=obj.measurability,
            outcome_goal=False,
            prior_lesson_id=prior_lesson_id,
        )
    raw = teaching.get("objective")
    if not isinstance(raw, dict):
        return None
    meas = str(raw.get("measurability", Measurability.NOT_MEASURABLE.value))
    return PracticeObjective(
        concept_id=str(raw.get("concept_id", concept_id)),
        target_behavior=str(raw.get("target_behavior", "")),
        observable=str(raw.get("observable", "")),
        evaluation_mode=str(raw.get("evaluation_mode", "")),
        success_definition=str(raw.get("success_definition", "")),
        required_future_evidence=tuple(
            str(item) for item in raw.get("required_future_evidence", ())
        ),
        measurability=Measurability(meas),
        outcome_goal=False,
        prior_lesson_id=str(raw.get("prior_lesson_id", prior_lesson_id)),
    )


def _cue_rule_drill(
    concept_id: str,
) -> tuple[RecognitionCue | None, MemorableRule | None, PracticeDrill | None]:
    playbook = get_concept_playbook(concept_id)
    if playbook is None:
        return None, None, None
    return playbook.recognition_cue, playbook.memorable_rule, playbook.drill


def _eligible_focus_candidate(
    concept_id: str,
    history: ConceptHistory,
    game: HistoricalCoachingGame,
    *,
    config: LongitudinalCoachingConfig,
    cooldown: set[str],
) -> bool:
    if concept_id in config.blocked_concepts:
        return False
    if concept_id in cooldown:
        return False
    if concept_id.startswith("strength."):
        return False
    playbook = get_concept_playbook(concept_id)
    if playbook is None:
        return False
    if playbook.objective_template.measurability is Measurability.NOT_MEASURABLE:
        return False
    # Need MAJOR selection or recurring history
    if concept_id in game.major_concept_ids:
        return True
    if history.status in {
        PatternStatus.RECURRING,
        PatternStatus.EMERGING,
        PatternStatus.REGRESSING,
    }:
        return True
    return False


def build_pre_game_focus(active: ActiveFocus | None) -> PreGameFocus | None:
    """Build pre-game reminder packet from active focus."""
    if active is None:
        return None
    progress = f"status={active.status.value}; continuity={active.continuity_games}"
    if active.recent_evaluations:
        last = active.recent_evaluations[-1]
        progress = f"{progress}; last_eval={last.result.value}"
    drill = ""
    if active.drill is not None:
        drill = active.drill.instruction
    obj = ""
    if active.objective is not None:
        obj = active.objective.target_behavior
    return PreGameFocus(
        concept_id=active.concept_id,
        recognition_cue=active.recognition_cue,
        memorable_rule=active.memorable_rule,
        drill_reminder=drill,
        objective_summary=obj,
        why_still_active="Active deliberate-practice focus remains unresolved.",
        recent_progress_summary=progress,
        confidence=active.confidence,
        reason_codes=(ReasonCode("PRE_GAME_FOCUS", active.concept_id),),
    )


def update_active_focus(
    previous: ActiveFocus | None,
    game: HistoricalCoachingGame,
    histories: Mapping[str, ConceptHistory],
    *,
    scope: CoachingScope,
    config: LongitudinalCoachingConfig | None = None,
    resolved_cooldown: Sequence[str] = (),
) -> tuple[ActiveFocus | None, FocusUpdate]:
    """Apply one game to active-focus state with hysteresis.

    Default: one primary focus. Does not chase the loudest latest mistake.
    """
    cfg = config or DEFAULT_LONGITUDINAL_CONFIG
    cooldown = set(resolved_cooldown)
    codes: list[ReasonCode] = []
    before = previous.concept_id if previous else None

    # Evaluate current focus if present
    evaluation: ObjectiveEvaluation | None = None
    trend_after = TrendState.UNKNOWN
    if previous is not None:
        hist = histories.get(previous.concept_id)
        if hist is not None:
            trend_after = hist.trend
        if previous.objective is not None:
            evaluation = evaluate_practice_objective(
                previous.objective, game, config=cfg
            )

    # Resolution check
    if previous is not None and evaluation is not None:
        recent_success = [
            item
            for item in (*previous.recent_evaluations, evaluation)
            if item.result is ObjectiveResult.SUCCESS
            and item.opportunity_status is OpportunityStatus.OBSERVED_OPPORTUNITY
        ]
        recent_fail = [
            item
            for item in (*previous.recent_evaluations, evaluation)
            if item.result is ObjectiveResult.FAILURE
        ]
        hist = histories.get(previous.concept_id)
        opp = hist.games_with_opportunity if hist else 0
        if (
            len(recent_success) >= cfg.resolve_min_success_evals
            and opp >= cfg.resolve_min_opportunity_games
            and len([item for item in recent_fail[-cfg.recent_window :]])
            <= cfg.resolve_max_recent_failures
            and evaluation.result is ObjectiveResult.SUCCESS
        ):
            codes.append(ReasonCode("FOCUS_RESOLVED", previous.concept_id))
            # Select next focus if worthy
            next_focus = _select_new_focus(
                game,
                histories,
                scope=scope,
                config=cfg,
                cooldown=cooldown | {previous.concept_id},
                exclude={previous.concept_id},
            )
            if next_focus is None:
                codes.append(ReasonCode("NO_WORTHY_REPLACEMENT"))
                update = FocusUpdate(
                    before_concept_id=before,
                    after_concept_id=None,
                    decision=FocusDecision.NO_NEW_FOCUS,
                    objective_evaluation=evaluation,
                    trend_after=trend_after,
                    evidence_summary=("focus_resolved", "no_replacement"),
                    reason_codes=tuple(codes),
                )
                return None, update
            codes.append(ReasonCode("SWITCH_FOCUS", next_focus.concept_id))
            update = FocusUpdate(
                before_concept_id=before,
                after_concept_id=next_focus.concept_id,
                decision=FocusDecision.RESOLVE_FOCUS,
                objective_evaluation=evaluation,
                trend_after=trend_after,
                evidence_summary=("focus_resolved", f"next={next_focus.concept_id}"),
                reason_codes=tuple(codes),
            )
            return next_focus, update

    # Keep focus with hysteresis unless strongly outranked AND continuity satisfied
    if previous is not None:
        current_lv = float(game.learning_value_by_concept.get(previous.concept_id, 0.0))
        challengers = [
            (cid, float(game.learning_value_by_concept.get(cid, 0.0)))
            for cid in game.major_concept_ids
            if cid != previous.concept_id
        ]
        best_other = max((value for _, value in challengers), default=0.0)
        best_other_id = None
        if challengers:
            best_other_id = max(challengers, key=lambda item: item[1])[0]

        keep = True
        if (
            previous.continuity_games >= cfg.min_focus_continuity_games
            and best_other_id is not None
            and best_other >= current_lv + cfg.focus_switch_margin
            and _eligible_focus_candidate(
                best_other_id,
                histories.get(
                    best_other_id,
                    build_concept_history([], best_other_id, scope=scope, config=cfg),
                ),
                game,
                config=cfg,
                cooldown=cooldown,
            )
            and (
                histories.get(best_other_id)
                and histories[best_other_id].status
                in {PatternStatus.RECURRING, PatternStatus.EMERGING, PatternStatus.REGRESSING}
            )
        ):
            keep = False

        if keep:
            codes.append(ReasonCode("KEEP_ACTIVE_FOCUS"))
            if best_other_id and best_other > current_lv:
                codes.append(ReasonCode("SWITCH_MARGIN_NOT_MET"))
            codes.append(ReasonCode("DO_NOT_CHASE_LATEST_MISTAKE"))
            cue, rule, drill = _cue_rule_drill(previous.concept_id)
            if evaluation is not None:
                recent = (*previous.recent_evaluations, evaluation)
            else:
                recent = previous.recent_evaluations
            # Cap recent evals
            recent = recent[-cfg.recent_window :]
            status = PatternStatus.ACTIVE_FOCUS
            if trend_after is TrendState.IMPROVING:
                status = PatternStatus.IMPROVING
                codes.append(ReasonCode("TREND_IMPROVING"))
            elif trend_after is TrendState.REGRESSING:
                status = PatternStatus.REGRESSING
                codes.append(ReasonCode("TREND_REGRESSING"))
            updated = ActiveFocus(
                concept_id=previous.concept_id,
                scope=previous.scope,
                status=status,
                started_match_id=previous.started_match_id,
                started_at_ms=previous.started_at_ms,
                prior_lesson_id=previous.prior_lesson_id,
                objective=previous.objective,
                recognition_cue=cue or previous.recognition_cue,
                memorable_rule=rule or previous.memorable_rule,
                drill=drill or previous.drill,
                recent_evaluations=tuple(item for item in recent if item is not None),
                continuity_games=previous.continuity_games + 1,
                confidence=previous.confidence,
                reason_codes=tuple(codes),
            )
            update = FocusUpdate(
                before_concept_id=before,
                after_concept_id=previous.concept_id,
                decision=FocusDecision.KEEP_FOCUS,
                objective_evaluation=evaluation,
                trend_after=trend_after,
                evidence_summary=("kept_active_focus",),
                reason_codes=tuple(codes),
            )
            return updated, update

        # Switch path
        assert best_other_id is not None
        codes.append(ReasonCode("SWITCH_FOCUS", best_other_id))
        switched = _activate(
            best_other_id, game, scope=scope, config=cfg, reactivation=False
        )
        update = FocusUpdate(
            before_concept_id=before,
            after_concept_id=best_other_id,
            decision=FocusDecision.SWITCH_FOCUS,
            objective_evaluation=evaluation,
            trend_after=trend_after,
            evidence_summary=(f"switched_to={best_other_id}",),
            reason_codes=tuple(codes),
        )
        return switched, update

    # No previous focus — activate initial or reactivate
    for concept_id in game.major_concept_ids:
        hist = histories.get(concept_id)
        if hist is None:
            continue
        if hist.status is PatternStatus.REGRESSING and concept_id in cooldown:
            # Reactivation of previously resolved
            codes.append(ReasonCode("CONCEPT_REACTIVATED", concept_id))
            focus = _activate(
                concept_id, game, scope=scope, config=cfg, reactivation=True
            )
            update = FocusUpdate(
                before_concept_id=None,
                after_concept_id=concept_id,
                decision=FocusDecision.REACTIVATE_FOCUS,
                objective_evaluation=None,
                trend_after=hist.trend,
                evidence_summary=("reactivated",),
                reason_codes=tuple(codes),
            )
            return focus, update

    new_focus = _select_new_focus(
        game, histories, scope=scope, config=cfg, cooldown=cooldown, exclude=set()
    )
    if new_focus is None:
        codes.append(ReasonCode("NO_WORTHY_REPLACEMENT"))
        update = FocusUpdate(
            before_concept_id=None,
            after_concept_id=None,
            decision=FocusDecision.NO_NEW_FOCUS,
            objective_evaluation=None,
            trend_after=TrendState.UNKNOWN,
            evidence_summary=("no_active_focus",),
            reason_codes=tuple(codes),
        )
        return None, update

    codes.append(ReasonCode("ACTIVATE_FOCUS", new_focus.concept_id))
    if new_focus.concept_id in game.major_concept_ids:
        codes.append(ReasonCode("FIRST_SUPPORTED_OCCURRENCE"))
    update = FocusUpdate(
        before_concept_id=None,
        after_concept_id=new_focus.concept_id,
        decision=FocusDecision.ACTIVATE_FOCUS,
        objective_evaluation=None,
        trend_after=TrendState.UNKNOWN,
        evidence_summary=(f"activated={new_focus.concept_id}",),
        reason_codes=tuple(codes),
    )
    return new_focus, update


def _activate(
    concept_id: str,
    game: HistoricalCoachingGame,
    *,
    scope: CoachingScope,
    config: LongitudinalCoachingConfig,
    reactivation: bool,
) -> ActiveFocus:
    prior = f"c5:{game.match_id}:{concept_id}"
    teaching = game.teaching_by_concept.get(concept_id)
    objective = _objective_from_teaching(teaching, concept_id, prior)
    cue, rule, drill = _cue_rule_drill(concept_id)
    codes = [ReasonCode("ACTIVATE_FOCUS", concept_id)]
    if reactivation:
        codes = [ReasonCode("CONCEPT_REACTIVATED", concept_id)]
    if concept_id in config.blocked_concepts:
        codes.append(ReasonCode("CAPABILITY_BLOCKED"))
    return ActiveFocus(
        concept_id=concept_id,
        scope=scope,
        status=PatternStatus.ACTIVE_FOCUS,
        started_match_id=game.match_id,
        started_at_ms=game.played_at_ms,
        prior_lesson_id=prior,
        objective=objective,
        recognition_cue=cue,
        memorable_rule=rule,
        drill=drill,
        recent_evaluations=(),
        continuity_games=1,
        confidence=0.4,
        reason_codes=tuple(codes),
    )


def _select_new_focus(
    game: HistoricalCoachingGame,
    histories: Mapping[str, ConceptHistory],
    *,
    scope: CoachingScope,
    config: LongitudinalCoachingConfig,
    cooldown: set[str],
    exclude: set[str],
) -> ActiveFocus | None:
    candidates: list[tuple[float, str]] = []
    for concept_id in game.major_concept_ids:
        if concept_id in exclude:
            continue
        hist = histories.get(concept_id)
        if hist is None:
            hist = build_concept_history([], concept_id, scope=scope, config=config)
        if not _eligible_focus_candidate(
            concept_id, hist, game, config=config, cooldown=cooldown
        ):
            continue
        score = float(game.learning_value_by_concept.get(concept_id, 50.0))
        if hist.status is PatternStatus.RECURRING:
            score += 10.0
        candidates.append((score, concept_id))
    # Also consider recurring histories not in this game majors
    for concept_id, hist in histories.items():
        if concept_id in exclude or concept_id in {c for _, c in candidates}:
            continue
        if hist.status in {PatternStatus.RECURRING, PatternStatus.REGRESSING}:
            if concept_id in config.blocked_concepts or concept_id in cooldown:
                continue
            if get_concept_playbook(concept_id) is None:
                continue
            candidates.append((40.0 + hist.confidence * 20.0, concept_id))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return _activate(candidates[0][1], game, scope=scope, config=config, reactivation=False)
