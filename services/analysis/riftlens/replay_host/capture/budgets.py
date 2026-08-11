"""Budget helpers for R.10 (§7.3). Re-exports the pure domain check for capture callers."""

from __future__ import annotations

from riftlens.domain.capture import (
    DEFAULT_CAPTURE_BUDGET,
    CaptureBudget,
    CaptureUsage,
    check_budget,
)

__all__ = [
    "DEFAULT_CAPTURE_BUDGET",
    "CaptureBudget",
    "CaptureUsage",
    "check_budget",
    "estimate_artifact_bytes",
    "estimate_artifacts",
]

BYTES_PER_IMAGE_ESTIMATE = 2 * 1024 * 1024
BYTES_PER_CLIP_SECOND_ESTIMATE = 1024 * 1024


def estimate_artifacts(*, expected_artifacts: int, max_artifacts: int) -> int:
    """Return the artifact count charged against the budget before recording runs."""
    return max(1, min(int(expected_artifacts), int(max_artifacts)))


def estimate_artifact_bytes(*, kind: str, artifacts: int, duration_ms: int) -> int:
    """Return a pre-flight byte estimate. Deliberately pessimistic — refusals beat overruns."""
    if kind == "clip":
        seconds = max(0.0, duration_ms / 1000.0)
        return int(seconds * BYTES_PER_CLIP_SECOND_ESTIMATE)
    return int(max(1, artifacts) * BYTES_PER_IMAGE_ESTIMATE)
