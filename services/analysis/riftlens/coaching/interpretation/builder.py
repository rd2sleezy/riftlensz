"""Pure C.2 interpreter over C.1 CoachingEpisode objects.

No network, DB, LLM, visual, or replay I/O. Not wired into H.11.
"""

from __future__ import annotations

from collections.abc import Sequence

from riftlens.coaching.context.models import (
    CoachingEpisode,
    FindingAssociation,
    FindingRef,
    ResolutionStatus,
    SnapshotPoint,
)
from riftlens.coaching.interpretation.models import (
    ALTERNATIVE_ANALYSIS_NOT_IMPLEMENTED,
    EPISODE_INTERPRETATION_SCHEMA_VERSION,
    INTERPRETATION_METHOD,
    INTERPRETATION_METHOD_VERSION,
    INTERPRETATION_PRODUCER,
    INTERPRETATION_PRODUCER_VERSION,
    ActionabilityAssessment,
    ActionabilityState,
    ClaimKind,
    ConditionResolutionView,
    DecisionAssessment,
    EpisodeInterpretation,
    EvidencePointer,
    FindingInterpretation,
    InformationClaim,
    KnowledgeStatus,
    ObservedOutcome,
    OutcomePolarity,
    QualityState,
    ReasonCode,
    TemporalObservation,
    TemporalRelation,
    derive_decision_outcome_relation,
    interpretation_id,
    not_observable_execution,
    unknown_decision,
)
from riftlens.coaching.interpretation.registry import interpret_finding
from riftlens.domain.enums import FactKind
from riftlens.domain.fact import Provenance
from riftlens.domain.ports import PatchData
from riftlens.domain.timeline import GameStateTimeline


def interpret_coaching_episodes(
    gst: GameStateTimeline,
    episodes: Sequence[CoachingEpisode],
    participant_id: int,
    *,
    patch: PatchData | None = None,
) -> list[EpisodeInterpretation]:
    """Return interpretations for each episode in order. Empty input → []."""
    del patch
    if not episodes:
        return []
    return [
        interpret_coaching_episode(gst, episode, participant_id) for episode in episodes
    ]


def interpret_coaching_episode(
    gst: GameStateTimeline,
    episode: CoachingEpisode,
    participant_id: int,
    *,
    patch: PatchData | None = None,
) -> EpisodeInterpretation:
    """Interpret one C.1 episode. Assumes episode.participant_id matches intent."""
    del patch
    pid = participant_id
    finding_rows = tuple(
        interpret_finding(gst, episode, finding) for finding in episode.findings
    )
    anchors = [item for item in episode.findings if item.association is FindingAssociation.ANCHOR]
    anchor_ids = tuple(item.finding_id for item in anchors)
    outcomes = tuple(item.outcome for item in finding_rows if not item.suppressed)
    if not outcomes:
        outcomes = tuple(item.outcome for item in finding_rows)
    decision = _episode_decision(finding_rows)
    execution = not_observable_execution(method=INTERPRETATION_METHOD)
    polarity = _aggregate_polarity(outcomes)
    relation = derive_decision_outcome_relation(decision.state, polarity)
    actionability = _actionability(episode, anchors)
    antecedents, concurrent, consequences = _temporal_buckets(episode, anchors)
    claims = _information_claims(gst, episode)
    resolutions = tuple(
        ConditionResolutionView(
            finding_id=item.finding_id,
            status=item.status,
            resolver=item.resolver,
            note=item.note,
        )
        for item in episode.resolutions
    )
    unknowns = _unknowns(episode, finding_rows, actionability, resolutions)
    support = tuple(
        EvidencePointer("finding", item.finding_id, item.t_ms) for item in anchors
    )
    return EpisodeInterpretation(
        id=interpretation_id(episode.id, pid),
        schema_version=EPISODE_INTERPRETATION_SCHEMA_VERSION,
        episode_id=episode.id,
        match_id=episode.match_id,
        participant_id=pid,
        start_ms=episode.start_ms,
        end_ms=episode.end_ms,
        anchor_finding_ids=anchor_ids,
        method=INTERPRETATION_METHOD,
        method_version=INTERPRETATION_METHOD_VERSION,
        findings=finding_rows,
        outcomes=outcomes,
        decision=decision,
        execution=execution,
        actionability=actionability,
        decision_outcome_relation=relation,
        antecedents=antecedents,
        concurrent=concurrent,
        consequences=consequences,
        condition_resolutions=resolutions,
        information_claims=claims,
        unknowns=unknowns,
        support=support,
        conflicts=(),
        provenance=Provenance(
            producer=INTERPRETATION_PRODUCER,
            producer_version=INTERPRETATION_PRODUCER_VERSION,
            upstream=("c1_episode", episode.id),
        ),
        alternative_analysis=ALTERNATIVE_ANALYSIS_NOT_IMPLEMENTED,
        confidence=min((item.outcome.confidence for item in finding_rows), default=0.0),
    )


