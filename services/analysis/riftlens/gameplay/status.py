"""Gameplay UI status composition. Capabilities and session — never source_type."""

from __future__ import annotations

from typing import Any

from riftlens.domain.gameplay_source import SourceCapability
from riftlens.domain.ports import GameplaySourceSnapshot
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode, replay_error_message
from riftlens.gameplay.factory import GameplaySourceFactory
from riftlens.gameplay.outcomes import ResolvedSource
from riftlens.replay_host.port import EnvironmentCheck
from riftlens.replay_host.session import ReplaySessionSnapshot

_DEFAULT_ACTION: dict[ReplayErrorCode, str] = {
    ReplayErrorCode.ROFL_MISSING: "choose_file",
    ReplayErrorCode.ROFL_UNREADABLE: "choose_file",
    ReplayErrorCode.ROFL_INVALID: "choose_file",
    ReplayErrorCode.ROFL_NOT_RECOGNISED: "choose_file",
    ReplayErrorCode.ROFL_METADATA_UNPARSED: "continue_without_replay",
    ReplayErrorCode.MATCH_ID_UNRESOLVED: "choose_file",
    ReplayErrorCode.MATCH_NOT_INGESTED: "ingest_match",
    ReplayErrorCode.MATCH_IDENTITY_MISMATCH: "open_replay_match",
    ReplayErrorCode.RIOT_CREDENTIAL_MISSING: "sign_in_api_key",
    ReplayErrorCode.PARTICIPANT_REQUIRED: "choose_participant",
    ReplayErrorCode.INSTALL_NOT_FOUND: "find_league_install",
    ReplayErrorCode.INSTALL_INVALID: "find_league_install",
    ReplayErrorCode.PATCH_INCOMPATIBLE: "try_anyway",
    ReplayErrorCode.REPLAY_API_DISABLED: "enable_replay_api",
    ReplayErrorCode.LIVE_GAME_IN_PROGRESS: "retry_after_live_game",
    ReplayErrorCode.LAUNCH_FAILED: "retry",
    ReplayErrorCode.LAUNCH_REJECTED: "retry",
    ReplayErrorCode.LAUNCH_TIMEOUT: "retry",
    ReplayErrorCode.PLAYBACK_NOT_STARTED: "retry",
    ReplayErrorCode.PLAYBACK_NOT_ADVANCING: "retry",
    ReplayErrorCode.REPLAY_API_UNAVAILABLE: "retry",
    ReplayErrorCode.REPLAY_API_TLS: "retry",
    ReplayErrorCode.PLAYBACK_UNREADABLE: "retry",
    ReplayErrorCode.PAUSE_FAILED: "retry",
    ReplayErrorCode.RESUME_FAILED: "retry",
    ReplayErrorCode.SEEK_FAILED: "retry",
    ReplayErrorCode.SEEK_OUT_OF_BOUNDS: "continue_without_replay",
    ReplayErrorCode.SEEK_TOLERANCE_EXCEEDED: "retry",
    ReplayErrorCode.CAPABILITY_UNSUPPORTED: "attach_video",
    ReplayErrorCode.CLOCK_UNMAPPED: "attach_video",
    ReplayErrorCode.CLOCK_OUT_OF_BOUNDS: "continue_without_replay",
    ReplayErrorCode.CLOCK_CALIBRATION_FAILED: "continue_without_replay",
    ReplayErrorCode.LIVE_CLIENT_DATA_UNAVAILABLE: "continue_without_replay",
    ReplayErrorCode.ACTIVE_PLAYER_UNAVAILABLE: "continue_without_replay",
    ReplayErrorCode.PLATFORM_UNSUPPORTED: "attach_video",
    ReplayErrorCode.SOURCE_NOT_READY: "open_replay",
    ReplayErrorCode.SESSION_LOST: "reopen_replay",
    ReplayErrorCode.CAPTURE_INVALID_INTERVAL: "adjust_capture_interval",
    ReplayErrorCode.CAPTURE_BUDGET_EXCEEDED: "free_capture_budget",
    ReplayErrorCode.CAPTURE_IN_PROGRESS: "wait_for_capture",
    ReplayErrorCode.CAPTURE_CANCELLED: "retry",
    ReplayErrorCode.CAPTURE_TIMEOUT: "retry",
    ReplayErrorCode.CAPTURE_OUTPUT_MISSING: "retry",
    ReplayErrorCode.CAPTURE_OUTPUT_EMPTY: "retry",
    ReplayErrorCode.CAPTURE_TRUNCATED: "retry",
    ReplayErrorCode.CAPTURE_RECORDING_FAILED: "retry",
    ReplayErrorCode.CAPTURE_DISK_FAILED: "free_disk_space",
}


def suggested_action_for(code: ReplayErrorCode, details: dict[str, object] | None = None) -> str:
    """Return a stable action id. Prefers ``details['suggested_action']`` when present."""
    if details is not None:
        raw = details.get("suggested_action")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return _DEFAULT_ACTION[code]


