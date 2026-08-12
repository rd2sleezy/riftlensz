"""Research-only exact finding-window capture planning.

Does not call CaptureService. Does not auto-capture production findings.
Replay paths are never hardcoded here — the caller supplies ``source_id``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from riftlens.domain.capture import CaptureMode, CaptureRequest, RetentionClass, validate_interval
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.visual.errors import CaptureNotRequested, CaptureWindowError

DEFAULT_PAD_BEFORE_MS = 12_000
DEFAULT_PAD_AFTER_MS = 15_000
# Selection preference only — never treated as ground truth for Kaisa's fight.
PREFERRED_R012_NEAR_MS = 1_340_000
CAPTURE_NOT_REQUESTED = "CAPTURE_NOT_REQUESTED"


@dataclass(frozen=True)
class FindingStamp:
    """A persisted finding's identity and GAME timestamp. Not a coaching rewrite."""

    finding_id: str
    rule_id: str
    t_ms: int
    match_id: str
    review_id: str | None = None
    t_end_ms: int | None = None
    participant_id: int | None = None
    title: str | None = None


@dataclass(frozen=True)
class PlannedCapture:
    """Explicit R.10 capture ask derived from a finding timestamp."""

    match_id: str
    finding_t_ms: int
    start_game_ms: int
    end_game_ms: int
    pad_before_ms: int
    pad_after_ms: int
    rule_id: str
    finding_id: str | None = None
    review_id: str | None = None
    participant_id: int | None = None
    source_id: str | None = None
    clock_map_id: str | None = None
    clipped_start: bool = False
    clipped_end: bool = False
    auto_capture: bool = False

    @property
    def duration_ms(self) -> int:
        return int(self.end_game_ms) - int(self.start_game_ms)


@dataclass(frozen=True)
class TypedCaptureOutcome:
    """Typed success/failure for a research capture ask. Never swallowed."""

    ok: bool
    code: str | None = None
    message: str = ""
    details: Mapping[str, Any] | None = None
    capture_id: str | None = None
    media_artifact_id: str | None = None
    clock_map_id: str | None = None
    source_id: str | None = None
    start_game_ms: int | None = None
    end_game_ms: int | None = None
    start_source_ms: int | None = None
    end_source_ms: int | None = None


def select_finding(
    findings: Sequence[FindingStamp],
    *,
    rule_id: str = "R-012",
    match_id: str | None = None,
    prefer_t_ms: int | None = PREFERRED_R012_NEAR_MS,
) -> FindingStamp:
    """Return the preferred finding. Does not invent a timestamp if none match."""
    matched = [
        item
        for item in findings
        if item.rule_id == rule_id and (match_id is None or item.match_id == match_id)
    ]
    if not matched:
        raise CaptureWindowError(f"no {rule_id} finding available")
    if prefer_t_ms is None:
        return matched[0]
    return min(matched, key=lambda item: (abs(item.t_ms - prefer_t_ms), item.t_ms))


def clip_game_bounds(
    start_game_ms: int,
    end_game_ms: int,
    *,
    match_start_ms: int = 0,
    match_duration_ms: int | None = None,
) -> tuple[int, int, bool, bool]:
    """Clip a GAME interval to match bounds. ``match_duration_ms`` is exclusive-end length."""
    start = int(start_game_ms)
    end = int(end_game_ms)
    clipped_start = False
    clipped_end = False
    floor = max(0, int(match_start_ms))
    if start < floor:
        start = floor
        clipped_start = True
    if match_duration_ms is not None:
        ceiling = max(floor, int(match_duration_ms))
        if end > ceiling:
            end = ceiling
            clipped_end = True
    if end <= start:
        raise CaptureWindowError("capture window is empty after clipping to match bounds")
    return start, end, clipped_start, clipped_end


