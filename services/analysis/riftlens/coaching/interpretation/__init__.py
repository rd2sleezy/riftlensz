"""C.2 decision and event interpretation over C.1 CoachingEpisode objects.

A bad outcome does not prove a poor decision.
A good outcome does not prove a good decision.
Temporal precedence does not prove causality.
Omniscient GST information does not prove player knowledge.
Condition resolution does not prove the original decision was correct.
UNKNOWN is a valid interpretation.

Not wired into H.11, UI, or persistence.
"""

from __future__ import annotations

from riftlens.coaching.interpretation.builder import (
    interpret_coaching_episode,
    interpret_coaching_episodes,
)
from riftlens.coaching.interpretation.catalog import (
    PRODUCTION_RULE_PROFILES,
    RuleSignalProfile,
    production_rule_ids,
    profile_for,
)
from riftlens.coaching.interpretation.models import (
    ALTERNATIVE_ANALYSIS_NOT_IMPLEMENTED,
    EPISODE_INTERPRETATION_SCHEMA_VERSION,
    INTERPRETATION_METHOD,
    ActionabilityAssessment,
    ActionabilityState,
    ClaimKind,
    ConditionResolutionView,
    DecisionAssessment,
    DecisionOutcomeRelation,
    EpisodeInterpretation,
    EvidencePointer,
    ExecutionAssessment,
    FindingInterpretation,
    InformationClaim,
    KnowledgeStatus,
    ObservedOutcome,
    OutcomeKind,
    OutcomePolarity,
    QualityState,
    ReasonCode,
    SignalType,
    TemporalObservation,
    TemporalRelation,
    derive_decision_outcome_relation,
    interpretation_id,
    not_observable_execution,
    unknown_decision,
)
from riftlens.coaching.interpretation.registry import (
    DEFAULT_INTERPRETER,
    DefaultFindingInterpreter,
    evidence_contracts,
    get_interpreter,
    register_interpreter,
)

__all__ = [
    "ALTERNATIVE_ANALYSIS_NOT_IMPLEMENTED",
    "DEFAULT_INTERPRETER",
    "EPISODE_INTERPRETATION_SCHEMA_VERSION",
    "INTERPRETATION_METHOD",
    "ActionabilityAssessment",
    "ActionabilityState",
    "ClaimKind",
    "ConditionResolutionView",
    "DecisionAssessment",
    "DecisionOutcomeRelation",
    "DefaultFindingInterpreter",
    "EpisodeInterpretation",
    "EvidencePointer",
    "ExecutionAssessment",
    "FindingInterpretation",
    "InformationClaim",
    "KnowledgeStatus",
    "ObservedOutcome",
    "OutcomeKind",
    "OutcomePolarity",
    "PRODUCTION_RULE_PROFILES",
    "QualityState",
    "ReasonCode",
    "RuleSignalProfile",
    "SignalType",
    "TemporalObservation",
    "TemporalRelation",
    "derive_decision_outcome_relation",
    "evidence_contracts",
    "get_interpreter",
    "interpret_coaching_episode",
    "interpret_coaching_episodes",
    "interpretation_id",
    "not_observable_execution",
    "production_rule_ids",
    "profile_for",
    "register_interpreter",
    "unknown_decision",
]
