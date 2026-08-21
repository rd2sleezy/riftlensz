"""Deterministic hard validity checks for coaching outputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from riftlens.coaching.evaluation.models import (
    FailureCategory,
    HardFailFinding,
    HardFailKind,
    NormalizedCoachingView,
)

BLOCKED_CONCEPTS = frozenset(
    {
        "wave.management",
        "mechanics.execution",
        "combat.summoner_usage",
        "risk.information_discipline",
    }
)

# Structural advice markers for blocked capabilities (not prose scoring).
_BLOCKED_ADVICE_MARKERS: dict[str, tuple[str, ...]] = {
    "wave.management": ("freeze", "slow push", "wave state", "crash timing"),
    "mechanics.execution": ("mechanics correction", "animation cancel", "aa cancel"),
    "combat.summoner_usage": ("flash here", "exact flash", "summoner timing"),
    "risk.information_discipline": ("ward placement quality", "ward geometry"),
}


def run_automated_checks(
    view: NormalizedCoachingView,
    *,
    case_constraints: Mapping[str, object] | None = None,
) -> tuple[HardFailFinding, ...]:
    """Structural hard-fail detection. Prefer fields over fragile text matching."""
    constraints = dict(case_constraints or {})
    findings: list[HardFailFinding] = []

    findings.extend(_check_decision_overreach(view, constraints))
    findings.extend(_check_causal_overreach(view, constraints))
    findings.extend(_check_player_knowledge(view, constraints))
    findings.extend(_check_capability_violation(view, constraints))
    findings.extend(_check_result_bias(view, constraints))
    findings.extend(_check_longitudinal_false_success(view, constraints))
    findings.extend(_check_false_progress(view, constraints))
    findings.extend(_check_fact_fabrication(view, constraints))

    return tuple(findings)


def _check_decision_overreach(
    view: NormalizedCoachingView, constraints: Mapping[str, object]
) -> list[HardFailFinding]:
    decision = (view.decision_quality or "").upper()
    claimed = str(
        view.structural.get("claimed_decision_quality")
        or constraints.get("claimed_decision_quality")
        or ""
    ).upper()
    if decision in {"UNKNOWN", "NOT_OBSERVABLE", ""} and claimed in {
        "GOOD",
        "POOR",
        "BAD",
        "CORRECT",
        "INCORRECT",
    }:
        return [
            HardFailFinding(
                kind=HardFailKind.DECISION_OVERREACH,
                category=FailureCategory.DECISION_OVERREACH,
                detail="Teaching claims definite decision quality while decision is UNKNOWN",
                evidence=(f"decision_quality={decision}", f"claimed={claimed}"),
            )
        ]
    # Also: if structural says decision UNKNOWN but alternative asserts definite bad/good
    if decision == "UNKNOWN" and bool(view.structural.get("asserts_definite_decision")):
        return [
            HardFailFinding(
                kind=HardFailKind.DECISION_OVERREACH,
                category=FailureCategory.DECISION_OVERREACH,
                detail="asserts_definite_decision with UNKNOWN decision_quality",
                evidence=("asserts_definite_decision=True",),
            )
        ]
    return []


def _check_causal_overreach(
    view: NormalizedCoachingView, constraints: Mapping[str, object]
) -> list[HardFailFinding]:
    causal = (view.causal_status or "").upper()
    asserts = bool(
        view.structural.get("asserts_definite_causality")
        or constraints.get("asserts_definite_causality")
    )
    if asserts and causal not in {"SUPPORTED", "ESTABLISHED"}:
        return [
            HardFailFinding(
                kind=HardFailKind.CAUSAL_OVERREACH,
                category=FailureCategory.CAUSAL_OVERREACH,
                detail="Definite caused-by claim without causal support",
                evidence=(f"causal_status={causal}",),
            )
        ]
    return []


def _check_player_knowledge(
    view: NormalizedCoachingView, constraints: Mapping[str, object]
) -> list[HardFailFinding]:
    pk = (view.player_knowledge or "").upper()
    claims_unseen = bool(
        view.structural.get("claims_player_could_not_see")
        or constraints.get("claims_player_could_not_see")
    )
    if claims_unseen and pk in {"UNKNOWN", "UNAVAILABLE", ""}:
        return [
            HardFailFinding(
                kind=HardFailKind.PLAYER_KNOWLEDGE_OVERREACH,
                category=FailureCategory.PLAYER_KNOWLEDGE_OVERREACH,
                detail=(
                    "Claims player could not see enemy while player knowledge "
                    "is UNKNOWN/UNAVAILABLE"
                ),
                evidence=(f"player_knowledge={pk}",),
            )
        ]
    return []


def _check_capability_violation(
    view: NormalizedCoachingView, constraints: Mapping[str, object]
) -> list[HardFailFinding]:
    findings: list[HardFailFinding] = []
    if view.structural.get("capability_violation"):
        findings.append(
            HardFailFinding(
                kind=HardFailKind.CAPABILITY_VIOLATION,
                category=FailureCategory.CAPABILITY_VIOLATION,
                detail=str(view.structural.get("capability_violation")),
                evidence=("structural.capability_violation",),
            )
        )

    raw_blocked = constraints.get("blocked_concepts", ())
    blocked_extra: set[str] = set()
    if isinstance(raw_blocked, (list, tuple, set, frozenset)):
        blocked_extra = {str(item) for item in raw_blocked}
    gives_advice = view.structural.get("gives_specific_blocked_advice")
    blob = " ".join(
        filter(
            None,
            [view.lesson, view.alternative, view.cue, view.drill, view.language_text],
        )
    ).lower()

    for concept in BLOCKED_CONCEPTS:
        status = (view.capability_statuses.get(concept) or "").upper()
        is_blocked = concept in blocked_extra or status == "BLOCKED"
        if not is_blocked and concept not in view.concept_ids:
            continue
        if not is_blocked and status != "BLOCKED":
            # Concept listed but capability map says ready — skip
            if concept not in view.capability_statuses:
                # Treat known blocked concept ids as blocked by default
                is_blocked = concept in BLOCKED_CONCEPTS and concept in view.concept_ids
        if not is_blocked:
            continue
        if gives_advice is False:
            continue
        markers = _BLOCKED_ADVICE_MARKERS.get(concept, ())
        marker_hit = any(marker in blob for marker in markers)
        if gives_advice is True or marker_hit:
            findings.append(
                HardFailFinding(
                    kind=HardFailKind.CAPABILITY_VIOLATION,
                    category=FailureCategory.CAPABILITY_VIOLATION,
                    detail=f"Specific advice for blocked capability {concept}",
                    evidence=(concept,),
                )
            )
    return findings


def _check_result_bias(
    view: NormalizedCoachingView, constraints: Mapping[str, object]
) -> list[HardFailFinding]:
    if bool(view.structural.get("uses_result_as_decision_proof")) or bool(
        constraints.get("uses_result_as_decision_proof")
    ):
        return [
            HardFailFinding(
                kind=HardFailKind.RESULT_BIAS,
                category=FailureCategory.UNSUPPORTED_INFERENCE,
                detail="Treats win/loss/kill/death as proof of decision quality",
                evidence=("uses_result_as_decision_proof",),
            )
        ]
    return []


def _check_longitudinal_false_success(
    view: NormalizedCoachingView, constraints: Mapping[str, object]
) -> list[HardFailFinding]:
    opp = (view.opportunity_status or "").upper()
    result = (view.objective_result or "").upper()
    if result == "SUCCESS" and opp in {
        "NO_OBSERVABLE_OPPORTUNITY",
        "UNKNOWN_OPPORTUNITY",
        "",
    }:
        if opp == "" and not constraints.get("require_opportunity_for_success"):
            return []
        return [
            HardFailFinding(
                kind=HardFailKind.LONGITUDINAL_FALSE_SUCCESS,
                category=FailureCategory.FALSE_LONGITUDINAL_PATTERN,
                detail="SUCCESS without observed opportunity",
                evidence=(f"opportunity={opp}", f"result={result}"),
            )
        ]
    return []


def _check_false_progress(
    view: NormalizedCoachingView, constraints: Mapping[str, object]
) -> list[HardFailFinding]:
    meas = (view.measurability or "").upper()
    long_status = (view.longitudinal_status or "").upper()
    if meas == "NOT_MEASURABLE" and long_status in {
        "RESOLVED",
        "IMPROVING",
        "SUCCESS",
    }:
        return [
            HardFailFinding(
                kind=HardFailKind.FALSE_PROGRESS,
                category=FailureCategory.FALSE_PROGRESS,
                detail="Progress/resolution claimed for NOT_MEASURABLE capability",
                evidence=(f"measurability={meas}", f"status={long_status}"),
            )
        ]
    if bool(view.structural.get("false_progress")) or bool(
        constraints.get("false_progress")
    ):
        return [
            HardFailFinding(
                kind=HardFailKind.FALSE_PROGRESS,
                category=FailureCategory.FALSE_PROGRESS,
                detail="Structural false_progress flag",
                evidence=("structural.false_progress",),
            )
        ]
    return []


def _check_fact_fabrication(
    view: NormalizedCoachingView, constraints: Mapping[str, object]
) -> list[HardFailFinding]:
    fabricated = view.structural.get("fabricated_facts") or constraints.get(
        "fabricated_facts"
    )
    if fabricated:
        items: Sequence[str]
        if isinstance(fabricated, (list, tuple)):
            items = tuple(str(item) for item in fabricated)
        else:
            items = (str(fabricated),)
        return [
            HardFailFinding(
                kind=HardFailKind.FACT_FABRICATION,
                category=FailureCategory.FACTUAL_ERROR,
                detail="Unsupported match fact claimed",
                evidence=items,
            )
        ]
    return []