def _episode_decision(rows: Sequence[FindingInterpretation]) -> DecisionAssessment:
    """Episode decision stays UNKNOWN unless a row independently assessed quality.

    C.2 ships no production GOOD/POOR contracts, so this remains UNKNOWN.
    """
    assessed = [
        item.decision
        for item in rows
        if item.decision.state
        in {QualityState.GOOD, QualityState.POOR, QualityState.MIXED}
        and not item.suppressed
    ]
    if not assessed:
        missing = (
            "documented_decision_evidence_contract",
            "player_knowledge_proof",
            "counterfactual_space",
        )
        return unknown_decision(method=INTERPRETATION_METHOD, missing=missing)
    # Reserved for future contracts; keep deterministic tie-break.
    states = {item.state for item in assessed}
    if len(states) > 1:
        return DecisionAssessment(
            state=QualityState.MIXED,
            confidence=min(item.confidence for item in assessed),
            method=INTERPRETATION_METHOD,
            reason_codes=(ReasonCode("MIXED_FINDING_DECISIONS", ""),),
            support=(),
            conflicts=(),
            missing_requirements=(),
        )
    return assessed[0]


def _aggregate_polarity(outcomes: Sequence[ObservedOutcome]) -> OutcomePolarity:
    if not outcomes:
        return OutcomePolarity.UNKNOWN
    polarities = {item.polarity for item in outcomes}
    if OutcomePolarity.UNFAVORABLE in polarities and OutcomePolarity.FAVORABLE in polarities:
        return OutcomePolarity.UNKNOWN
    if OutcomePolarity.UNFAVORABLE in polarities:
        return OutcomePolarity.UNFAVORABLE
    if OutcomePolarity.FAVORABLE in polarities:
        return OutcomePolarity.FAVORABLE
    if OutcomePolarity.NEUTRAL in polarities:
        return OutcomePolarity.NEUTRAL
    return OutcomePolarity.UNKNOWN


def _actionability(
    episode: CoachingEpisode, anchors: Sequence[FindingRef]
) -> ActionabilityAssessment:
    """Fail closed: only NOT_ACTIONABLE when death during the evaluated window."""
    after = next(
        (sample for sample in episode.samples if sample.point is SnapshotPoint.AFTER),
        None,
    )
    if after is not None and after.alive is not None and after.alive.value is False:
        return ActionabilityAssessment(
            state=ActionabilityState.NOT_ACTIONABLE,
            t_ms=after.t_ms,
            confidence=float(after.alive.confidence or 0.0),
            reason_codes=(
                ReasonCode(
                    "SUBJECT_DEAD_IN_WINDOW",
                    "Subject modelled dead at AFTER sample; not actionable then.",
                ),
            ),
            support=(
                EvidencePointer("sample", "AFTER.alive", after.t_ms, after.alive.basis),
            ),
        )
    if episode.end_ms >= episode.start_ms and episode.end_ms == 0:
        return ActionabilityAssessment(
            state=ActionabilityState.NOT_ACTIONABLE,
            t_ms=0,
            confidence=1.0,
            reason_codes=(ReasonCode("GAME_ENDED", "Zero-duration episode."),),
        )
    return ActionabilityAssessment(
        state=ActionabilityState.UNKNOWN,
        t_ms=anchors[0].t_ms if anchors else episode.start_ms,
        confidence=0.0,
        reason_codes=(
            ReasonCode(
                "STRATEGIC_AGENCY_NOT_ESTABLISHED",
                "Alive/presence alone does not prove strategic actionability.",
            ),
        ),
    )


