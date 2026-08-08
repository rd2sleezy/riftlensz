from __future__ import annotations


class RiotError(Exception):
    """Base Riot API failure. Assumes the caller already redacts secrets."""


class RateLimited(RiotError):
    """HTTP 429. Assumes Retry-After was parsed by the client when available."""

    def __init__(self, retry_after_s: float, scope: str) -> None:
        self.retry_after_s = retry_after_s
        self.scope = scope
        super().__init__(f"rate limited ({scope}) retry_after_s={retry_after_s}")


class NotFound(RiotError):
    """HTTP 404. Assumes the resource does not exist at this routing value."""


class Forbidden(RiotError):
    """HTTP 403. Assumes the key is missing, wrong, or expired."""


class ServerError(RiotError):
    """HTTP 5xx. Assumes the caller may retry with backoff."""

    def __init__(self, status_code: int, message: str = "") -> None:
        self.status_code = status_code
        super().__init__(message or f"riot server error HTTP {status_code}")
