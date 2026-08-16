"""Typed H.10 automatic-sync failures. VIDEO path only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class AutoSyncError(Exception):
    """Actionable auto-sync failure. ``code`` is stable for API/UI mapping."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready failure payload. Does not include a SyncMap."""
        payload: dict[str, Any] = {"ok": False, "code": self.code, "message": self.message}
        payload.update(self.details)
        return payload


class InsufficientReadings(AutoSyncError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("INSUFFICIENT_READINGS", message, details=details)


class NoStableModel(AutoSyncError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("NO_STABLE_MODEL", message, details=details)


class MultipleGamesDetected(AutoSyncError):
    """One video contains incompatible League game timelines."""

    def __init__(
        self,
        message: str,
        *,
        boundaries_video_ms: Sequence[int],
        details: Mapping[str, Any] | None = None,
    ) -> None:
        merged = dict(details or {})
        merged["boundaries_video_ms"] = [int(item) for item in boundaries_video_ms]
        super().__init__("MULTIPLE_GAMES", message, details=merged)
        self.boundaries_video_ms = tuple(int(item) for item in boundaries_video_ms)


class InconsistentOcrStream(AutoSyncError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("INCONSISTENT_OCR", message, details=details)


class InsufficientCoverage(AutoSyncError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("INSUFFICIENT_COVERAGE", message, details=details)


class VerificationFailed(AutoSyncError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("VERIFICATION_FAILED", message, details=details)


class UnsupportedSource(AutoSyncError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("UNSUPPORTED_SOURCE", message, details=details)


class MediaUnavailable(AutoSyncError):
    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__("MEDIA_UNAVAILABLE", message, details=details)
