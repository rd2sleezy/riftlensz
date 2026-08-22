"""Developer-only C.x real-match validation package."""

from __future__ import annotations

from riftlens.coaching.validation.cx_real_match import (
    CxValidationResult,
    assert_safe_output_path,
    format_human_report,
    load_patch_data,
    run_cx_pipeline,
    validate_participant_id,
)
from riftlens.coaching.validation.traceability import format_game_clock_ms

__all__ = [
    "CxValidationResult",
    "assert_safe_output_path",
    "format_game_clock_ms",
    "format_human_report",
    "load_patch_data",
    "run_cx_pipeline",
    "validate_participant_id",
]
