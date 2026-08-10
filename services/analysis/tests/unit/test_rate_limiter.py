from __future__ import annotations

import asyncio

import pytest
from riftlens.adapters.riot.rate_limiter import FakeClock, TokenBucket


@pytest.mark.asyncio
async def test_token_bucket_never_exceeds_capacity_in_sliding_window() -> None:
    clock = FakeClock()
    bucket = TokenBucket(capacity=20, window_ms=1000, clock=clock)
    completed: list[int] = []

    async def worker() -> None:
        await bucket.acquire()
        completed.append(clock.now_ms())

    tasks = [asyncio.create_task(worker()) for _ in range(500)]
    await clock.pump_until(lambda: all(task.done() for task in tasks))
    await asyncio.gather(*tasks)
    assert len(completed) == 500
    for start in completed:
        in_window = sum(1 for ts in completed if start <= ts < start + 1000)
        assert in_window <= 20
