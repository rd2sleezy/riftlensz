from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Mapping
from enum import IntEnum
from typing import Literal, Protocol


class Priority(IntEnum):
    INTERACTIVE = 0
    BATCH = 1


class Clock(Protocol):
    def now_ms(self) -> int: ...

    async def sleep_ms(self, ms: int) -> None: ...


class MonotonicClock:
    """Wall-clock wrapper. Assumes the event loop is running for sleep_ms."""

    def now_ms(self) -> int:
        return int(asyncio.get_running_loop().time() * 1000)

    async def sleep_ms(self, ms: int) -> None:
        await asyncio.sleep(max(ms, 0) / 1000.0)


class FakeClock:
    """Deterministic clock for limiter tests. Assumes tests pump advance()/drain()."""

    def __init__(self) -> None:
        self._now = 0
        self._sleepers: list[tuple[int, asyncio.Future[None]]] = []

    def now_ms(self) -> int:
        return self._now

    async def sleep_ms(self, ms: int) -> None:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[None] = loop.create_future()
        self._sleepers.append((self._now + max(ms, 0), fut))
        await fut

    def advance(self, ms: int) -> None:
        self._now += max(ms, 0)
        due = [(t, fut) for t, fut in self._sleepers if t <= self._now]
        self._sleepers = [(t, fut) for t, fut in self._sleepers if t > self._now]
        for _t, fut in due:
            if not fut.done():
                fut.set_result(None)

    async def pump_until(self, done: Callable[[], bool], max_steps: int = 50_000) -> None:
        """Advance time until done() is true. Assumes waiters use sleep_ms()."""
        for _ in range(max_steps):
            if done():
                return
            await asyncio.sleep(0)
            if self._sleepers:
                next_wake = min(t for t, _fut in self._sleepers)
                self.advance(max(1, next_wake - self._now))
        raise RuntimeError("FakeClock.pump_until exceeded max_steps")


def parse_rate_pairs(header: str) -> list[tuple[int, int]]:
    """Parse 'N:W,M:V' into (count_or_limit, window_seconds) pairs. Assumes Riot format."""
    pairs: list[tuple[int, int]] = []
    if not header.strip():
        return pairs
    for part in header.split(","):
        left, right = part.strip().split(":")
        pairs.append((int(left), int(right)))
    return pairs


