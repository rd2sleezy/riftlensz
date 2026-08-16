from __future__ import annotations

import queue
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from riftlens.orchestration.job import TERMINAL_STATUSES


@dataclass(frozen=True)
class ProgressEvent:
    job_id: str
    stage: str
    pct: int
    message: str
    ts: int
    status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the SSE JSON body."""
        return {
            "job_id": self.job_id,
            "stage": self.stage,
            "pct": self.pct,
            "message": self.message,
            "ts": self.ts,
            "status": self.status,
        }

    @property
    def terminal(self) -> bool:
        """Return True when this event closes the stream."""
        return self.status in TERMINAL_STATUSES


class ProgressBus:
    """Thread-safe fan-out of progress events. Disconnected subscribers do not affect jobs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._history: dict[str, list[ProgressEvent]] = {}
        self._subs: dict[str, list[queue.Queue[ProgressEvent | None]]] = {}

    def emit(self, event: ProgressEvent) -> None:
        """Record and fan-out ``event``. Assumes ``pct`` is already clamped 0..100."""
        with self._lock:
            self._history.setdefault(event.job_id, []).append(event)
            targets = list(self._subs.get(event.job_id, ()))
        for bucket in targets:
            try:
                bucket.put_nowait(event)
            except queue.Full:
                continue

    def snapshot(self, job_id: str) -> list[ProgressEvent]:
        """Return recorded events for reconnect. Assumes the job may be unknown."""
        with self._lock:
            return list(self._history.get(job_id, ()))

    def subscribe(self, job_id: str) -> queue.Queue[ProgressEvent | None]:
        """Return a queue preloaded with history. Caller must ``unsubscribe``."""
        bucket: queue.Queue[ProgressEvent | None] = queue.Queue(maxsize=256)
        with self._lock:
            for event in self._history.get(job_id, ()):
                try:
                    bucket.put_nowait(event)
                except queue.Full:
                    break
            self._subs.setdefault(job_id, []).append(bucket)
        return bucket

    def unsubscribe(self, job_id: str, bucket: queue.Queue[ProgressEvent | None]) -> None:
        """Drop a subscriber. Assumes the queue was created by ``subscribe``."""
        with self._lock:
            items = self._subs.get(job_id, [])
            self._subs[job_id] = [item for item in items if item is not bucket]

    def iter_sse(self, job_id: str, *, poll_s: float = 0.25) -> Iterator[ProgressEvent]:
        """Yield events until a terminal status. Blocking; run on a worker thread."""
        bucket = self.subscribe(job_id)
        try:
            while True:
                try:
                    event = bucket.get(timeout=poll_s)
                except queue.Empty:
                    continue
                if event is None:
                    return
                yield event
                if event.terminal:
                    return
        finally:
            self.unsubscribe(job_id, bucket)


def now_ms() -> int:
    """Return unix epoch milliseconds."""
    return int(time.time() * 1000)
