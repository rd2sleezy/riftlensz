from __future__ import annotations

import json
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.api.tls import (
    DEFAULT_REPLAY_API_ORIGIN,
    assert_loopback_origin,
    replay_api_ssl_context,
)
from riftlens.replay_host.api.tls import riot_ca_path as riot_ca_path

OPENAPI_V3_PATH = "/swagger/v3/openapi.json"
SWAGGER_V2_PATH = "/swagger/v2/swagger.json"
REQUIRED_REPLAY_PATH = "/replay/playback"
MAX_SPEC_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class ReplayApiCapability:
    """OpenAPI probe result. Config-file flags are not treated as proof."""

    reachable: bool
    replay_playback_present: bool
    documented_paths: tuple[str, ...]
    spec_path: str | None
    error: ReplayError | None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready mapping. Assumes the probe already finished."""
        error = self.error
        return {
            "reachable": self.reachable,
            "replay_playback_present": self.replay_playback_present,
            "documented_paths": list(self.documented_paths),
            "spec_path": self.spec_path,
            "error": None
            if error is None
            else {"code": error.code.value, "message": str(error), "details": dict(error.details)},
        }


def probe_replay_api_capability(
    *,
    origin: str = DEFAULT_REPLAY_API_ORIGIN,
    ca_file: str | Path | None = None,
    timeout_s: float = 5.0,
) -> ReplayApiCapability:
    """GET OpenAPI and require ``/replay/playback``. Does not call playback itself."""
    try:
        assert_loopback_origin(origin)
        ctx = replay_api_ssl_context(ca_file)
    except ReplayError as exc:
        return ReplayApiCapability(
            reachable=False,
            replay_playback_present=False,
            documented_paths=(),
            spec_path=None,
            error=exc,
        )
    spec_path, document, error = _fetch_spec(origin, ctx, timeout_s)
    if error is not None or document is None:
        return ReplayApiCapability(
            reachable=False,
            replay_playback_present=False,
            documented_paths=(),
            spec_path=spec_path,
            error=error,
        )
    paths = _documented_paths(document)
    present = REQUIRED_REPLAY_PATH in paths or REQUIRED_REPLAY_PATH.lstrip("/") in paths
    if not present:
        return ReplayApiCapability(
            reachable=True,
            replay_playback_present=False,
            documented_paths=paths,
            spec_path=spec_path,
            error=ReplayError(
                ReplayErrorCode.REPLAY_API_DISABLED,
                details={
                    "reason": "replay_paths_missing",
                    "spec_path": spec_path,
                    "suggested_action": "enable_replay_api_and_restart_client",
                },
            ),
        )
    return ReplayApiCapability(
        reachable=True,
        replay_playback_present=True,
        documented_paths=paths,
        spec_path=spec_path,
        error=None,
    )


def _fetch_spec(
    origin: str,
    ctx: ssl.SSLContext,
    timeout_s: float,
) -> tuple[str | None, dict[str, Any] | None, ReplayError | None]:
    """Fetch OpenAPI v3, then Swagger v2. Returns the first JSON object that parses."""
    last_error: ReplayError | None = None
    last_path: str | None = None
    for spec_path in (OPENAPI_V3_PATH, SWAGGER_V2_PATH):
        last_path = spec_path
        try:
            document = _get_json(f"{origin.rstrip('/')}{spec_path}", ctx, timeout_s)
        except ReplayError as exc:
            last_error = exc
            if exc.code is ReplayErrorCode.REPLAY_API_TLS:
                return spec_path, None, exc
            continue
        return spec_path, document, None
    return last_path, None, last_error or ReplayError(ReplayErrorCode.REPLAY_API_UNAVAILABLE)


def _get_json(url: str, ctx: ssl.SSLContext, timeout_s: float) -> dict[str, Any]:
    """GET ``url`` with the pinned context. Maps transport failures to typed errors."""
    try:
        with httpx.Client(verify=ctx, timeout=timeout_s, trust_env=False) as client:
            response = client.get(url, headers={"Accept": "application/json"})
    except httpx.TimeoutException as exc:
        raise ReplayError(
            ReplayErrorCode.REPLAY_API_UNAVAILABLE,
            details={"reason": "timeout", "url": url},
        ) from exc
    except httpx.ConnectError as exc:
        raise _classify_connect_error(exc, url) from exc
    except httpx.HTTPError as exc:
        raise ReplayError(
            ReplayErrorCode.REPLAY_API_UNAVAILABLE,
            details={"reason": "http_error", "error": type(exc).__name__, "url": url},
        ) from exc
    if response.status_code >= 400:
        raise ReplayError(
            ReplayErrorCode.REPLAY_API_UNAVAILABLE,
            details={"reason": "http_status", "status": response.status_code, "url": url},
        )
    if len(response.content) > MAX_SPEC_BYTES:
        raise ReplayError(
            ReplayErrorCode.REPLAY_API_UNAVAILABLE,
            details={"reason": "spec_too_large", "bytes": len(response.content)},
        )
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise ReplayError(
            ReplayErrorCode.REPLAY_API_UNAVAILABLE,
            details={"reason": "malformed_spec", "url": url},
        ) from exc
    if not isinstance(payload, dict):
        raise ReplayError(
            ReplayErrorCode.REPLAY_API_UNAVAILABLE,
            details={"reason": "spec_not_object", "url": url},
        )
    return payload


def _classify_connect_error(exc: httpx.ConnectError, url: str) -> ReplayError:
    """Map TLS verify failures separately from connection refused."""
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, ssl.SSLError):
            return ReplayError(
                ReplayErrorCode.REPLAY_API_TLS,
                details={"reason": "tls_verify_failed", "error": type(cause).__name__, "url": url},
            )
        cause = cause.__cause__ or cause.__context__
    text = str(exc).lower()
    if "certificate" in text or "ssl" in text or "tls" in text:
        return ReplayError(
            ReplayErrorCode.REPLAY_API_TLS,
            details={"reason": "tls_verify_failed", "url": url},
        )
    return ReplayError(
        ReplayErrorCode.REPLAY_API_UNAVAILABLE,
        details={"reason": "connect_failed", "error": type(exc).__name__, "url": url},
    )


def _documented_paths(document: dict[str, Any]) -> tuple[str, ...]:
    """Return OpenAPI/Swagger path keys, normalised with a leading slash."""
    raw = document.get("paths")
    if not isinstance(raw, dict):
        return ()
    paths: list[str] = []
    for key in raw:
        if not isinstance(key, str) or not key:
            continue
        paths.append(key if key.startswith("/") else f"/{key}")
    return tuple(paths)
