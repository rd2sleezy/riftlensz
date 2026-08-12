"""Visual clip-analysis spike (V.0 baseline + V.1 tracking). Isolated from coaching.

Depends on the R.11 observation contract. The observation contract does not
depend on this package. Do not import this module from H.6/H.7/H.8.
"""

from __future__ import annotations

from riftlens.visual.analyze import (
    ANALYZER_ID,
    ANALYZER_VERSION,
    DEFAULT_SAMPLE_FPS,
    VisualAnalysisResult,
    analyze_capture_dir,
    analyze_manifest,
)
from riftlens.visual.correlate import CorrelationStatus, SubjectCorrelation, correlate_subject
from riftlens.visual.detect import (
    MAX_PLAUSIBLE_CHAMPIONS,
    DetectedBar,
    ViewportCoverage,
    classify_viewport,
    detect_champion_like_bars,
)
from riftlens.visual.errors import (
    ArtifactMissing,
    CaptureNotRequested,
    CaptureWindowError,
    EmptyClip,
    MalformedVideo,
    VisualSpikeError,
)
from riftlens.visual.gst_align import GstAlignment, align_gst
from riftlens.visual.report import (
    StructuredClaim,
    VisualRuleDiagnostic,
    classify_against_claim,
    classify_v1_against_claim,
    format_timeline,
    format_v1_timeline,
)
from riftlens.visual.sampling import SampledFrame, sample_clip
from riftlens.visual.track import (
    CandidateKind,
    EntityTrack,
    TeamEstimate,
    TrackLifecycle,
    track_candidates,
)
from riftlens.visual.v1_analyze import (
    DEFAULT_V1_SAMPLE_FPS,
    V1_ANALYZER_ID,
    V1_ANALYZER_VERSION,
    V1AnalysisResult,
    analyze_capture_dir_v1,
    analyze_manifest_v1,
)
from riftlens.visual.window import (
    FindingStamp,
    PlannedCapture,
    capture_request_for_window,
    capture_window_for_finding,
    select_finding,
)

__all__ = [
    "ANALYZER_ID",
    "ANALYZER_VERSION",
    "DEFAULT_SAMPLE_FPS",
    "DEFAULT_V1_SAMPLE_FPS",
    "ArtifactMissing",
    "MAX_PLAUSIBLE_CHAMPIONS",
    "CandidateKind",
    "CaptureNotRequested",
    "CaptureWindowError",
    "CorrelationStatus",
    "DetectedBar",
    "EmptyClip",
    "EntityTrack",
    "FindingStamp",
    "GstAlignment",
    "MalformedVideo",
    "PlannedCapture",
    "SampledFrame",
    "StructuredClaim",
    "SubjectCorrelation",
    "TeamEstimate",
    "TrackLifecycle",
    "V1_ANALYZER_ID",
    "V1_ANALYZER_VERSION",
    "V1AnalysisResult",
    "ViewportCoverage",
    "VisualAnalysisResult",
    "VisualRuleDiagnostic",
    "VisualSpikeError",
    "align_gst",
    "analyze_capture_dir",
    "analyze_capture_dir_v1",
    "analyze_manifest",
    "analyze_manifest_v1",
    "capture_request_for_window",
    "capture_window_for_finding",
    "classify_against_claim",
    "classify_v1_against_claim",
    "classify_viewport",
    "correlate_subject",
    "detect_champion_like_bars",
    "format_timeline",
    "format_v1_timeline",
    "sample_clip",
    "select_finding",
    "track_candidates",
]
