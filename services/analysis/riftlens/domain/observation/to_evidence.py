from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from riftlens.domain.enums import EvidenceKind, Source
from riftlens.domain.evidence import Evidence
from riftlens.domain.observation.common import never_increase_confidence
from riftlens.domain.observation.entity import EntityObservation
from riftlens.domain.observation.enums import KnowledgeState, VisibilityState, VisualClaimKind
from riftlens.domain.observation.frame_observation import FrameObservation
from riftlens.domain.observation.hud import HudValue

_RIOT_SOURCES = frozenset(
    {Source.RIOT_TIMELINE, Source.RIOT_MATCH, Source.DERIVED, Source.USER, Source.CV}
)


def evidence_origin_label(source: Source) -> str:
    """Return the H.8 display label for an evidence source (§8.2)."""
    if source is Source.VISUAL:
        return "observed from replay footage"
    if source is Source.VISUAL_INFERRED:
        return "inferred from replay footage"
    if source is Source.RIOT_TIMELINE:
        return "riot timeline"
    if source is Source.RIOT_MATCH:
        return "riot match"
    if source is Source.DERIVED:
        return "derived"
    if source is Source.CV:
        return "computer vision"
    if source is Source.USER:
        return "user"
    return source.value


def visual_source_for(observation: FrameObservation) -> Source:
    """Map claim kind onto Source.VISUAL / VISUAL_INFERRED. Never a Riot source."""
    if observation.source in _RIOT_SOURCES:
        raise ValueError("visual observation cannot become a Riot/GST evidence source")
    if observation.claim_kind is VisualClaimKind.INFERRED:
        return Source.VISUAL_INFERRED
    return Source.VISUAL


def frame_observation_to_evidence(
    observation: FrameObservation,
    *,
    label: str,
    value: Mapping[str, Any],
    claim_established: bool,
    confidence: float | None = None,
) -> Evidence | None:
    """Convert an explicit visual claim into H.6 Evidence.

    Returns None when the claim was not established (UNKNOWN / missing).
    Confidence is the min of observation confidence and any proposed value.
    """
    if not claim_established:
        return None
    kept = (
        observation.confidence
        if confidence is None
        else never_increase_confidence(observation.confidence, confidence)
    )
    payload = dict(value)
    payload.setdefault("observation_id", observation.observation_id)
    payload.setdefault("media_artifact_id", observation.media_artifact_id)
    payload.setdefault("capture_interval_id", observation.capture_interval_id)
    payload.setdefault("claim_kind", observation.claim_kind.value)
    return Evidence(
        kind=EvidenceKind.FRAME,
        label=label,
        value=payload,
        source=visual_source_for(observation),
        t_ms=observation.game_t_ms,
        confidence=kept,
        provenance=observation.as_provenance(),
    )


def entity_visibility_evidence(
    observation: FrameObservation,
    entity: EntityObservation,
) -> Evidence | None:
    """Emit visibility evidence only when the state was actually established.

    UNKNOWN visibility does not become ``enemy_not_visible``.
    NOT_VISIBLE requires KnowledgeState.ABSENT (known not present), not mere
    non-detection.
    """
    if entity.visibility is VisibilityState.UNKNOWN:
        return None
    if entity.visibility is VisibilityState.NOT_VISIBLE:
        known_absent = (
            entity.identity_knowledge is KnowledgeState.ABSENT
            or entity.participant_knowledge is KnowledgeState.ABSENT
        )
        if not known_absent:
            return None
    kept = never_increase_confidence(observation.confidence, entity.confidence)
    return frame_observation_to_evidence(
        observation,
        label="entity_visibility",
        value={
            "entity_observation_id": entity.entity_observation_id,
            "visibility": entity.visibility.value,
            "participant_id": entity.participant_id,
            "champion_id": entity.champion_id,
            "occluded": entity.occluded,
            "identity_knowledge": entity.identity_knowledge.value,
            "participant_knowledge": entity.participant_knowledge.value,
        },
        claim_established=True,
        confidence=kept,
    )


def hud_value_evidence(
    observation: FrameObservation,
    field_name: str,
    hud_value: HudValue,
) -> Evidence | None:
    """Emit HUD evidence only for established values. UNKNOWN/missing stay silent."""
    if hud_value.knowledge in {KnowledgeState.UNKNOWN, KnowledgeState.UNOBSERVABLE}:
        return None
    if hud_value.knowledge is KnowledgeState.ABSENT:
        kept = observation.confidence
        if hud_value.confidence is not None:
            kept = never_increase_confidence(observation.confidence, hud_value.confidence)
        return frame_observation_to_evidence(
            observation,
            label=f"hud_{field_name}",
            value={"field": field_name, "knowledge": hud_value.knowledge.value, "value": None},
            claim_established=True,
            confidence=kept,
        )
    if hud_value.value is None:
        return None
    kept = observation.confidence
    if hud_value.confidence is not None:
        kept = never_increase_confidence(observation.confidence, hud_value.confidence)
    return frame_observation_to_evidence(
        observation,
        label=f"hud_{field_name}",
        value={
            "field": field_name,
            "knowledge": hud_value.knowledge.value,
            "value": hud_value.value,
        },
        claim_established=True,
        confidence=kept,
    )
