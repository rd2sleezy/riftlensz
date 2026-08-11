"""R.10 frame capture: recording orchestration, artifact storage, budgets, retention."""

from __future__ import annotations

from riftlens.domain.capture import DEFAULT_CAPTURE_TIMEOUT_S
from riftlens.replay_host.capture.budgets import estimate_artifact_bytes, estimate_artifacts
from riftlens.replay_host.capture.capture_service import CaptureService
from riftlens.replay_host.capture.recording import (
    DEFAULT_POLL_INTERVAL_S,
    RecordingClient,
    RecordingOrchestrator,
    RecordingProgress,
    run_capture,
)
from riftlens.replay_host.capture.retention import (
    CleanupReport,
    RetentionPolicy,
    RetentionService,
)

__all__ = [
    "DEFAULT_CAPTURE_TIMEOUT_S",
    "DEFAULT_POLL_INTERVAL_S",
    "CaptureService",
    "CleanupReport",
    "RecordingClient",
    "RecordingOrchestrator",
    "RecordingProgress",
    "RetentionPolicy",
    "RetentionService",
    "estimate_artifact_bytes",
    "estimate_artifacts",
    "run_capture",
]
