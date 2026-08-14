"""R.10 frame-capture domain (amendment §7). Pure values — no HTTP, disk, or DB."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from riftlens.domain.camera_framing import CameraFramingMetadata, CameraFramingPlan
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode

CAPTURE_MANIFEST_NAME = "manifest.json"
CAPTURE_ENGINE_VERSION = "r10"
DEFAULT_SAMPLED_FPS = 2.0
DEFAULT_CLIP_FPS = 30.0
MAX_CAPTURE_FPS = 60.0
DEFAULT_MAX_ARTIFACTS = 60
STILL_MAX_ARTIFACTS = 3
DEFAULT_CAPTURE_TIMEOUT_S = 600.0
DEFAULT_CAPTURE_POLL_S = 0.5
CODEC_PNG = "png"
CODEC_WEBM = "webm"
ARTIFACT_KIND_IMAGE = "image"
ARTIFACT_KIND_CLIP = "clip"

# Clip coverage: actual duration must meet both a ratio floor and an absolute slack.
CAPTURE_DURATION_MIN_RATIO = 0.90
CAPTURE_DURATION_ABS_SLACK_MS = 2_000


class CaptureCoverageVerdict(StrEnum):
    """Whether finalized media covers the requested game-time interval."""

    COVERED = "covered"
    TRUNCATED = "truncated"
    UNPROBED_API_COMPLETE = "unprobed_api_complete"
    NOT_APPLICABLE = "not_applicable"


class RecordingCompletionMethod(StrEnum):
    """How the recording wait loop decided encode finished."""

    API_RECORDING_FALSE = "api_recording_false"
    TEMP_STABLE_AFTER_END = "temp_stable_after_end"
    TIMEOUT_TEMP_PROMOTE = "timeout_temp_promote"
    WAIT_EXCEPTION_TEMP_PROMOTE = "wait_exception_temp_promote"


class CaptureMode(StrEnum):
    """Requested capture shape. STILL is a degenerate SAMPLED, not a separate path."""

    STILL = "STILL"
    SAMPLED = "SAMPLED"
    CLIP = "CLIP"


class RetentionClass(StrEnum):
    """Artifact lifetime. Values are the persisted ``retention_class`` strings."""

    EPHEMERAL = "ephemeral"
    REVIEW = "review"
    PINNED = "pinned"


class CaptureStatus(StrEnum):
    """Capture lifecycle. Values are the persisted ``capture_interval.status`` strings."""

    REQUESTED = "requested"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES: frozenset[CaptureStatus] = frozenset(
    {CaptureStatus.COMPLETE, CaptureStatus.FAILED, CaptureStatus.CANCELLED}
)
PARTIAL_STATUSES: frozenset[CaptureStatus] = frozenset(
    {CaptureStatus.FAILED, CaptureStatus.CANCELLED}
)


@dataclass(frozen=True)
class CaptureRequest:
    """One explicit user/rule capture ask. Times are canonical game milliseconds.

    ``camera_framing`` is capture-only opt-in. Ordinary reveal/seek/viewing never
    constructs a plan. When a plan is set and apply fails, capture continues only if
    ``allow_capture_without_framing`` is True.
    """

    source_id: str
    start_game_ms: int
    end_game_ms: int
    mode: CaptureMode
    fps: float | None = None
    max_artifacts: int = DEFAULT_MAX_ARTIFACTS
    retention: RetentionClass = RetentionClass.REVIEW
    review_id: str | None = None
    codec: str | None = None
    camera_framing: CameraFramingPlan | None = None
    allow_capture_without_framing: bool = True

    def __post_init__(self) -> None:
        if self.max_artifacts <= 0:
            raise ValueError("max_artifacts must be > 0")
        if self.fps is not None and self.fps <= 0:
            raise ValueError("fps must be > 0")

    @property
    def duration_ms(self) -> int:
        """Return the requested interval length. May be non-positive before validation."""
        return int(self.end_game_ms) - int(self.start_game_ms)


@dataclass(frozen=True)
class CaptureBudget:
    """Per-review capture ceilings (§7.3). Exceeding one is a typed refusal, not a degrade."""

    max_seconds: float
    max_artifacts: int
    max_bytes: int


DEFAULT_CAPTURE_BUDGET = CaptureBudget(
    max_seconds=120.0,
    max_artifacts=200,
    max_bytes=2 * 1024 * 1024 * 1024,
)


@dataclass(frozen=True)
class CaptureProgress:
    """Progress snapshot for a running capture. ``fraction`` is clamped to 0..1."""

    capture_id: str
    status: CaptureStatus
    fraction: float
    message: str
    current_source_ms: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "fraction", min(1.0, max(0.0, float(self.fraction))))


@dataclass(frozen=True)
class CaptureCoverage:
    """Post-finalize duration / completion evidence for one capture."""

    requested_start_game_ms: int
    requested_end_game_ms: int
    requested_duration_ms: int
    actual_duration_ms: int | None
    actual_frame_count: int | None
    coverage_verdict: CaptureCoverageVerdict
    completion_method: RecordingCompletionMethod | None
    temp_promotion_method: str | None
    api_dropout_count: int
    min_acceptable_duration_ms: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready mapping for the capture manifest."""
        return {
            "requested_start_game_ms": self.requested_start_game_ms,
            "requested_end_game_ms": self.requested_end_game_ms,
            "requested_duration_ms": self.requested_duration_ms,
            "actual_duration_ms": self.actual_duration_ms,
            "actual_frame_count": self.actual_frame_count,
            "coverage_verdict": self.coverage_verdict.value,
            "completion_method": (
                None if self.completion_method is None else self.completion_method.value
            ),
            "temp_promotion_method": self.temp_promotion_method,
            "api_dropout_count": self.api_dropout_count,
            "min_acceptable_duration_ms": self.min_acceptable_duration_ms,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CaptureCoverage:
        """Parse a mapping produced by ``to_dict``."""
        method_raw = payload.get("completion_method")
        method = RecordingCompletionMethod(str(method_raw)) if method_raw is not None else None
        return cls(
            requested_start_game_ms=int(payload["requested_start_game_ms"]),
            requested_end_game_ms=int(payload["requested_end_game_ms"]),
            requested_duration_ms=int(payload["requested_duration_ms"]),
            actual_duration_ms=_opt_int(payload.get("actual_duration_ms")),
            actual_frame_count=_opt_int(payload.get("actual_frame_count")),
            coverage_verdict=CaptureCoverageVerdict(str(payload["coverage_verdict"])),
            completion_method=method,
            temp_promotion_method=_opt_str(payload.get("temp_promotion_method")),
            api_dropout_count=int(payload.get("api_dropout_count") or 0),
            min_acceptable_duration_ms=int(payload["min_acceptable_duration_ms"]),
        )


def min_acceptable_capture_duration_ms(requested_duration_ms: int) -> int:
    """Return the shortest media duration that still counts as covering ``requested``."""
    requested = max(0, int(requested_duration_ms))
    if requested <= 0:
        return 0
    ratio_floor = int(round(requested * CAPTURE_DURATION_MIN_RATIO))
    abs_floor = max(0, requested - CAPTURE_DURATION_ABS_SLACK_MS)
    return max(ratio_floor, abs_floor)


def capture_duration_covers(
    *,
    requested_duration_ms: int,
    actual_duration_ms: int | None,
) -> bool:
    """Return True when probed media duration meets the explicit coverage tolerance."""
    if actual_duration_ms is None:
        return False
    return int(actual_duration_ms) >= min_acceptable_capture_duration_ms(requested_duration_ms)


@dataclass(frozen=True)
class CaptureArtifactSpec:
    """One written file. ``game_t_ms`` is authoritative and also encoded in the filename."""

    id: str
    kind: str
    relative_path: str
    game_t_ms: int
    sha256: str
    bytes: int
    source_t_ms: int | None = None
    width: int | None = None
    height: int | None = None
    frame_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready mapping for the manifest."""
        return {
            "id": self.id,
            "kind": self.kind,
            "relative_path": self.relative_path,
            "game_t_ms": self.game_t_ms,
            "source_t_ms": self.source_t_ms,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "width": self.width,
            "height": self.height,
            "frame_index": self.frame_index,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CaptureArtifactSpec:
        """Parse a mapping produced by ``to_dict``. Assumes keys are complete."""
        return cls(
            id=str(payload["id"]),
            kind=str(payload["kind"]),
            relative_path=str(payload["relative_path"]),
            game_t_ms=int(payload["game_t_ms"]),
            sha256=str(payload["sha256"]),
            bytes=int(payload["bytes"]),
            source_t_ms=_opt_int(payload.get("source_t_ms")),
            width=_opt_int(payload.get("width")),
            height=_opt_int(payload.get("height")),
            frame_index=_opt_int(payload.get("frame_index")),
        )


@dataclass(frozen=True)
class CaptureManifest:
    """Provenance record written beside the artifacts (§7.4, §8.2)."""

    capture_id: str
    source_id: str
    match_id: str
    clock_map_id: str | None
    mode: CaptureMode
    codec: str
    fps: float
    requested_start_game_ms: int
    requested_end_game_ms: int
    start_source_ms: int
    end_source_ms: int
    retention: RetentionClass
    status: CaptureStatus
    created_at_ms: int
    clock_confidence: str
    clock_verified: bool
    review_id: str | None = None
    completed_at_ms: int | None = None
    declared_patch: str | None = None
    camera_controlled: bool = False
    camera_framing: CameraFramingMetadata | None = None
    capture_coverage: CaptureCoverage | None = None
    engine_version: str = CAPTURE_ENGINE_VERSION
    artifacts: tuple[CaptureArtifactSpec, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON body written to ``manifest.json``."""
        body: dict[str, Any] = {
            "capture_id": self.capture_id,
            "source_id": self.source_id,
            "match_id": self.match_id,
            "clock_map_id": self.clock_map_id,
            "mode": self.mode.value,
            "codec": self.codec,
            "fps": self.fps,
            "requested_start_game_ms": self.requested_start_game_ms,
            "requested_end_game_ms": self.requested_end_game_ms,
            "start_source_ms": self.start_source_ms,
            "end_source_ms": self.end_source_ms,
            "retention_class": self.retention.value,
            "review_id": self.review_id,
            "status": self.status.value,
            "created_at_ms": self.created_at_ms,
            "completed_at_ms": self.completed_at_ms,
            "clock_confidence": self.clock_confidence,
            "clock_verified": self.clock_verified,
            "declared_patch": self.declared_patch,
            "camera_controlled": self.camera_controlled,
            "engine_version": self.engine_version,
            "artifacts": [item.to_dict() for item in self.artifacts],
        }
        if self.camera_framing is not None:
            body["camera_framing"] = self.camera_framing.to_dict()
        if self.capture_coverage is not None:
            body["capture_coverage"] = self.capture_coverage.to_dict()
        return body

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CaptureManifest:
        """Parse a mapping produced by ``to_dict``. Assumes the manifest was written by R.10."""
        raw_artifacts = payload.get("artifacts") or []
        framing_raw = payload.get("camera_framing")
        framing = (
            CameraFramingMetadata.from_dict(framing_raw)
            if isinstance(framing_raw, Mapping)
            else None
        )
        camera_controlled = bool(payload.get("camera_controlled", False))
        if framing is not None:
            camera_controlled = bool(framing.camera_controlled)
        coverage_raw = payload.get("capture_coverage")
        coverage = (
            CaptureCoverage.from_dict(coverage_raw) if isinstance(coverage_raw, Mapping) else None
        )
        return cls(
            capture_id=str(payload["capture_id"]),
            source_id=str(payload["source_id"]),
            match_id=str(payload["match_id"]),
            clock_map_id=_opt_str(payload.get("clock_map_id")),
            mode=CaptureMode(str(payload["mode"])),
            codec=str(payload["codec"]),
            fps=float(payload["fps"]),
            requested_start_game_ms=int(payload["requested_start_game_ms"]),
            requested_end_game_ms=int(payload["requested_end_game_ms"]),
            start_source_ms=int(payload["start_source_ms"]),
            end_source_ms=int(payload["end_source_ms"]),
            retention=RetentionClass(str(payload["retention_class"])),
            status=CaptureStatus(str(payload["status"])),
            created_at_ms=int(payload["created_at_ms"]),
            clock_confidence=str(payload["clock_confidence"]),
            clock_verified=bool(payload["clock_verified"]),
            review_id=_opt_str(payload.get("review_id")),
            completed_at_ms=_opt_int(payload.get("completed_at_ms")),
            declared_patch=_opt_str(payload.get("declared_patch")),
            camera_controlled=camera_controlled,
            camera_framing=framing,
            capture_coverage=coverage,
            engine_version=str(payload.get("engine_version", CAPTURE_ENGINE_VERSION)),
            artifacts=tuple(
                CaptureArtifactSpec.from_dict(item)
                for item in raw_artifacts
                if isinstance(item, Mapping)
            ),
        )


@dataclass(frozen=True)
class CaptureResult:
    """Outcome of a capture request or of the synchronous capture engine."""

    ok: bool
    capture_id: str
    status: CaptureStatus
    manifest: CaptureManifest | None = None
    artifacts: tuple[CaptureArtifactSpec, ...] = ()
    error: ReplayError | None = None
    progress: CaptureProgress | None = None
    camera_framing: CameraFramingMetadata | None = None
    capture_coverage: CaptureCoverage | None = None


@dataclass(frozen=True)
class ModeSettings:
    """Resolved recording parameters for a mode. ``expected_artifacts`` is a hint, not a cap."""

    codec: str
    fps: float
    kind: str
    expected_artifacts: int


@dataclass(frozen=True)
class CaptureUsage:
    """Captured totals already charged against a review budget."""

    seconds: float = 0.0
    artifacts: int = 0
    bytes: int = 0

    @classmethod
    def from_totals(cls, totals: Sequence[Any]) -> CaptureUsage:
        """Build usage from a ``(seconds, artifacts, bytes)`` triple."""
        seconds, artifacts, byte_count = totals
        return cls(seconds=float(seconds), artifacts=int(artifacts), bytes=int(byte_count))


def validate_interval(start_game_ms: int, end_game_ms: int) -> None:
    """Raise ``CAPTURE_INVALID_INTERVAL`` unless ``0 <= start < end``. Returns None otherwise."""
    start = int(start_game_ms)
    end = int(end_game_ms)
    if start < 0:
        raise ReplayError(
            ReplayErrorCode.CAPTURE_INVALID_INTERVAL,
            details={"reason": "negative_start", "start_game_ms": start},
        )
    if end <= start:
        raise ReplayError(
            ReplayErrorCode.CAPTURE_INVALID_INTERVAL,
            details={"reason": "end_not_after_start", "start_game_ms": start, "end_game_ms": end},
        )


def check_budget(
    budget: CaptureBudget,
    *,
    duration_ms: int,
    artifact_count: int,
    byte_count: int,
    existing_seconds: float = 0.0,
    existing_artifacts: int = 0,
    existing_bytes: int = 0,
) -> None:
    """Raise ``CAPTURE_BUDGET_EXCEEDED`` when this capture would cross a per-review ceiling."""
    seconds = max(0.0, float(duration_ms) / 1000.0) + max(0.0, float(existing_seconds))
    if seconds > budget.max_seconds:
        raise _budget_error("seconds", seconds, budget.max_seconds)
    artifacts = max(0, int(artifact_count)) + max(0, int(existing_artifacts))
    if artifacts > budget.max_artifacts:
        raise _budget_error("artifacts", artifacts, budget.max_artifacts)
    total_bytes = max(0, int(byte_count)) + max(0, int(existing_bytes))
    if total_bytes > budget.max_bytes:
        raise _budget_error("bytes", total_bytes, budget.max_bytes)


def resolve_mode_settings(
    mode: CaptureMode,
    fps: float | None,
    start_game_ms: int,
    end_game_ms: int,
) -> ModeSettings:
    """Return codec/fps/kind for ``mode``. Assumes the interval already validated."""
    duration_s = max(0.0, (int(end_game_ms) - int(start_game_ms)) / 1000.0)
    if mode is CaptureMode.CLIP:
        clip_fps = DEFAULT_CLIP_FPS if fps is None else float(fps)
        clip_fps = min(max(clip_fps, 0.01), MAX_CAPTURE_FPS)
        return ModeSettings(
            codec=CODEC_WEBM,
            fps=clip_fps,
            kind=ARTIFACT_KIND_CLIP,
            expected_artifacts=1,
        )
    sampled_default = DEFAULT_SAMPLED_FPS if fps is None else float(fps)
    requested = min(max(sampled_default, 0.01), MAX_CAPTURE_FPS)
    if mode is CaptureMode.STILL:
        still_fps = requested
        if duration_s > 0:
            still_fps = min(requested, STILL_MAX_ARTIFACTS / duration_s)
        frames = _expected_frames(duration_s, still_fps, STILL_MAX_ARTIFACTS)
        return ModeSettings(
            codec=CODEC_PNG,
            fps=max(still_fps, 0.01),
            kind=ARTIFACT_KIND_IMAGE,
            expected_artifacts=frames,
        )
    return ModeSettings(
        codec=CODEC_PNG,
        fps=requested,
        kind=ARTIFACT_KIND_IMAGE,
        expected_artifacts=_expected_frames(duration_s, requested, None),
    )


def frame_game_times(
    *,
    start_game_ms: int,
    end_game_ms: int,
    count: int,
) -> tuple[int, ...]:
    """Spread ``count`` frame timestamps across the interval. Single frames land on start."""
    if count <= 0:
        return ()
    start = int(start_game_ms)
    end = int(end_game_ms)
    if count == 1:
        return (start,)
    step = (end - start) / float(count - 1)
    return tuple(int(round(start + step * index)) for index in range(count))


def artifact_filename(*, frame_index: int, game_t_ms: int, suffix: str) -> str:
    """Return the canonical ``frame_{index}_g{game_t_ms}{suffix}`` artifact name."""
    return f"frame_{frame_index:06d}_g{int(game_t_ms)}{suffix}"


def _expected_frames(duration_s: float, fps: float, cap: int | None) -> int:
    raw = 1 if duration_s <= 0 else int(math.floor(duration_s * fps)) + 1
    frames = max(1, raw)
    if cap is not None:
        frames = min(frames, cap)
    return frames


def _budget_error(dimension: str, requested: float, limit: float) -> ReplayError:
    return ReplayError(
        ReplayErrorCode.CAPTURE_BUDGET_EXCEEDED,
        details={"dimension": dimension, "requested": requested, "limit": limit},
    )


def _opt_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)
