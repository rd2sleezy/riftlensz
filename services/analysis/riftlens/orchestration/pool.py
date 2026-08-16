from __future__ import annotations

import asyncio
import multiprocessing
from collections.abc import Callable
from multiprocessing.process import BaseProcess
from typing import Any, TypeVar

from riftlens.orchestration.job import CancellationToken, JobCancelled

T = TypeVar("T")


class CancellablePool:
    """Run CPU work in a spawned process so cancel can terminate it."""

    async def run(
        self,
        fn: Callable[..., T],
        *args: Any,
        cancel: CancellationToken,
        poll_s: float = 0.05,
    ) -> T:
        """Return ``fn(*args)``. Terminates the worker when ``cancel`` is set."""
        ctx = multiprocessing.get_context("spawn")
        result_q: multiprocessing.Queue[tuple[str, object]] = ctx.Queue()
        proc = ctx.Process(target=_worker, args=(fn, args, result_q), daemon=True)
        proc.start()
        try:
            while proc.is_alive():
                cancel.raise_if_set()
                await asyncio.sleep(poll_s)
            if cancel.is_cancelled():
                raise JobCancelled()
            kind, payload = result_q.get_nowait()
            if kind == "err":
                raise payload  # type: ignore[misc]
            return payload  # type: ignore[return-value]
        except JobCancelled:
            _stop(proc)
            raise
        finally:
            if proc.is_alive():
                _stop(proc)
            proc.join(timeout=1.0)


def _worker(
    fn: Callable[..., object],
    args: tuple[object, ...],
    result_q: multiprocessing.Queue[tuple[str, object]],
) -> None:
    try:
        result_q.put(("ok", fn(*args)))
    except Exception as exc:  # noqa: BLE001 — surface worker failures to the parent
        result_q.put(("err", exc))


def _stop(proc: BaseProcess) -> None:
    proc.terminate()
    proc.join(timeout=2.0)
    if proc.is_alive():
        proc.kill()
        proc.join(timeout=1.0)
