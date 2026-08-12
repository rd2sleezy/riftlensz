from __future__ import annotations

from riftlens.domain.observation.camera import CameraProvenance, camera_from_capture
from riftlens.domain.observation.common import (
    ScreenRect,
    confidence_band,
    never_increase_confidence,
)
from riftlens.domain.observation.entity import EntityObservation
from riftlens.domain.observation.enums import (
    FRAME_OBSERVATION_SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    CameraControl,
    ConfidenceBand,
    CorrelationMethod,
    KnowledgeState,
    ObservationPayloadError,
    UnsupportedObservationSchema,
    VisibilityState,
    VisualClaimKind,
)
from riftlens.domain.observation.frame_observation import FrameObservation
from riftlens.domain.observation.hud import KNOWN_HUD_FIELDS, HudObservation, HudValue
from riftlens.domain.observation.sequence import ObservationSequence, SampleGap, VisualWindow
from riftlens.domain.observation.serialize import (
    dumps,
    loads_frame,
    loads_sequence,
    to_canonical_json,
)
from riftlens.domain.observation.spatial import SpatialObservation
from riftlens.domain.observation.to_evidence import (
    entity_visibility_evidence,
    evidence_origin_label,
    frame_observation_to_evidence,
    hud_value_evidence,
    visual_source_for,
)

__all__ = [
    "FRAME_OBSERVATION_SCHEMA_VERSION",
    "KNOWN_HUD_FIELDS",
    "SUPPORTED_SCHEMA_VERSIONS",
    "CameraControl",
    "CameraProvenance",
    "ConfidenceBand",
    "CorrelationMethod",
    "EntityObservation",
    "FrameObservation",
    "HudObservation",
    "HudValue",
    "KnowledgeState",
    "ObservationPayloadError",
    "ObservationSequence",
    "SampleGap",
    "ScreenRect",
    "SpatialObservation",
    "UnsupportedObservationSchema",
    "VisibilityState",
    "VisualClaimKind",
    "VisualWindow",
    "camera_from_capture",
    "confidence_band",
    "dumps",
    "entity_visibility_evidence",
    "evidence_origin_label",
    "frame_observation_to_evidence",
    "hud_value_evidence",
    "loads_frame",
    "loads_sequence",
    "never_increase_confidence",
    "to_canonical_json",
    "visual_source_for",
]
