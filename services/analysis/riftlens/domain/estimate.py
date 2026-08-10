from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import reduce
from operator import mul


@dataclass(frozen=True)
class Estimate[T]:
    value: T
    confidence: float
    lo: T | None = None
    hi: T | None = None
    basis: str = ""

    def is_confident(self, threshold: float) -> bool:
        """Return True when ``confidence >= threshold``. Assumes threshold is in 0..1."""
        return self.confidence >= threshold


def combine(confidences: Sequence[float]) -> float:
    """Return the product of confidences, floored at 0. Do not average.

    Assumes each input is a finite float. An empty sequence yields 1.0, the
    multiplicative identity used by ``reduce(..., 1.0)``.
    """
    return max(0.0, float(reduce(mul, confidences, 1.0)))