class TokenBucket:
    def __init__(
        self,
        capacity: int,
        window_ms: int,
        clock: Clock | None = None,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if window_ms < 1:
            raise ValueError("window_ms must be >= 1")
        self.capacity = capacity
        self.window_ms = window_ms
        self._clock: Clock = clock or MonotonicClock()
        self._stamps: deque[int] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Take one token, waiting until the sliding window has room. Assumes running loop."""
        while True:
            async with self._lock:
                now = self._clock.now_ms()
                self._evict(now)
                if len(self._stamps) < self.capacity:
                    self._stamps.append(now)
                    return
                wait_ms = self._stamps[0] + self.window_ms - now
            await self._clock.sleep_ms(max(wait_ms, 1))

    def observe_headers(self, limit_header: str, count_header: str) -> None:
        """Reconcile local state with Riot's X-*-Rate-Limit / -Count headers.

        Header format is 'N:W,M:V' meaning N requests per W seconds, etc.
        Assumes this bucket corresponds to one of those windows.
        """
        limits = parse_rate_pairs(limit_header)
        counts = {window_s: count for count, window_s in parse_rate_pairs(count_header)}
        window_s = max(1, self.window_ms // 1000)
        matched: tuple[int, int] | None = None
        for limit_n, limit_w in limits:
            if limit_w == window_s:
                matched = (limit_n, limit_w)
                break
        if matched is None and len(limits) == 1:
            matched = limits[0]
        if matched is None:
            return
        limit_n, limit_w = matched
        self.capacity = max(1, limit_n)
        self.window_ms = max(1, limit_w * 1000)
        riot_count = min(self.capacity, max(0, counts.get(limit_w, len(self._stamps))))
        now = self._clock.now_ms()
        self._evict(now)
        while len(self._stamps) > riot_count:
            self._stamps.popleft()
        while len(self._stamps) < riot_count:
            self._stamps.append(now)

    def _evict(self, now_ms: int) -> None:
        cutoff = now_ms - self.window_ms
        while self._stamps and self._stamps[0] <= cutoff:
            self._stamps.popleft()


class RiotRateLimiter:
    """App-level buckets + per-method buckets + priority queue."""

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock: Clock = clock or MonotonicClock()
        self._app_buckets: list[TokenBucket] = [
            TokenBucket(20, 1_000, self._clock),
            TokenBucket(100, 120_000, self._clock),
        ]
        self._app_limits_seen = False
        self._method_buckets: dict[str, list[TokenBucket]] = {}
        self._seq = 0
        self._queue: asyncio.PriorityQueue[
            tuple[int, int, str, asyncio.Future[None]]
        ] = asyncio.PriorityQueue()
        self._dispatcher_started = False
        self._penalty_until: dict[str, int] = {}
        self._dispatch_task: asyncio.Task[None] | None = None

    async def acquire(self, method_key: str, priority: Priority) -> None:
        """Wait until this request may proceed. Assumes a running event loop."""
        self._ensure_dispatcher()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[None] = loop.create_future()
        self._seq += 1
        await self._queue.put((int(priority), self._seq, method_key, fut))
        await fut

    def update_from_response(self, method_key: str, headers: Mapping[str, str]) -> None:
        """Overwrite seeded buckets from Riot rate-limit headers.

        Assumes header names vary by case.
        """
        normalized = {k.lower(): v for k, v in headers.items()}
        app_limit = normalized.get("x-app-rate-limit", "")
        app_count = normalized.get("x-app-rate-limit-count", "")
        method_limit = normalized.get("x-method-rate-limit", "")
        method_count = normalized.get("x-method-rate-limit-count", "")
        if app_limit:
            if not self._app_limits_seen:
                self._app_buckets = [
                    TokenBucket(limit_n, window_s * 1000, self._clock)
                    for limit_n, window_s in parse_rate_pairs(app_limit)
                ]
                self._app_limits_seen = True
            for bucket in self._app_buckets:
                bucket.observe_headers(app_limit, app_count)
        if method_limit:
            if method_key not in self._method_buckets:
                self._method_buckets[method_key] = [
                    TokenBucket(limit_n, window_s * 1000, self._clock)
                    for limit_n, window_s in parse_rate_pairs(method_limit)
                ]
            for bucket in self._method_buckets[method_key]:
                bucket.observe_headers(method_limit, method_count)

    async def penalize(
        self,
        retry_after_s: float,
        scope: Literal["app", "method"],
        method_key: str,
    ) -> None:
        """Block app or method scope until Retry-After elapses. Assumes retry_after_s >= 0."""
        until = self._clock.now_ms() + int(retry_after_s * 1000)
        key = "app" if scope == "app" else f"method:{method_key}"
        self._penalty_until[key] = max(self._penalty_until.get(key, 0), until)
        wait_ms = max(0, until - self._clock.now_ms())
        if wait_ms:
            await self._clock.sleep_ms(wait_ms)

    def _ensure_dispatcher(self) -> None:
        if self._dispatcher_started:
            return
        self._dispatcher_started = True
        self._dispatch_task = asyncio.create_task(self._dispatch())

    async def _dispatch(self) -> None:
        while True:
            _prio, _seq, method_key, fut = await self._queue.get()
            try:
                await self._wait_penalties(method_key)
                for bucket in self._app_buckets:
                    await bucket.acquire()
                for bucket in self._method_buckets.get(method_key, []):
                    await bucket.acquire()
                if not fut.done():
                    fut.set_result(None)
            except Exception as exc:
                if not fut.done():
                    fut.set_exception(exc)

    async def _wait_penalties(self, method_key: str) -> None:
        while True:
            now = self._clock.now_ms()
            deadlines = [
                self._penalty_until.get("app", 0),
                self._penalty_until.get(f"method:{method_key}", 0),
            ]
            remaining = max(deadlines) - now
            if remaining <= 0:
                return
            await self._clock.sleep_ms(remaining)
