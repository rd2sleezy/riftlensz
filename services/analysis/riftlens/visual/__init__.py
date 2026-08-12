"""V.0 visual clip-analysis spike. Isolated from production coaching.

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
from riftlens.visual.detect import (
    MAX_PLAUSIBLE_CHAMPIONS,
    DetectedBar,
    detect_champion_like_bars,
)
from riftlens.visual.errors import (
    ArtifactMissing,
    EmptyClip,
    MalformedVideo,
    VisualSpikeError,
)
from riftlens.visual.report import (
    StructuredClaim,
    VisualRuleDiagnostic,
    classify_against_claim,
    format_timeline,
)
from riftlens.visual.sampling import SampledFrame, sample_clip

__all__ = [
    "ANALYZER_ID",
    "ANALYZER_VERSION",
    "DEFAULT_SAMPLE_FPS",
    "ArtifactMissing",
    "MAX_PLAUSIBLE_CHAMPIONS",
    "DetectedBar",
    "EmptyClip",
    "MalformedVideo",
    "SampledFrame",
    "StructuredClaim",
    "VisualAnalysisResult",
    "VisualRuleDiagnostic",
    "VisualSpikeError",
    "analyze_capture_dir",
    "analyze_manifest",
    "classify_against_claim",
    "detect_champion_like_bars",
    "format_timeline",
    "sample_clip",
]
