from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Literal

ReplayErrorSeverity = Literal["fatal", "retryable", "informational"]


class ReplayErrorCode(StrEnum):
    """Closed taxonomy for native-replay and gameplay-source failures."""

    ROFL_MISSING = "ROFL_MISSING"
    ROFL_UNREADABLE = "ROFL_UNREADABLE"
    ROFL_INVALID = "ROFL_INVALID"
    INSTALL_NOT_FOUND = "INSTALL_NOT_FOUND"
    INSTALL_INVALID = "INSTALL_INVALID"
    PATCH_INCOMPATIBLE = "PATCH_INCOMPATIBLE"
    REPLAY_API_DISABLED = "REPLAY_API_DISABLED"
    LAUNCH_FAILED = "LAUNCH_FAILED"
    PLAYBACK_NOT_STARTED = "PLAYBACK_NOT_STARTED"
    REPLAY_API_UNAVAILABLE = "REPLAY_API_UNAVAILABLE"
    REPLAY_API_TLS = "REPLAY_API_TLS"
    PLAYBACK_UNREADABLE = "PLAYBACK_UNREADABLE"
    PAUSE_FAILED = "PAUSE_FAILED"
    RESUME_FAILED = "RESUME_FAILED"
    SEEK_FAILED = "SEEK_FAILED"
    SEEK_OUT_OF_BOUNDS = "SEEK_OUT_OF_BOUNDS"
    SEEK_TOLERANCE_EXCEEDED = "SEEK_TOLERANCE_EXCEEDED"
    CAPABILITY_UNSUPPORTED = "CAPABILITY_UNSUPPORTED"
    CLOCK_UNMAPPED = "CLOCK_UNMAPPED"
    CLOCK_OUT_OF_BOUNDS = "CLOCK_OUT_OF_BOUNDS"
    LIVE_CLIENT_DATA_UNAVAILABLE = "LIVE_CLIENT_DATA_UNAVAILABLE"
    ACTIVE_PLAYER_UNAVAILABLE = "ACTIVE_PLAYER_UNAVAILABLE"
    PLATFORM_UNSUPPORTED = "PLATFORM_UNSUPPORTED"
    SOURCE_NOT_READY = "SOURCE_NOT_READY"


_DEFAULT_MESSAGE: dict[ReplayErrorCode, str] = {
    ReplayErrorCode.ROFL_MISSING: "Replay file is missing.",
    ReplayErrorCode.ROFL_UNREADABLE: "Replay file exists but could not be read.",
    ReplayErrorCode.ROFL_INVALID: "Replay file is not a valid .rofl.",
    ReplayErrorCode.INSTALL_NOT_FOUND: "League of Legends installation was not found.",
    ReplayErrorCode.INSTALL_INVALID: "League of Legends installation is incomplete.",
    ReplayErrorCode.PATCH_INCOMPATIBLE: "Replay patch does not match the installed client.",
    ReplayErrorCode.REPLAY_API_DISABLED: "Replay API is not enabled in the game client.",
    ReplayErrorCode.LAUNCH_FAILED: "Failed to launch the replay in the game client.",
    ReplayErrorCode.PLAYBACK_NOT_STARTED: "Replay process started but playback has not begun.",
    ReplayErrorCode.REPLAY_API_UNAVAILABLE: "Local Replay API is not reachable.",
    ReplayErrorCode.REPLAY_API_TLS: "Replay API TLS verification failed.",
    ReplayErrorCode.PLAYBACK_UNREADABLE: "Playback time/state could not be read.",
    ReplayErrorCode.PAUSE_FAILED: "Replay pause did not hold game time.",
    ReplayErrorCode.RESUME_FAILED: "Replay resume did not advance game time.",
    ReplayErrorCode.SEEK_FAILED: "Replay seek did not change playback time.",
    ReplayErrorCode.SEEK_OUT_OF_BOUNDS: "Requested seek time is outside the source clock.",
    ReplayErrorCode.SEEK_TOLERANCE_EXCEEDED: "Seek landed outside the allowed tolerance.",
    ReplayErrorCode.CAPABILITY_UNSUPPORTED: "Gameplay source does not expose this capability.",
    ReplayErrorCode.CLOCK_UNMAPPED: "No clock mapping exists for this timestamp.",
    ReplayErrorCode.CLOCK_OUT_OF_BOUNDS: "Timestamp is outside the clock map bounds.",
    ReplayErrorCode.LIVE_CLIENT_DATA_UNAVAILABLE: (
        "Live Client Data is unavailable during this replay (non-fatal)."
    ),
    ReplayErrorCode.ACTIVE_PLAYER_UNAVAILABLE: (
        "activeplayer is unavailable during this replay (non-fatal)."
    ),
    ReplayErrorCode.PLATFORM_UNSUPPORTED: "This gameplay source is not supported on this platform.",
    ReplayErrorCode.SOURCE_NOT_READY: "Gameplay source is not ready.",
}

