"""Extensible FindingInterpreter registry for C.2.

Interpreters emit structured assessments only. They never generate coaching prose
or non-UNKNOWN decision labels without a documented evidence contract.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from riftlens.coaching.context.models import CoachingEpisode, FindingRef
from riftlens.coaching.interpretation.catalog import RuleSignalProfile, profile_for
from riftlens.coaching.interpretation.models import (
    INTERPRETATION_METHOD,
    EvidencePointer,
    FindingInterpretation,
    ObservedOutcome,
    ReasonCode,
    not_observable_execution,
    unknown_decision,
)
from riftlens.domain.timeline import GameStateTimeline


@dataclass(frozen=True)
class InterpreterContext:
    """Inputs available to a FindingInterpreter. Assumes C.1 episode is complete."""

    gst: GameStateTimeline
    episode: CoachingEpisode
    finding: FindingRef
    profile: RuleSignalProfile


class FindingInterpreter(Protocol):
    """Deterministic per-finding interpreter."""

    def supported_rule_ids(self) -> frozenset[str]:
        """Return rule ids this interpreter handles."""

    def interpret(self, ctx: InterpreterContext) -> FindingInterpretation:
        """Return a structured finding interpretation. Assumes ctx.finding matches."""


_REGISTRY: dict[str, FindingInterpreter] = {}


def register_interpreter(interpreter: FindingInterpreter) -> FindingInterpreter:
    """Register ``interpreter`` for each of its rule ids. Last write wins."""
    for rule_id in interpreter.supported_rule_ids():
        _REGISTRY[rule_id] = interpreter
    return interpreter


def get_interpreter(rule_id: str) -> FindingInterpreter:
    """Return a registered interpreter or the default fail-closed interpreter."""
    return _REGISTRY.get(rule_id) or DEFAULT_INTERPRETER


def clear_interpreters() -> None:
    """Clear registry except the default. Intended for tests only."""
    _REGISTRY.clear()


@dataclass(frozen=True)
class DefaultFindingInterpreter:
    """Safe interpreter used for all production rules in C.2.

    Emits outcome polarity from the catalog. Decision remains UNKNOWN.
    Execution remains NOT_OBSERVABLE. No GOOD/POOR decision contracts ship.
    """

    _rule_ids: frozenset[str] = frozenset()
    method: str = INTERPRETATION_METHOD

    def supported_rule_ids(self) -> frozenset[str]:
        """Return explicitly claimed rule ids (empty → used as default)."""
        return self._rule_ids

    def interpret(self, ctx: InterpreterContext) -> FindingInterpretation:
        """Return fail-closed interpretation. Assumes finding labels are stable."""
        profile = ctx.profile
        support = (
            EvidencePointer(
                kind="finding",
                ref=ctx.finding.finding_id,
                t_ms=ctx.finding.t_ms,
                note="anchor finding reference",
            ),
        )
        outcome = ObservedOutcome(
            kind=profile.outcome_kind,
            polarity=profile.outcome_polarity,
            finding_id=ctx.finding.finding_id,
            rule_id=ctx.finding.rule_id,
            t_ms=ctx.finding.t_ms,
            confidence=0.7 if profile.outcome_polarity.value != "UNKNOWN" else 0.0,
            reason_codes=(
                ReasonCode(
                    "CATALOG_OUTCOME",
                    profile.notes,
                ),
            ),
            support=support,
        )
        decision = unknown_decision(method=self.method, missing=profile.missing_for_decision)
        execution = not_observable_execution(method=self.method)
        return FindingInterpretation(
            finding_id=ctx.finding.finding_id,
            rule_id=ctx.finding.rule_id,
            concept_id=ctx.finding.concept_id,
            signal_type=profile.signal_type,
            association=ctx.finding.association.value,
            suppressed=ctx.finding.suppressed,
            outcome=outcome,
            decision=decision,
            execution=execution,
            decision_assessable=profile.decision_assessable,
            execution_observable=profile.execution_observable,
        )


DEFAULT_INTERPRETER = DefaultFindingInterpreter()


def interpret_finding(
    gst: GameStateTimeline, episode: CoachingEpisode, finding: FindingRef
) -> FindingInterpretation:
    """Dispatch one finding through the registry. Assumes C.1 FindingRef is valid."""
    profile = profile_for(finding.rule_id)
    interpreter = get_interpreter(finding.rule_id)
    ctx = InterpreterContext(gst=gst, episode=episode, finding=finding, profile=profile)
    return interpreter.interpret(ctx)


InterpreterFactory = Callable[[], FindingInterpreter]


def registered_rule_ids() -> frozenset[str]:
    """Return rule ids with non-default registered interpreters."""
    return frozenset(_REGISTRY)


def evidence_contracts() -> Mapping[str, str]:
    """Return documented non-UNKNOWN decision contracts.

    Empty in C.2: no production rule currently has a defensible GOOD/POOR/MIXED
    decision contract under GST-only fail-closed rules.
    """
    return {}
