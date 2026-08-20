"""C.1 coaching context: temporal episode containers around existing Findings.

A CoachingEpisode is a TEMPORAL AND FACTUAL CONTEXT CONTAINER.
Temporal association does not imply causality.
Condition resolution does not imply that the original decision was correct.

This package is not wired into H.11, the UI, or persistence.
"""

from __future__ import annotations

from riftlens.coaching.context.builder import build_coaching_episodes
from riftlens.coaching.context.models import (
    COACHING_EPISODE_SCHEMA_VERSION,
    EPISODE_GROUPING_SEMANTICS,
    CoachingEpisode,
    ConditionResolution,
    ContextGap,
    ContextGapStatus,
    ContextOrigin,
    ContextualValue,
    EpisodeBuilderConfig,
    FactRef,
    FightWindowRef,
    FindingAssociation,
    FindingRef,
    ParticipantStateSample,
    ResolutionStatus,
    SnapshotPoint,
    episode_id,
)

__all__ = [
    "COACHING_EPISODE_SCHEMA_VERSION",
    "EPISODE_GROUPING_SEMANTICS",
    "CoachingEpisode",
    "ConditionResolution",
    "ContextGap",
    "ContextGapStatus",
    "ContextOrigin",
    "ContextualValue",
    "EpisodeBuilderConfig",
    "FactRef",
    "FightWindowRef",
    "FindingAssociation",
    "FindingRef",
    "ParticipantStateSample",
    "ResolutionStatus",
    "SnapshotPoint",
    "build_coaching_episodes",
    "episode_id",
]
