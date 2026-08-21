"""Evaluate C.5 PracticeObjectives against a HistoricalCoachingGame."""

from __future__ import annotations

from riftlens.coaching.longitudinal.config import (
    DEFAULT_LONGITUDINAL_CONFIG,
    LongitudinalCoachingConfig,
)
from riftlens.coaching.longitudinal.models import (
    ConceptGameObservation,
    HistoricalCoachingGame,
    ObjectiveEvaluation,
    ObjectiveResult,
    OpportunityStatus,
    ReasonCode,
)
from riftlens.coaching.teaching.models import Measurability, PracticeObjective


def _obs_for(
    game: HistoricalCoachingGame, concept_id: str
) -> ConceptGameObservation | None:
    for item in game.concept_observations:
        if item.concept_id == concept_id:
            return item
    return None


def evaluate_practice_objective(
    objective: PracticeObjective,
    game: HistoricalCoachingGame,
    *,
    config: LongitudinalCoachingConfig | None = None,
) -> ObjectiveEvaluation:
    """Conservatively evaluate one PracticeObjective for one game.

    Absence of a Finding without OBSERVED_OPPORTUNITY is never SUCCESS.
    NOT_MEASURABLE → NOT_EVALUATED.
    """
    _ = config or DEFAULT_LONGITUDINAL_CONFIG
    concept_id = objective.concept_id
    obs = _obs_for(game, concept_id)
    codes: list[ReasonCode] = []

    if objective.measurability is Measurability.NOT_MEASURABLE:
        return ObjectiveEvaluation(
            objective_concept_id=concept_id,
            prior_lesson_id=objective.prior_lesson_id,
            match_id=game.match_id,
            result=ObjectiveResult.NOT_EVALUATED,
            opportunity_status=(
                obs.opportunity_status
                if obs is not None
                else OpportunityStatus.UNKNOWN_OPPORTUNITY
            ),
            measurability=objective.measurability,
            method="c6_not_measurable",
            confidence=0.0,
            evidence=(),
            missing_evidence=objective.required_future_evidence,
            reason_codes=(ReasonCode("OBJECTIVE_NOT_MEASURABLE", concept_id),),
            metric_value=None,
        )

    if obs is None:
        return ObjectiveEvaluation(
            objective_concept_id=concept_id,
            prior_lesson_id=objective.prior_lesson_id,
            match_id=game.match_id,
            result=ObjectiveResult.NOT_EVALUATED,
            opportunity_status=OpportunityStatus.UNKNOWN_OPPORTUNITY,
            measurability=objective.measurability,
            method="c6_missing_observation",
            confidence=0.0,
            evidence=(),
            missing_evidence=("concept_game_observation",),
            reason_codes=(ReasonCode("INSUFFICIENT_OBSERVATION_OPPORTUNITY"),),
        )

    if obs.opportunity_status is OpportunityStatus.NO_OBSERVABLE_OPPORTUNITY:
        codes.append(ReasonCode("INSUFFICIENT_OBSERVATION_OPPORTUNITY", "no opportunity"))
        return ObjectiveEvaluation(
            objective_concept_id=concept_id,
            prior_lesson_id=objective.prior_lesson_id,
            match_id=game.match_id,
            result=ObjectiveResult.NOT_EVALUATED,
            opportunity_status=obs.opportunity_status,
            measurability=objective.measurability,
            method="c6_no_opportunity",
            confidence=0.0,
            evidence=("no_observable_opportunity",),
            missing_evidence=(),
            reason_codes=tuple(codes),
            metric_value=None,
        )

    if obs.opportunity_status is OpportunityStatus.UNKNOWN_OPPORTUNITY:
        codes.append(ReasonCode("UNKNOWN_OPPORTUNITY"))
        # Absence of finding with unknown opportunity ≠ success
        return ObjectiveEvaluation(
            objective_concept_id=concept_id,
            prior_lesson_id=objective.prior_lesson_id,
            match_id=game.match_id,
            result=ObjectiveResult.UNKNOWN,
            opportunity_status=obs.opportunity_status,
            measurability=objective.measurability,
            method="c6_unknown_opportunity",
            confidence=0.1,
            evidence=(),
            missing_evidence=("opportunity_denominator",),
            reason_codes=tuple(codes),
            metric_value=obs.measurable_metric,
        )

    # OBSERVED_OPPORTUNITY path
    metric = obs.measurable_metric
    if metric is None:
        # Fall back to occurrence_count as process metric for negative concepts
        metric = float(obs.occurrence_count)

    if objective.measurability is Measurability.PARTIALLY_MEASURABLE:
        codes.append(ReasonCode("PARTIAL_MEASUREMENT_ONLY"))
        if obs.occurrence_count <= 0 and obs.polarity != "CONSISTENT_NEGATIVE":
            result = ObjectiveResult.PARTIAL
            codes.append(ReasonCode("OBJECTIVE_PARTIAL_POSITIVE_SIGNAL"))
        elif obs.occurrence_count > 0:
            result = ObjectiveResult.PARTIAL
            codes.append(ReasonCode("OBJECTIVE_PARTIAL_NEGATIVE_PRESENT"))
        else:
            result = ObjectiveResult.UNKNOWN
        return ObjectiveEvaluation(
            objective_concept_id=concept_id,
            prior_lesson_id=objective.prior_lesson_id,
            match_id=game.match_id,
            result=result,
            opportunity_status=obs.opportunity_status,
            measurability=objective.measurability,
            method="c6_partial_metric",
            confidence=0.35,
            evidence=(f"occurrences={obs.occurrence_count}",),
            missing_evidence=(),
            reason_codes=tuple(codes),
            metric_value=metric,
        )

    # MEASURABLE_NOW: success if occurrence_count == 0 under observed opportunity
    # for negative-process objectives; failure if occurrences remain.
    if obs.occurrence_count <= 0:
        codes.append(ReasonCode("OBJECTIVE_SUCCESS"))
        result = ObjectiveResult.SUCCESS
        conf = 0.7
    else:
        codes.append(ReasonCode("OBJECTIVE_FAILURE", f"occurrences={obs.occurrence_count}"))
        result = ObjectiveResult.FAILURE
        conf = 0.7

    return ObjectiveEvaluation(
        objective_concept_id=concept_id,
        prior_lesson_id=objective.prior_lesson_id,
        match_id=game.match_id,
        result=result,
        opportunity_status=obs.opportunity_status,
        measurability=objective.measurability,
        method="c6_measurable_now",
        confidence=conf,
        evidence=(
            f"occurrences={obs.occurrence_count}",
            f"opportunity={obs.opportunity_status.value}",
        ),
        missing_evidence=(),
        reason_codes=tuple(codes),
        metric_value=metric,
    )
