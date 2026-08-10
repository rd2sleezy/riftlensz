from __future__ import annotations

import json
import ssl
import time
from collections.abc import Mapping
from typing import Any

import httpx

from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.api.tls import (
    DEFAULT_REPLAY_API_ORIGIN,
    assert_loopback_origin,
    replay_api_ssl_context,
)

MAX_BODY_BYTES = 2 * 1024 * 1024
_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})
_DEFAULT_MAX_RETRIES = 2
_BACKOFF_S = (0.05, 0.15)


class LoopbackHttpsClient:
    """HTTPS client for 127.0.0.1 only. Retries transient connect/5xx; never retries TLS or 4xx."""

    def __init__(
        self,
        origin: str = DEFAULT_REPLAY_API_ORIGIN,
        *,
        ca_file: str | None = None,
        timeout_s: float = 5.0,
        connect_timeout_s: float = 2.0,
        max_retries: int = _DEFAULT_MAX_RETRIES,
    ) -> None:
        assert_loopback_origin(origin)
        self.origin = origin.rstrip("/")
        self._ca_file = ca_file
        self._timeout = httpx.Timeout(timeout_s, connect=min(connect_timeout_s, timeout_s))
        self._max_retries = max(0, max_retries)
        self._ctx = replay_api_ssl_context(ca_file)

    def request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        retry_transient: bool = True,
    ) -> Any:
        """Return parsed JSON. Raises typed ``ReplayError`` on transport or decode failure."""
        url = f"{self.origin}{path if path.startswith('/') else '/' + path}"
        attempts = self._max_retries + 1 if retry_transient else 1
        last_error: ReplayError | None = None
        for attempt in range(attempts):
            try:
                return self._once(method, url, json_body)
            except ReplayError as exc:
                last_error = exc
                if not retry_transient or not _is_transient(exc) or attempt + 1 >= attempts:
                    raise
                time.sleep(_BACKOFF_S[min(attempt, len(_BACKOFF_S) - 1)])
        raise last_error or ReplayError(ReplayErrorCode.REPLAY_API_UNAVAILABLE)

    def _once(self, method: str, url: str, json_body: Mapping[str, Any] | None) -> Any:
        """Issue one HTTP call. Assumes origin/TLS were already validated."""
        try:
            with httpx.Client(
                verify=self._ctx, timeout=self._timeout, trust_env=False
            ) as client:
                response = client.request(
                    method,
                    url,
                    json=dict(json_body) if json_body is not None else None,
                    headers={"Accept": "application/json"},
                )
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
        if len(response.content) > MAX_BODY_BYTES:
            raise ReplayError(
                ReplayErrorCode.REPLAY_API_UNAVAILABLE,
                details={"reason": "body_too_large", "bytes": len(response.content), "url": url},
            )
        if response.status_code >= 400:
            raise ReplayError(
                ReplayErrorCode.REPLAY_API_UNAVAILABLE,
                details={
                    "reason": "http_status",
                    "status": response.status_code,
                    "url": url,
                    "body_preview": response.text[:200],
                },
            )
        if not response.content:
            return None
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise ReplayError(
                ReplayErrorCode.REPLAY_API_UNAVAILABLE,
                details={"reason": "malformed_json", "url": url},
            ) from exc


def _is_transient(error: ReplayError) -> bool:
    """Return True for connect-refused / 5xx only. TLS and 4xx are not retried."""
    if error.code is ReplayErrorCode.REPLAY_API_TLS:
        return False
    reason = error.details.get("reason")
    if reason == "connect_failed":
        return True
    if reason == "http_status":
        status = error.details.get("status")
        return isinstance(status, int) and status in _RETRYABLE_STATUS
    return False


def _classify_connect_error(exc: httpx.ConnectError, url: str) -> ReplayError:
    """Map certificate pin failures to TLS; handshake resets stay transient."""
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, ssl.SSLCertVerificationError):
            return ReplayError(
                ReplayErrorCode.REPLAY_API_TLS,
                details={"reason": "tls_verify_failed", "error": type(cause).__name__, "url": url},
            )
        if isinstance(cause, ssl.SSLError):
            text = str(cause).lower()
            if "certificate" in text or "verify" in text:
                return ReplayError(
                    ReplayErrorCode.REPLAY_API_TLS,
                    details={
                        "reason": "tls_verify_failed",
                        "error": type(cause).__name__,
                        "url": url,
                    },
                )
            return ReplayError(
                ReplayErrorCode.REPLAY_API_UNAVAILABLE,
                details={"reason": "connect_failed", "error": type(cause).__name__, "url": url},
            )
        cause = cause.__cause__ or cause.__context__
    text = str(exc).lower()
    if "certificate" in text and ("verify" in text or "ssl" in text):
        return ReplayError(
            ReplayErrorCode.REPLAY_API_TLS,
            details={"reason": "tls_verify_failed", "url": url},
        )
    return ReplayError(
        ReplayErrorCode.REPLAY_API_UNAVAILABLE,
        details={"reason": "connect_failed", "error": type(exc).__name__, "url": url},
    )
