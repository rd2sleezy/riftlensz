"""Injected clocks for launch/seek polling. No Windows or HTTP dependencies."""

from __future__ import annotations

import time
from typing import Protocol


class SleepClock(Protocol):
    """Injected clock so launch polling is deterministic under tests."""

    def monotonic(self) -> float:
        """Return monotonic seconds."""

    def sleep(self, seconds: float) -> None:
        """Block or advance fake time by ``seconds``."""


class WallClock:
    """Production clock wrapping ``time.monotonic`` / ``time.sleep``."""

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