_SEVERITY: dict[ReplayErrorCode, ReplayErrorSeverity] = {
    ReplayErrorCode.ROFL_MISSING: "fatal",
    ReplayErrorCode.ROFL_UNREADABLE: "fatal",
    ReplayErrorCode.ROFL_INVALID: "fatal",
    ReplayErrorCode.INSTALL_NOT_FOUND: "fatal",
    ReplayErrorCode.INSTALL_INVALID: "fatal",
    ReplayErrorCode.PATCH_INCOMPATIBLE: "fatal",
    ReplayErrorCode.REPLAY_API_DISABLED: "fatal",
    ReplayErrorCode.LAUNCH_FAILED: "fatal",
    ReplayErrorCode.PLAYBACK_NOT_STARTED: "retryable",
    ReplayErrorCode.REPLAY_API_UNAVAILABLE: "retryable",
    ReplayErrorCode.REPLAY_API_TLS: "fatal",
    ReplayErrorCode.PLAYBACK_UNREADABLE: "retryable",
    ReplayErrorCode.PAUSE_FAILED: "fatal",
    ReplayErrorCode.RESUME_FAILED: "fatal",
    ReplayErrorCode.SEEK_FAILED: "fatal",
    ReplayErrorCode.SEEK_OUT_OF_BOUNDS: "fatal",
    ReplayErrorCode.SEEK_TOLERANCE_EXCEEDED: "fatal",
    ReplayErrorCode.CAPABILITY_UNSUPPORTED: "fatal",
    ReplayErrorCode.CLOCK_UNMAPPED: "fatal",
    ReplayErrorCode.CLOCK_OUT_OF_BOUNDS: "fatal",
    ReplayErrorCode.LIVE_CLIENT_DATA_UNAVAILABLE: "informational",
    ReplayErrorCode.ACTIVE_PLAYER_UNAVAILABLE: "informational",
    ReplayErrorCode.PLATFORM_UNSUPPORTED: "fatal",
    ReplayErrorCode.SOURCE_NOT_READY: "retryable",
}


def replay_error_message(code: ReplayErrorCode) -> str:
    """Return the canonical message for ``code``. Assumes ``code`` is a known member."""
    return _DEFAULT_MESSAGE[code]


def replay_error_severity(code: ReplayErrorCode) -> ReplayErrorSeverity:
    """Return fatal/retryable/informational for ``code``. Assumes taxonomy is complete."""
    return _SEVERITY[code]


class ReplayError(Exception):
    """Typed failure for gameplay-source / native-replay operations. No HTTP assumed."""

    def __init__(
        self,
        code: ReplayErrorCode,
        message: str | None = None,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = code
        self.details = dict(details or {})
        super().__init__(message if message is not None else replay_error_message(code))

    @property
    def severity(self) -> ReplayErrorSeverity:
        """Return the taxonomy severity. Assumes ``code`` is a known member."""
        return replay_error_severity(self.code)

    def is_fatal(self) -> bool:
        """Return True when this error should abort a native-replay proof."""
        return self.severity == "fatal"

    def is_retryable(self) -> bool:
        """Return True when a later poll/retry might succeed."""
        return self.severity == "retryable"

    def is_informational(self) -> bool:
        """Return True when the error must not fail Replay API control proof."""
        return self.severity == "informational"
