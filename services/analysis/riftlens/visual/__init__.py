"""Visual clip-analysis spike (V.0–V.5). Isolated from coaching.

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
from riftlens.visual.continuity import ContinuityBundle, ContinuityCue, CueType, CueVerdict
from riftlens.visual.correlate import CorrelationStatus, SubjectCorrelation, correlate_subject
from riftlens.visual.correlate_v5 import V5CorrelationResult, refine_subject_correlation
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
    classify_v2_against_claim,
    format_timeline,
    format_v1_timeline,
    format_v2_timeline,
)
from riftlens.visual.sampling import SampledFrame, sample_clip
from riftlens.visual.team_calibrate import CalibrationConfidence, TeamCalibration
from riftlens.visual.track import (
    CandidateKind,
    EntityTrack,
    TeamEstimate,
    TrackLifecycle,
    track_candidates,
)
from riftlens.visual.trajectory import MotionClass, TrajectoryCue, measure_trajectory
from riftlens.visual.v1_analyze import (
    DEFAULT_V1_SAMPLE_FPS,
    V1_ANALYZER_ID,
    V1_ANALYZER_VERSION,
    V1AnalysisResult,
    analyze_capture_dir_v1,
    analyze_manifest_v1,
)
from riftlens.visual.v2_analyze import (
    DEFAULT_V2_SAMPLE_FPS,
    V2_ANALYZER_ID,
    V2_ANALYZER_VERSION,
    V2AnalysisResult,
    analyze_capture_dir_v2,
    analyze_manifest_v2,
)
from riftlens.visual.v4_analyze import (
    DEFAULT_V4_SAMPLE_FPS,
    V4_ANALYZER_ID,
    V4_ANALYZER_VERSION,
    V4AnalysisResult,
    analyze_capture_dir_v4,
    analyze_manifest_v4,
)
from riftlens.visual.v5_analyze import (
    DEFAULT_V5_SAMPLE_FPS,
    V5_ANALYZER_ID,
    V5_ANALYZER_VERSION,
    V5AnalysisResult,
    analyze_capture_dir_v5,
    analyze_manifest_v5,
    refine_v4_result,
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
    "DEFAULT_V2_SAMPLE_FPS",
    "DEFAULT_V4_SAMPLE_FPS",
    "DEFAULT_V5_SAMPLE_FPS",
    "ArtifactMissing",
    "MAX_PLAUSIBLE_CHAMPIONS",
    "CalibrationConfidence",
    "CandidateKind",
    "CaptureNotRequested",
    "CaptureWindowError",
    "ContinuityBundle",
    "ContinuityCue",
    "CorrelationStatus",
    "CueType",
    "CueVerdict",
    "DetectedBar",
    "EmptyClip",
    "EntityTrack",
    "FindingStamp",
    "GstAlignment",
    "MalformedVideo",
    "MotionClass",
    "PlannedCapture",
    "SampledFrame",
    "StructuredClaim",
    "SubjectCorrelation",
    "TeamCalibration",
    "TeamEstimate",
    "TrackLifecycle",
    "TrajectoryCue",
    "V1_ANALYZER_ID",
    "V1_ANALYZER_VERSION",
    "V1AnalysisResult",
    "V2_ANALYZER_ID",
    "V2_ANALYZER_VERSION",
    "V2AnalysisResult",
    "V4_ANALYZER_ID",
    "V4_ANALYZER_VERSION",
    "V4AnalysisResult",
    "V5_ANALYZER_ID",
    "V5_ANALYZER_VERSION",
    "V5AnalysisResult",
    "V5CorrelationResult",
    "ViewportCoverage",
    "VisualAnalysisResult",
    "VisualRuleDiagnostic",
    "VisualSpikeError",
    "align_gst",
    "analyze_capture_dir",
    "analyze_capture_dir_v1",
    "analyze_capture_dir_v2",
    "analyze_capture_dir_v4",
    "analyze_capture_dir_v5",
    "analyze_manifest",
    "analyze_manifest_v1",
    "analyze_manifest_v2",
    "analyze_manifest_v4",
    "analyze_manifest_v5",
    "capture_request_for_window",
    "capture_window_for_finding",
    "classify_against_claim",
    "classify_v1_against_claim",
    "classify_v2_against_claim",
    "classify_viewport",
    "correlate_subject",
    "detect_champion_like_bars",
    "format_timeline",
    "format_v1_timeline",
    "format_v2_timeline",
    "measure_trajectory",
    "refine_subject_correlation",
    "refine_v4_result",
    "sample_clip",
    "select_finding",
    "track_candidates",
]