def capture_window_for_finding(
    finding: FindingStamp,
    *,
    pad_before_ms: int = DEFAULT_PAD_BEFORE_MS,
    pad_after_ms: int = DEFAULT_PAD_AFTER_MS,
    match_start_ms: int = 0,
    match_duration_ms: int | None = None,
    source_id: str | None = None,
    clock_map_id: str | None = None,
) -> PlannedCapture:
    """Pad the finding timestamp into an explicit ~20–30 s GAME window."""
    if pad_before_ms < 0 or pad_after_ms < 0:
        raise CaptureWindowError("pads must be >= 0")
    raw_start = int(finding.t_ms) - int(pad_before_ms)
    raw_end = int(finding.t_ms) + int(pad_after_ms)
    start, end, clipped_start, clipped_end = clip_game_bounds(
        raw_start,
        raw_end,
        match_start_ms=match_start_ms,
        match_duration_ms=match_duration_ms,
    )
    return PlannedCapture(
        match_id=finding.match_id,
        finding_t_ms=finding.t_ms,
        start_game_ms=start,
        end_game_ms=end,
        pad_before_ms=pad_before_ms,
        pad_after_ms=pad_after_ms,
        rule_id=finding.rule_id,
        finding_id=finding.finding_id,
        review_id=finding.review_id,
        participant_id=finding.participant_id,
        source_id=source_id,
        clock_map_id=clock_map_id,
        clipped_start=clipped_start,
        clipped_end=clipped_end,
        auto_capture=False,
    )


def capture_request_for_window(
    plan: PlannedCapture,
    *,
    source_id: str | None = None,
) -> CaptureRequest:
    """Build an R.10 CLIP request. Caller must supply gameplay source id."""
    resolved = source_id or plan.source_id
    if not resolved:
        raise CaptureWindowError("gameplay source id is required to request a capture")
    validate_interval(plan.start_game_ms, plan.end_game_ms)
    return CaptureRequest(
        source_id=resolved,
        start_game_ms=plan.start_game_ms,
        end_game_ms=plan.end_game_ms,
        mode=CaptureMode.CLIP,
        retention=RetentionClass.EPHEMERAL,
        review_id=plan.review_id,
    )


def refuse_automatic_capture(plan: PlannedCapture) -> TypedCaptureOutcome:
    """V.1 does not capture every finding. Explicit research action only."""
    if plan.auto_capture:
        raise CaptureWindowError("V.1 planned captures must not set auto_capture")
    return TypedCaptureOutcome(
        ok=False,
        code=CAPTURE_NOT_REQUESTED,
        message="exact finding-window capture is an explicit research action",
        details={
            "match_id": plan.match_id,
            "finding_id": plan.finding_id,
            "start_game_ms": plan.start_game_ms,
            "end_game_ms": plan.end_game_ms,
        },
        clock_map_id=plan.clock_map_id,
        source_id=plan.source_id,
        start_game_ms=plan.start_game_ms,
        end_game_ms=plan.end_game_ms,
    )


def typed_from_replay_error(error: ReplayError) -> TypedCaptureOutcome:
    """Preserve R.10 typed capture failures without inventing a success."""
    code = error.code.value if isinstance(error.code, ReplayErrorCode) else str(error.code)
    return TypedCaptureOutcome(
        ok=False,
        code=code,
        message=str(error),
        details=dict(error.details) if error.details else None,
    )


def capture_covers_window(
    *,
    capture_start_game_ms: int,
    capture_end_game_ms: int,
    window_start_game_ms: int,
    window_end_game_ms: int,
    slack_ms: int = 2_000,
) -> bool:
    """True when an existing capture already covers the planned GAME window."""
    return (
        int(capture_start_game_ms) <= int(window_start_game_ms) + int(slack_ms)
        and int(capture_end_game_ms) >= int(window_end_game_ms) - int(slack_ms)
    )


def require_explicit_capture(enabled: bool, plan: PlannedCapture) -> None:
    """Raise when a caller tries to capture without an explicit research flag."""
    if enabled:
        return
    outcome = refuse_automatic_capture(plan)
    raise CaptureNotRequested(outcome.message)