def serialize_replay_error(error: ReplayError | None) -> dict[str, Any] | None:
    """JSON-ready typed error. Never dumps exception class names as the user message."""
    if error is None:
        return None
    message = str(error).strip() or replay_error_message(error.code)
    return {
        "code": error.code.value,
        "message": message,
        "suggested_action": suggested_action_for(error.code, error.details),
        "recoverable": error.is_retryable() or error.is_informational(),
        "severity": error.severity,
        "details": dict(error.details) if error.details else {},
    }


def serialize_environment(check: EnvironmentCheck) -> dict[str, Any]:
    """Return install/Replay-API probe fields. Does not imply a live session."""
    return {
        "native_replay_supported": check.supported,
        "install_found": check.install_found,
        "replay_api_documented": check.replay_api_documented,
        "live_game": check.live_game,
        "error": serialize_replay_error(check.error),
        "warnings": [serialize_replay_error(item) for item in check.warnings],
    }


def is_native_shaped(resolved: ResolvedSource) -> bool:
    """True when capabilities (or empty+unavailable) describe native replay, not H.9 video."""
    caps = resolved.source.capabilities
    if SourceCapability.LIVE_CLIENT_DATA in caps:
        return True
    return not caps


def pick_source(
    snapshots: list[GameplaySourceSnapshot],
    factory: GameplaySourceFactory,
    source_id: str | None,
) -> tuple[GameplaySourceSnapshot | None, ResolvedSource | None]:
    """Choose the active source. Explicit id wins; otherwise native-shaped, then first."""
    resolved_by_id: dict[str, ResolvedSource] = {
        snap.source.id: factory.resolve(snap) for snap in snapshots
    }
    if source_id is not None:
        for snap in snapshots:
            if snap.source.id == source_id:
                return snap, resolved_by_id[source_id]
        return None, None
    natives = [snap for snap in snapshots if is_native_shaped(resolved_by_id[snap.source.id])]
    if natives:
        chosen = natives[0]
        return chosen, resolved_by_id[chosen.source.id]
    if not snapshots:
        return None, None
    chosen = snapshots[0]
    return chosen, resolved_by_id[chosen.source.id]


def compose_gameplay_status(
    *,
    match_id: str,
    native_supported: bool,
    snapshots: list[GameplaySourceSnapshot],
    chosen: GameplaySourceSnapshot | None,
    resolved: ResolvedSource | None,
    session: ReplaySessionSnapshot,
    factory: GameplaySourceFactory,
) -> dict[str, Any]:
    """Build the R.9 status payload. Omits ``source_type`` so UI cannot branch on it."""
    summaries = [
        _source_summary(snap, factory.resolve(snap)) for snap in snapshots
    ]
    caps = [] if resolved is None else sorted(item.value for item in resolved.source.capabilities)
    clock = None if chosen is None or chosen.clock is None else chosen.clock
    session_error = session.error
    resolve_error = None if resolved is None else resolved.reason
    error = session_error or resolve_error
    warnings: list[dict[str, Any]] = []
    if (
        session_error is not None
        and resolve_error is not None
        and resolve_error.code is not session_error.code
    ):
        serialized = serialize_replay_error(resolve_error)
        if serialized is not None:
            warnings.append(serialized)
    playback = None
    if session.playback is not None:
        playback = {
            "t_source_ms": session.playback.t_source_ms,
            "length_ms": session.playback.length_ms,
            "paused": session.playback.paused,
            "seeking": session.playback.seeking,
            "speed_milli": session.playback.speed_milli,
            "t_game_ms": session.playback.t_game_ms,
        }
    return {
        "native_replay_supported": native_supported,
        "match_id": match_id,
        "sources": summaries,
        "active_source_id": None if chosen is None else chosen.source.id,
        "capabilities": caps,
        "source_status": None if chosen is None else chosen.source.status,
        "file_present": False if chosen is None else chosen.file_present,
        "display_name": None if chosen is None else chosen.source.display_name,
        "declared_patch": None
        if chosen is None or chosen.rofl is None
        else chosen.rofl.declared_patch,
        "session_phase": session.phase.value,
        "session_reached_ready": session.reached_ready,
        "session_owns_process": session.owns_process,
        "clock_confidence": None
        if clock is None
        else clock.clock.confidence.value,
        "clock_verified": None if clock is None else clock.clock.verified,
        "clock_method": None if clock is None else clock.method,
        "offset_ms": None if clock is None else clock.offset_ms,
        "residual_ms": None if clock is None else clock.residual_ms,
        "anchor_count": None if clock is None else clock.anchor_count,
        "error": serialize_replay_error(error),
        "warnings": warnings,
        "playback": playback,
    }


def _source_summary(snapshot: GameplaySourceSnapshot, resolved: ResolvedSource) -> dict[str, Any]:
    return {
        "id": snapshot.source.id,
        "display_name": snapshot.source.display_name,
        "capabilities": sorted(item.value for item in resolved.source.capabilities),
        "status": snapshot.source.status,
        "file_present": snapshot.file_present,
        "declared_patch": None if snapshot.rofl is None else snapshot.rofl.declared_patch,
        "duration_ms": snapshot.source.duration_ms,
        "available": resolved.available,
        "unavailable_error": serialize_replay_error(resolved.reason),
    }
