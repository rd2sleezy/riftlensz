"""Deterministic C.3 concept-signal mapping and lesson synthesis."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

from riftlens.coaching.concepts.capabilities import evaluate_capability_readiness
from riftlens.coaching.concepts.catalog import concept_for
from riftlens.coaching.concepts.h8_priors import h8_edge_pair, h8_related_rule_ids
from riftlens.coaching.concepts.mapping import mappings_for
from riftlens.coaching.concepts.models import (
    CONCEPTS_SCHEMA_VERSION,
    SYNTHESIS_METHOD,
    SYNTHESIS_METHOD_VERSION,
    SYNTHESIS_PRODUCER,
    SYNTHESIS_PRODUCER_VERSION,
    CausalHypothesis,
    CausalRelation,
    CausalStatus,
    ConceptSignal,
    ConceptSpecificity,
    EvidenceRef,
    LessonCandidate,
    LessonPolarity,
    LessonReadiness,
    ReasonCode,
    SignalDirection,
    SupportLevel,
    SynthesisResult,
    empty_synthesis,
    hypothesis_id,
    lesson_id,
    signal_id,
)
from riftlens.coaching.context.models import (
    CoachingEpisode,
    FindingAssociation,
    ResolutionStatus,
)
from riftlens.coaching.interpretation.models import (
    EpisodeInterpretation,
    QualityState,
)
from riftlens.domain.fact import Provenance
from riftlens.domain.finding import Finding

_SUPPORTED_CAUSAL_CONTRACTS: Mapping[str, str] = {
    # Intentionally empty in C.3: no production path may emit CausalStatus.SUPPORTED.
    # Temporal proximity, shared concepts, and H.8 priors may reach PLAUSIBLE only.
}


def supported_causal_contracts() -> Mapping[str, str]:
    """Documented evidence contracts that may emit CausalStatus.SUPPORTED.

    C.3 ships with zero contracts. Returning an empty mapping is intentional.
    """
    return _SUPPORTED_CAUSAL_CONTRACTS


def map_concept_signals(
    episodes: Sequence[CoachingEpisode],
    interpretations: Sequence[EpisodeInterpretation],
    findings: Sequence[Finding] | None = None,
) -> list[ConceptSignal]:
    """Map C.1/C.2 findings into conservative concept signals.

    Returns [] when inputs are empty. Does not invent decision quality.
    """
    if not episodes or not interpretations:
        return []

    interp_by_episode = {item.episode_id: item for item in interpretations}
    finding_by_id = {item.id: item for item in (findings or ())}
    signals: list[ConceptSignal] = []

    for episode in episodes:
        interp = interp_by_episode.get(episode.id)
        if interp is None:
            continue
        for finding_ref in episode.findings:
            if (
                finding_ref.suppressed
                and finding_ref.association is not FindingAssociation.ANCHOR
            ):
                # Suppressed non-anchors remain context only (C.1 semantics).
                continue
            rule_id = finding_ref.rule_id
            taxonomy = finding_ref.concept_id
            t_ms = finding_ref.t_ms
            finding_obj = finding_by_id.get(finding_ref.finding_id)
            conf = float(finding_obj.confidence) if finding_obj is not None else 0.5
            # Finding confidence is not decision confidence; cap for signal use.
            conf = min(conf, 0.85)

            # C.2 decision UNKNOWN must not become POOR via synthesis.
            decision_unknown = True
            for fi in interp.findings:
                if fi.finding_id == finding_ref.finding_id:
                    decision_unknown = fi.decision.state is QualityState.UNKNOWN
                    break

            for mapping in mappings_for(rule_id):
                gaps = list(mapping.forbidden_claims)
                concept = concept_for(mapping.concept_id)
                if concept is not None:
                    gaps.extend(
                        req
                        for req in concept.evidence_requirements
                        if req
                        in {
                            "true_player_fog_or_vision",
                            "ward_positions_and_coverage",
                            "minion_counts_hp_wave_direction",
                            "pov_mechanical_or_visual_evidence",
                            "summoner_loadout_and_cooldown_state",
                        }
                    )
                reasons = list(mapping.reason_codes)
                if decision_unknown:
                    reasons.append(
                        ReasonCode(
                            "C2_DECISION_REMAINS_UNKNOWN",
                            "Concept signal must not imply decision quality",
                        )
                    )
                sid = signal_id(mapping.concept_id, finding_ref.finding_id, interp.id)
                signals.append(
                    ConceptSignal(
                        id=sid,
                        concept_id=mapping.concept_id,
                        finding_id=finding_ref.finding_id,
                        rule_id=rule_id,
                        interpretation_id=interp.id,
                        episode_id=episode.id,
                        direction=mapping.direction,
                        specificity=mapping.specificity,
                        confidence=conf if mapping.primary else min(conf, 0.6),
                        reason_codes=tuple(reasons),
                        support=(
                            EvidenceRef("finding", finding_ref.finding_id, rule_id),
                            EvidenceRef("interpretation", interp.id, "c2"),
                            EvidenceRef("episode", episode.id, "c1"),
                        ),
                        conflicts=(),
                        gaps=tuple(sorted(set(gaps))),
                        t_ms=t_ms,
                        taxonomy_concept_id=taxonomy,
                        provenance=Provenance(
                            producer=SYNTHESIS_PRODUCER,
                            producer_version=SYNTHESIS_PRODUCER_VERSION,
                            upstream=(finding_ref.finding_id, interp.id, episode.id),
                        ),
                    )
                )

    signals.sort(key=lambda item: (item.t_ms, item.concept_id, item.finding_id, item.id))
    return signals


def _temporal_relation(delta_ms: int) -> CausalRelation:
    if delta_ms < 0:
        return CausalRelation.TEMPORALLY_PRECEDES
    if delta_ms > 0:
        return CausalRelation.TEMPORALLY_FOLLOWS
    return CausalRelation.TEMPORALLY_OVERLAPS


def _build_hypotheses(signals: Sequence[ConceptSignal]) -> list[CausalHypothesis]:
    """Build conservative hypotheses. Never SUPPORTED from temporal proximity alone."""
    if len(signals) < 2:
        return []

    # Deduplicate to primary signals for pairing to avoid combinatorial explosion.
    primaries = [
        item
        for item in signals
        if item.specificity
        in {ConceptSpecificity.SPECIFIC, ConceptSpecificity.GENERAL, ConceptSpecificity.BROAD}
    ]
    # Prefer one signal per finding for causal pairing.
    by_finding: dict[str, ConceptSignal] = {}
    for item in primaries:
        current = by_finding.get(item.finding_id)
        if current is None or item.confidence > current.confidence:
            by_finding[item.finding_id] = item
    ordered = sorted(by_finding.values(), key=lambda item: (item.t_ms, item.finding_id))

    hypotheses: list[CausalHypothesis] = []
    for i, earlier in enumerate(ordered):
        for later in ordered[i + 1 :]:
            delta = later.t_ms - earlier.t_ms
            relation = _temporal_relation(-delta)  # earlier precedes later
            # Flip: earlier is upstream
            relation = CausalRelation.TEMPORALLY_PRECEDES
            codes = [
                ReasonCode(
                    "TEMPORAL_ORDER_ONLY",
                    "Temporal precedence alone cannot yield SUPPORTED causality",
                )
            ]
            status = CausalStatus.UNKNOWN
            conf = 0.15
            h8 = False
            blocking = (
                "no_direct_gst_causality",
                "temporal_proximity_insufficient",
            )

            same_concept = earlier.concept_id == later.concept_id
            if same_concept:
                codes.append(ReasonCode("SHARES_CONCEPT", earlier.concept_id))
                relation = CausalRelation.SHARES_CONCEPT
                status = CausalStatus.UNKNOWN
                conf = 0.2

            # H.8 prior: taxonomy cause → symptom may elevate to PLAUSIBLE only.
            if earlier.taxonomy_concept_id and later.taxonomy_concept_id:
                if h8_edge_pair(earlier.taxonomy_concept_id, later.taxonomy_concept_id):
                    h8 = True
                    status = CausalStatus.PLAUSIBLE
                    relation = CausalRelation.SUPPORTED_CONTRIBUTOR
                    conf = 0.45
                    codes.append(
                        ReasonCode(
                            "H8_CAUSAL_GRAPH_PRIOR",
                            f"{earlier.taxonomy_concept_id}->{later.taxonomy_concept_id}",
                        )
                    )
                    codes.append(
                        ReasonCode(
                            "H8_PRIOR_NOT_SUPPORTED",
                            "Graph prior without revalidated causal test ≠ SUPPORTED",
                        )
                    )
                related = h8_related_rule_ids(later.taxonomy_concept_id)
                if earlier.rule_id in related and delta <= 180_000:
                    h8 = True
                    if status is CausalStatus.UNKNOWN:
                        status = CausalStatus.PLAUSIBLE
                        relation = CausalRelation.POTENTIAL_ANTECEDENT
                        conf = max(conf, 0.35)
                    codes.append(
                        ReasonCode(
                            "H8_RELATED_RULE_NEAR_PRIOR",
                            f"{earlier.rule_id} near symptom {later.taxonomy_concept_id}",
                        )
                    )

            # Unrelated taxonomy + different concepts + large gap → mark UNRELATED.
            if (
                not h8
                and not same_concept
                and earlier.taxonomy_concept_id
                and later.taxonomy_concept_id
                and earlier.taxonomy_concept_id.split(".")[0]
                != later.taxonomy_concept_id.split(".")[0]
                and delta > 120_000
            ):
                relation = CausalRelation.UNRELATED
                status = CausalStatus.UNKNOWN
                codes.append(ReasonCode("DOMAIN_DIVERGENT_TEMPORAL_PAIR"))

            hid = hypothesis_id(earlier.id, later.id, relation.value)
            hypotheses.append(
                CausalHypothesis(
                    id=hid,
                    upstream_ref=earlier.id,
                    downstream_ref=later.id,
                    upstream_concept_id=earlier.concept_id,
                    downstream_concept_id=later.concept_id,
                    relation=relation,
                    status=status,
                    temporal_delta_ms=delta,
                    confidence=conf,
                    method="c3_temporal_h8_prior",
                    reason_codes=tuple(codes),
                    support=(
                        EvidenceRef("signal", earlier.id),
                        EvidenceRef("signal", later.id),
                    ),
                    conflicts=(),
                    blocking_gaps=blocking,
                    h8_prior=h8,
                )
            )

    # Never emit SUPPORTED without a registered contract.
    assert all(item.status is not CausalStatus.SUPPORTED for item in hypotheses)
    hypotheses.sort(key=lambda item: (item.temporal_delta_ms or 0, item.id))
    return hypotheses


def _polarity(pos: int, neg: int, neu: int) -> LessonPolarity:
    if pos and neg:
        return LessonPolarity.MIXED
    if neg and not pos:
        return LessonPolarity.CONSISTENT_NEGATIVE
    if pos and not neg:
        return LessonPolarity.CONSISTENT_POSITIVE
    if neu:
        return LessonPolarity.INSUFFICIENT
    return LessonPolarity.INSUFFICIENT


def _support_level(
    *,
    occurrences: int,
    polarity: LessonPolarity,
    resolved_fraction: float,
    has_decision_block: bool,
    gaps: Sequence[str],
    mixed: bool,
) -> SupportLevel:
    if occurrences <= 0:
        return SupportLevel.INSUFFICIENT
    if mixed or polarity is LessonPolarity.INSUFFICIENT:
        return SupportLevel.WEAK if occurrences >= 2 else SupportLevel.INSUFFICIENT
    if has_decision_block and occurrences == 1:
        base = SupportLevel.WEAK
    elif occurrences >= 3 and resolved_fraction < 0.5:
        base = SupportLevel.MODERATE
    elif occurrences >= 2:
        base = SupportLevel.WEAK
    else:
        base = SupportLevel.WEAK
    # Condition resolution reduces persistence strength, not decision correctness.
    if resolved_fraction >= 0.5 and base is SupportLevel.MODERATE:
        base = SupportLevel.WEAK
    if gaps and base is SupportLevel.MODERATE:
        base = SupportLevel.WEAK
    # C.3 never claims STRONG without multi-signal + low gaps + no resolution washout
    if (
        occurrences >= 3
        and resolved_fraction < 0.25
        and not mixed
        and not has_decision_block
        and len(gaps) <= 1
    ):
        return SupportLevel.MODERATE
    return base


def _specificity_for(signals: Sequence[ConceptSignal]) -> ConceptSpecificity:
    order = {
        ConceptSpecificity.UNRESOLVED: 0,
        ConceptSpecificity.BROAD: 1,
        ConceptSpecificity.GENERAL: 2,
        ConceptSpecificity.SPECIFIC: 3,
    }
    # Prefer the most specific among signals, but never upgrade beyond evidence.
    best = ConceptSpecificity.UNRESOLVED
    for item in signals:
        if order[item.specificity] > order[best]:
            best = item.specificity
    return best


def synthesize_lesson_candidates(
    episodes: Sequence[CoachingEpisode],
    interpretations: Sequence[EpisodeInterpretation],
    findings: Sequence[Finding] | None = None,
    *,
    include_capabilities: bool = True,
) -> SynthesisResult:
    """Synthesize concept signals, causal hypotheses, and lesson candidates.

    Empty episodes/interpretations → empty lessons (no synthetic lesson).
    """
    if not episodes or not interpretations:
        caps = evaluate_capability_readiness() if include_capabilities else ()
        match_id = episodes[0].match_id if episodes else ""
        pid = episodes[0].participant_id if episodes else 0
        empty = empty_synthesis(match_id, pid)
        return SynthesisResult(
            schema_version=empty.schema_version,
            match_id=empty.match_id,
            participant_id=empty.participant_id,
            signals=(),
            hypotheses=(),
            lessons=(),
            capabilities=caps,
        )

    match_id = episodes[0].match_id
    participant_id = episodes[0].participant_id
    signals = map_concept_signals(episodes, interpretations, findings)
    hypotheses = _build_hypotheses(signals)

    # Resolution notes from C.1 via interpretations.
    resolved_findings: set[str] = set()
    resolution_notes: list[str] = []
    for interp in interpretations:
        for row in interp.condition_resolutions:
            if row.status is ResolutionStatus.RESOLVED:
                resolved_findings.add(row.finding_id)
                resolution_notes.append(
                    f"{row.finding_id}:{row.status.value}:{row.resolver}"
                )

    by_concept: dict[str, list[ConceptSignal]] = defaultdict(list)
    for signal in signals:
        by_concept[signal.concept_id].append(signal)

    hyp_by_concept: dict[str, list[CausalHypothesis]] = defaultdict(list)
    for hyp in hypotheses:
        hyp_by_concept[hyp.upstream_concept_id].append(hyp)
        hyp_by_concept[hyp.downstream_concept_id].append(hyp)

    lessons: list[LessonCandidate] = []
    for concept_id in sorted(by_concept):
        group = by_concept[concept_id]
        pos = [item for item in group if item.direction is SignalDirection.POSITIVE]
        neg = [item for item in group if item.direction is SignalDirection.NEGATIVE]
        neu = [
            item
            for item in group
            if item.direction in {SignalDirection.NEUTRAL, SignalDirection.UNKNOWN}
        ]
        polarity = _polarity(len(pos), len(neg), len(neu))
        mixed = polarity is LessonPolarity.MIXED
        finding_ids = tuple(sorted({item.finding_id for item in group}))
        resolved_count = sum(1 for fid in finding_ids if fid in resolved_findings)
        resolved_fraction = (
            resolved_count / len(finding_ids) if finding_ids else 0.0
        )
        gaps = sorted({gap for item in group for gap in item.gaps})
        has_decision_block = any(
            code.code == "C2_DECISION_REMAINS_UNKNOWN"
            for item in group
            for code in item.reason_codes
        )
        occurrences = len({item.finding_id for item in group})
        support = _support_level(
            occurrences=occurrences,
            polarity=polarity,
            resolved_fraction=resolved_fraction,
            has_decision_block=has_decision_block,
            gaps=gaps,
            mixed=mixed,
        )
        specificity = _specificity_for(group)
        readiness = LessonReadiness.CANDIDATE
        concept = concept_for(concept_id)
        if concept is not None and concept.capability_status.value == "BLOCKED":
            # Still emit candidate for tracking, but mark blocked for specialized use.
            if concept_id in {"wave.management", "mechanics.execution", "combat.summoner_usage"}:
                readiness = LessonReadiness.BLOCKED
        if support is SupportLevel.INSUFFICIENT:
            readiness = LessonReadiness.INSUFFICIENT

        conflicts: list[EvidenceRef] = []
        if mixed:
            conflicts.extend(EvidenceRef("signal", item.id, "positive") for item in pos)
            conflicts.extend(EvidenceRef("signal", item.id, "negative") for item in neg)

        reason_codes = [
            ReasonCode("LESSON_FROM_CONCEPT_SIGNALS", concept_id),
            ReasonCode("WITHIN_MATCH_ONLY", "not cross-game habit"),
        ]
        if resolved_fraction > 0:
            reason_codes.append(
                ReasonCode(
                    "CONDITION_RESOLUTION_REDUCES_PERSISTENCE",
                    "RESOLVED does not prove original decision was correct",
                )
            )
        if has_decision_block:
            reason_codes.append(
                ReasonCode(
                    "NO_DECISION_QUALITY_SMUGGLED",
                    "C.2 UNKNOWN preserved",
                )
            )

        related_hyps = hyp_by_concept.get(concept_id, [])
        lessons.append(
            LessonCandidate(
                id=lesson_id(concept_id, match_id, participant_id),
                schema_version=CONCEPTS_SCHEMA_VERSION,
                concept_id=concept_id,
                match_id=match_id,
                participant_id=participant_id,
                episode_ids=tuple(sorted({item.episode_id for item in group})),
                finding_ids=finding_ids,
                interpretation_ids=tuple(
                    sorted({item.interpretation_id for item in group})
                ),
                positive_signal_ids=tuple(sorted(item.id for item in pos)),
                negative_signal_ids=tuple(sorted(item.id for item in neg)),
                neutral_signal_ids=tuple(sorted(item.id for item in neu)),
                causal_hypothesis_ids=tuple(sorted({item.id for item in related_hyps})),
                polarity=polarity,
                support_level=support,
                readiness=readiness,
                specificity=specificity,
                within_match_occurrences=occurrences,
                confidence=min(item.confidence for item in group) if group else 0.0,
                context_gaps=tuple(gaps),
                conflicting_evidence=tuple(conflicts),
                condition_resolution_notes=tuple(
                    note
                    for note in resolution_notes
                    if any(fid in note for fid in finding_ids)
                ),
                reason_codes=tuple(reason_codes),
                provenance=Provenance(
                    producer=SYNTHESIS_PRODUCER,
                    producer_version=SYNTHESIS_PRODUCER_VERSION,
                    upstream=tuple(sorted({item.id for item in group})),
                ),
            )
        )

    lessons.sort(key=lambda item: (item.concept_id, item.id))
    caps = evaluate_capability_readiness() if include_capabilities else ()
    return SynthesisResult(
        schema_version=CONCEPTS_SCHEMA_VERSION,
        match_id=match_id,
        participant_id=participant_id,
        signals=tuple(signals),
        hypotheses=tuple(hypotheses),
        lessons=tuple(lessons),
        capabilities=caps,
        method=SYNTHESIS_METHOD,
        method_version=SYNTHESIS_METHOD_VERSION,
    )
