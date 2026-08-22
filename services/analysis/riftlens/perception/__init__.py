"""RP.1 rich replay perception — not a production coaching path."""

from __future__ import annotations

from riftlens.perception.assemble import assemble_rich_state, observe_frame
from riftlens.perception.capture import (
    CapturedFrame,
    frame_from_image_path,
    frame_from_pixels,
    nearest_sampled_frame,
    sample_capture_dir,
    sequence_around,
)
from riftlens.perception.debug import assert_debug_path_safe, default_debug_root, write_debug_bundle
from riftlens.perception.geometry import LayoutSupport, ScreenGeometry
from riftlens.perception.models import (
    PERCEPTION_SCHEMA_VERSION,
    CandidateKind,
    ObservationStatus,
    PerceptionCapabilityStatus,
    RichFrameObservation,
    RichReplayState,
    TeamClass,
    TrackState,
)
from riftlens.perception.report import render_rich_state

__all__ = [
    "PERCEPTION_SCHEMA_VERSION",
    "CapturedFrame",
    "CandidateKind",
    "LayoutSupport",
    "ObservationStatus",
    "PerceptionCapabilityStatus",
    "RichFrameObservation",
    "RichReplayState",
    "ScreenGeometry",
    "TeamClass",
    "TrackState",
    "assemble_rich_state",
    "assert_debug_path_safe",
    "default_debug_root",
    "frame_from_image_path",
    "frame_from_pixels",
    "nearest_sampled_frame",
    "observe_frame",
    "render_rich_state",
    "sample_capture_dir",
    "sequence_around",
    "write_debug_bundle",
]
