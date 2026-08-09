from __future__ import annotations

from pathlib import Path

from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode

PREFIX_MAX_BYTES = 64 * 1024
METADATA_JSON_MAX_BYTES = 32 * 1024
MIN_ROFL_BYTES = 4
MAX_ROFL_BYTES = 2 * 1024 * 1024 * 1024
ROFL_MAGICS: tuple[bytes, ...] = (b"RIOT", b"ROFL")


def resolve_rofl_candidate(path: Path) -> Path:
    """Return a resolved path. Assumes the caller has not yet checked existence."""
    try:
        return path.expanduser().resolve(strict=False)
    except OSError as exc:
        raise ReplayError(
            ReplayErrorCode.ROFL_UNREADABLE,
            details={"reason": "resolve_failed", "error": type(exc).__name__},
        ) from exc


def assert_rofl_size(size_bytes: int) -> None:
    """Raise when ``size_bytes`` is empty or absurd. Assumes size came from ``stat``."""
    if size_bytes <= 0:
        raise ReplayError(
            ReplayErrorCode.ROFL_UNREADABLE,
            details={"reason": "empty", "size_bytes": size_bytes},
        )
    if size_bytes < MIN_ROFL_BYTES:
        raise ReplayError(
            ReplayErrorCode.ROFL_UNREADABLE,
            details={"reason": "too_small", "size_bytes": size_bytes},
        )
    if size_bytes > MAX_ROFL_BYTES:
        raise ReplayError(
            ReplayErrorCode.ROFL_UNREADABLE,
            details={"reason": "too_large", "size_bytes": size_bytes},
        )


def validate_rofl_path(path: Path) -> tuple[Path, int]:
    """Return ``(resolved_path, size_bytes)`` or raise a typed ``ReplayError``."""
    resolved = resolve_rofl_candidate(path)
    if not resolved.exists():
        raise ReplayError(
            ReplayErrorCode.ROFL_MISSING,
            details={"reason": "missing"},
        )
    if not resolved.is_file():
        raise ReplayError(
            ReplayErrorCode.ROFL_UNREADABLE,
            details={"reason": "not_a_file"},
        )
    try:
        size_bytes = resolved.stat().st_size
    except OSError as exc:
        raise ReplayError(
            ReplayErrorCode.ROFL_UNREADABLE,
            details={"reason": "stat_failed", "error": type(exc).__name__},
        ) from exc
    assert_rofl_size(size_bytes)
    return resolved, size_bytes


def read_rofl_prefix(path: Path, *, max_bytes: int = PREFIX_MAX_BYTES) -> bytes:
    """Read at most ``max_bytes`` from the start of ``path``. Never follows offsets."""
    if max_bytes <= 0:
        return b""
    try:
        with path.open("rb") as handle:
            return handle.read(max_bytes)
    except OSError as exc:
        raise ReplayError(
            ReplayErrorCode.ROFL_UNREADABLE,
            details={"reason": "read_failed", "error": type(exc).__name__},
        ) from exc