def _temporal_buckets(
    episode: CoachingEpisode, anchors: Sequence[FindingRef]
) -> tuple[
    tuple[TemporalObservation, ...],
    tuple[TemporalObservation, ...],
    tuple[TemporalObservation, ...],
]:
    if not anchors:
        return (), (), ()
    earliest = min(item.t_ms for item in anchors)
    latest = max(item.t_end_ms or item.t_ms for item in anchors)
    ante: list[TemporalObservation] = []
    conc: list[TemporalObservation] = []
    cons: list[TemporalObservation] = []
    for finding in episode.findings:
        obs = TemporalObservation(
            relation=TemporalRelation.CONCURRENT,
            label=f"finding:{finding.rule_id}",
            t_ms=finding.t_ms,
            source_kind="finding",
            ref=finding.finding_id,
            payload={
                "association": finding.association.value,
                "suppressed": finding.suppressed,
                "temporal_note": "TEMPORALLY_PRECEDING_OR_FOLLOWING_ONLY",
            },
        )
        if finding.t_ms < earliest:
            ante.append(
                TemporalObservation(
                    relation=TemporalRelation.ANTECEDENT,
                    label=obs.label,
                    t_ms=obs.t_ms,
                    source_kind=obs.source_kind,
                    ref=obs.ref,
                    payload=obs.payload,
                )
            )
        elif finding.t_ms > latest:
            cons.append(
                TemporalObservation(
                    relation=TemporalRelation.CONSEQUENCE,
                    label=obs.label,
                    t_ms=obs.t_ms,
                    source_kind=obs.source_kind,
                    ref=obs.ref,
                    payload=obs.payload,
                )
            )
        else:
            conc.append(obs)
    for fact in episode.fact_refs:
        label = f"fact:{fact.kind.value}"
        payload = {"origin": fact.origin.value, "source": fact.source.value}
        if fact.t_ms < earliest:
            ante.append(
                TemporalObservation(
                    TemporalRelation.ANTECEDENT, label, fact.t_ms, "fact", label, payload
                )
            )
        elif fact.t_ms > latest:
            cons.append(
                TemporalObservation(
                    TemporalRelation.CONSEQUENCE, label, fact.t_ms, "fact", label, payload
                )
            )
        else:
            conc.append(
                TemporalObservation(
                    TemporalRelation.CONCURRENT, label, fact.t_ms, "fact", label, payload
                )
            )
    for resolution in episode.resolutions:
        if resolution.status is ResolutionStatus.NOT_EVALUATED:
            continue
        stamp = resolution.evaluated_at_ms
        if stamp is None:
            continue
        obs = TemporalObservation(
            relation=TemporalRelation.CONSEQUENCE,
            label=f"condition_resolution:{resolution.status.value}",
            t_ms=stamp,
            source_kind="condition_resolution",
            ref=resolution.finding_id,
            payload={"resolver": resolution.resolver, "status": resolution.status.value},
        )
        if stamp < earliest:
            ante.append(
                TemporalObservation(
                    TemporalRelation.ANTECEDENT,
                    obs.label,
                    obs.t_ms,
                    obs.source_kind,
                    obs.ref,
                    obs.payload,
                )
            )
        elif stamp > latest:
            cons.append(obs)
        else:
            conc.append(
                TemporalObservation(
                    TemporalRelation.CONCURRENT,
                    obs.label,
                    obs.t_ms,
                    obs.source_kind,
                    obs.ref,
                    obs.payload,
                )
            )
    def _sort_key(item: TemporalObservation) -> tuple[int, str]:
        return (item.t_ms if item.t_ms is not None else -1, item.ref)

    return (
        tuple(sorted(ante, key=_sort_key)),
        tuple(sorted(conc, key=_sort_key)),
        tuple(sorted(cons, key=_sort_key)),
    )


