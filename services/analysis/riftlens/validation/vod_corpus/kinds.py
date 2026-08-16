"""Media kind labels for VIDEO validation. Only REAL counts toward H.10/H.12."""

from __future__ import annotations

from enum import StrEnum


class MediaKind(StrEnum):
    """How a catalogued recording was produced."""

    REAL = "REAL"
    SYNTHETIC = "SYNTHETIC"
    REPLAY_GENERATED = "REPLAY-GENERATED"
    R10_CLIP = "R10-CLIP"


class CoverageKind(StrEnum):
    """Whether the file covers a whole match or a slice."""

    FULL_GAME = "full-game"
    PARTIAL = "partial"


class GamePhase(StrEnum):
    """Independent checkpoint phase label. Not inferred from H.10."""

    EARLY = "early"
    MID = "mid"
    LATE = "late"
    CUT = "cut"
    PAUSE = "pause"
    RESUME = "resume"
    UNKNOWN = "unknown"


class FailureClass(StrEnum):
    """Why auto-sync failed or must not be trusted."""

    OCR_INSUFFICIENT = "ocr_insufficient"
    OCR_CONFIDENTLY_WRONG = "ocr_confidently_wrong"
    ROI_LAYOUT_FAILURE = "roi_layout_failure"
    RESOLUTION_HUD_SCALE = "resolution_hud_scale"
    CUT_SEGMENTATION_FAILURE = "cut_segmentation_failure"
    PAUSE_HANDLING_FAILURE = "pause_handling_failure"
    MULTI_GAME_DETECTION = "multi_game_detection"
    VERIFICATION_FAILURE = "verification_failure"
    INSUFFICIENT_COVERAGE = "insufficient_coverage"
    INCORRECT_MATCH_PAIRING = "incorrect_match_pairing"
    WRONG_SYNC = "wrong_sync"
    OTHER = "other"


ACCEPTANCE_KINDS = frozenset({MediaKind.REAL})
EXPERIMENTAL_KINDS = frozenset(
    {MediaKind.R10_CLIP, MediaKind.REPLAY_GENERATED, MediaKind.SYNTHETIC}
)

# Glyph templates currently in resources/vision/glyphs/league/24px.
ATLAS_TRAIN_MATCH_IDS = frozenset({"NA1_5620410094"})
