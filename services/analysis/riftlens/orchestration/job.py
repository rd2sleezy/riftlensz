from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

JOB_QUEUED = "QUEUED"
JOB_RUNNING = "RUNNING"
JOB_COMPLETED = "COMPLETED"
JOB_FAILED = "FAILED"
JOB_CANCELLED = "CANCELLED"

TERMINAL_STATUSES = frozenset({JOB_COMPLETED, JOB_FAILED, JOB_CANCELLED})


class JobCancelled(Exception):
    """Raised when a job's cancellation token is observed."""


class CancellationToken:
    """Thread-safe cooperative cancel flag. Checked between stages and at progress ticks."""

    def __init__(self) -> None:
        self._flag = threading.Event()

    def cancel(self) -> None:
        """Request cancellation. Assumes callers check ``raise_if_set`` cooperatively."""
        self._flag.set()

    def is_cancelled(self) -> bool:
        """Return True when cancellation was requested."""
        return self._flag.is_set()

    def raise_if_set(self) -> None:
        """Raise ``JobCancelled`` when cancellation was requested."""
        if self._flag.is_set():
            raise JobCancelled()


@dataclass(frozen=True)
class JobInputs:
    match_id: str
    participant_id: int
    media_asset_id: str | None = None
    rank: str = "UNRANKED"
    llm_provider: str = "null"
    llm_model: str = ""
    region: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe inputs. Never includes API keys."""
        return {
            "match_id": self.match_id,
            "participant_id": self.participant_id,
            "media_asset_id": self.media_asset_id,
            "rank": self.rank,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "region": self.region,
        }


@dataclass
class StageTiming:
    name: str
    duration_ms: int
    cache_hit: bool
    skipped: bool = False


@dataclass
class AnalysisJob:
    id: str
    inputs: JobInputs
    status: str = JOB_QUEUED
    current_stage: str | None = None
    progress_pct: int = 0
    progress_message: str = ""
    created_at: int = 0
    started_at: int | None = None
    completed_at: int | None = None
    failure_stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    review_id: str | None = None
    stage_timings: list[StageTiming] = field(default_factory=list)
    cache_hits: int = 0
    cache_misses: int = 0
    fact_count: int | None = None
    finding_count: int | None = None
    llm_provider: str = "null"
    llm_model: str | None = None
    llm_fallback: bool = False
    sync_quality: dict[str, Any] | None = None
    cancel: CancellationToken = field(default_factory=CancellationToken)

    def to_dict(self) -> dict[str, Any]:
        """Return the public job snapshot. Assumes no secrets are stored on the job."""
        wall_ms = None
        if self.started_at is not None and self.completed_at is not None:
            wall_ms = max(0, self.completed_at - self.started_at)
        return {
            "job_id": self.id,
            "status": self.status,
            "inputs": self.inputs.to_dict(),
            "current_stage": self.current_stage,
            "progress_pct": self.progress_pct,
            "progress_message": self.progress_message,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "failure_stage": self.failure_stage,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "review_id": self.review_id,
            "wall_ms": wall_ms,
            "stage_timings": [
                {
                    "name": item.name,
                    "duration_ms": item.duration_ms,
                    "cache_hit": item.cache_hit,
                    "skipped": item.skipped,
                }
                for item in self.stage_timings
            ],
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "fact_count": self.fact_count,
            "finding_count": self.finding_count,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "llm_fallback": self.llm_fallback,
            "sync_quality": self.sync_quality,
        }