def _information_claims(
    gst: GameStateTimeline, episode: CoachingEpisode
) -> tuple[InformationClaim, ...]:
    claims: list[InformationClaim] = []
    gap_fields = {gap.field for gap in episode.gaps}
    pid = episode.participant_id
    for fact in gst.facts(
        kind=FactKind.POSITION, window=(episode.start_ms, episode.end_ms)
    ):
        if fact.subject.kind != "participant" or fact.subject.id == pid:
            continue
        claims.append(
            InformationClaim(
                claim_kind=ClaimKind.SYSTEM_INFORMATION,
                label="enemy_or_ally_position_frame",
                system_available=True,
                player_knowledge=KnowledgeStatus.UNAVAILABLE,
                t_ms=fact.t_ms,
                reason_codes=(
                    ReasonCode(
                        "OMNISCIENT_POSITION_NOT_PLAYER_VISION",
                        "Riot timeline positions are system information; fog unavailable.",
                    ),
                ),
                support=(EvidencePointer("fact", fact.kind.value, fact.t_ms),),
            )
        )
    for fact_row in episode.fact_refs:
        if fact_row.kind is FactKind.CHAMPION_KILL:
            claims.append(
                InformationClaim(
                    claim_kind=ClaimKind.SYSTEM_INFORMATION,
                    label="champion_kill_event",
                    system_available=True,
                    player_knowledge=KnowledgeStatus.UNKNOWN,
                    t_ms=fact_row.t_ms,
                    reason_codes=(
                        ReasonCode(
                            "KILL_FEED_VISIBILITY_UNKNOWN",
                            "Kill events are system facts; player attention/UI focus unknown.",
                        ),
                    ),
                    support=(EvidencePointer("fact", "CHAMPION_KILL", fact_row.t_ms),),
                )
            )
    if "true_fog" in gap_fields:
        claims.append(
            InformationClaim(
                claim_kind=ClaimKind.PLAYER_KNOWLEDGE,
                label="true_fog",
                system_available=False,
                player_knowledge=KnowledgeStatus.UNAVAILABLE,
                t_ms=None,
                reason_codes=(
                    ReasonCode(
                        "FOG_UNAVAILABLE",
                        "C.1 gap true_fog; high info_age is not proof of invisibility.",
                    ),
                ),
            )
        )
    if "ward_map" in gap_fields:
        claims.append(
            InformationClaim(
                claim_kind=ClaimKind.PLAYER_KNOWLEDGE,
                label="ward_map",
                system_available=False,
                player_knowledge=KnowledgeStatus.UNAVAILABLE,
                t_ms=None,
                reason_codes=(ReasonCode("WARD_MAP_UNAVAILABLE", ""),),
            )
        )
    claims.sort(key=lambda item: (item.label, item.t_ms if item.t_ms is not None else -1))
    return tuple(claims)


def _unknowns(
    episode: CoachingEpisode,
    rows: Sequence[FindingInterpretation],
    actionability: ActionabilityAssessment,
    resolutions: Sequence[ConditionResolutionView],
) -> tuple[str, ...]:
    items = [
        "decision_quality",
        "execution_quality",
        "player_vision_fog",
        "ward_map_geometry",
        "counterfactual_alternatives",
        "root_cause",
    ]
    if actionability.state is ActionabilityState.UNKNOWN:
        items.append("strategic_actionability")
    if any(item.status is ResolutionStatus.RESOLVED for item in resolutions):
        items.append("resolved_condition_does_not_prove_decision_correct")
    if any(item.rule_id == "R-001" for item in episode.findings):
        items.append("info_age_is_not_player_blindness")
    if any(not item.decision_assessable for item in rows):
        items.append("no_production_decision_evidence_contract")
    return tuple(dict.fromkeys(items))
