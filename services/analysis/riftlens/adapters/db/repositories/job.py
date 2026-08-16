from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from riftlens.adapters.db.models import AnalysisJobRow
from riftlens.adapters.db.repositories.base import SessionRepository
from riftlens.orchestration.job import (
    JOB_FAILED,
    JOB_RUNNING,
    AnalysisJob,
    JobInputs,
    StageTiming,
)


class SqlJobRepository(SessionRepository):
    async def upsert(self, job: AnalysisJob) -> None:
        """Insert or replace a job row. Never stores API keys."""
        await self.call(lambda session: session.merge(_job_row(job)))

    def upsert_sync(self, job: AnalysisJob) -> None:
        """Synchronous upsert for the worker thread. Never stores API keys."""
        self.run(lambda session: session.merge(_job_row(job)))

    async def get(self, job_id: str) -> AnalysisJob | None:
        """Return a persisted job or None."""

        def work(session: Session) -> AnalysisJob | None:
            found = session.get(AnalysisJobRow, job_id)
            return None if found is None else _job_from_row(found)

        return await self.call(work)

    async def last(self) -> AnalysisJob | None:
        """Return the most recently completed job, else the latest created."""

        def work(session: Session) -> AnalysisJob | None:
            found = session.scalar(
                select(AnalysisJobRow).order_by(
                    AnalysisJobRow.completed_at.desc(), AnalysisJobRow.created_at.desc()
                )
            )
            return None if found is None else _job_from_row(found)

        return await self.call(work)

    async def fail_running(self, now_ms: int) -> int:
        """Mark leftover RUNNING jobs FAILED after a crash. Returns the count."""
        return await self.call(lambda session: _fail_running_rows(session, now_ms))

    def fail_running_sync(self, now_ms: int) -> int:
        """Synchronous crash recovery. Returns the count of interrupted jobs."""
        return self.run(lambda session: _fail_running_rows(session, now_ms))


def _job_row(job: AnalysisJob) -> AnalysisJobRow:
    return AnalysisJobRow(
        id=job.id,
        status=job.status,
        match_id=job.inputs.match_id,
        participant_id=job.inputs.participant_id,
        media_asset_id=job.inputs.media_asset_id,
        current_stage=job.current_stage,
        progress_pct=job.progress_pct,
        progress_message=job.progress_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        failure_stage=job.failure_stage,
        error_code=job.error_code,
        error_message=job.error_message,
        review_id=job.review_id,
        stage_timings_json=json.dumps(
            [
                {
                    "name": item.name,
                    "duration_ms": item.duration_ms,
                    "cache_hit": item.cache_hit,
                    "skipped": item.skipped,
                }
                for item in job.stage_timings
            ]
        ),
        cache_hits=job.cache_hits,
        cache_misses=job.cache_misses,
        inputs_json=json.dumps(job.inputs.to_dict()),
        llm_provider=job.llm_provider,
        llm_model=job.llm_model,
        llm_fallback=1 if job.llm_fallback else 0,
        fact_count=job.fact_count,
        finding_count=job.finding_count,
        sync_quality_json=None if job.sync_quality is None else json.dumps(job.sync_quality),
    )


def _job_from_row(row: AnalysisJobRow) -> AnalysisJob:
    raw_inputs: dict[str, Any] = json.loads(row.inputs_json)
    timings_raw = json.loads(row.stage_timings_json or "[]")
    quality = json.loads(row.sync_quality_json) if row.sync_quality_json else None
    return AnalysisJob(
        id=row.id,
        inputs=JobInputs(
            match_id=str(raw_inputs.get("match_id") or row.match_id),
            participant_id=int(raw_inputs.get("participant_id") or row.participant_id),
            media_asset_id=raw_inputs.get("media_asset_id"),
            rank=str(raw_inputs.get("rank") or "UNRANKED"),
            llm_provider=str(raw_inputs.get("llm_provider") or "null"),
            llm_model=str(raw_inputs.get("llm_model") or ""),
            region=raw_inputs.get("region"),
        ),
        status=row.status,
        current_stage=row.current_stage,
        progress_pct=row.progress_pct,
        progress_message=row.progress_message or "",
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        failure_stage=row.failure_stage,
        error_code=row.error_code,
        error_message=row.error_message,
        review_id=row.review_id,
        stage_timings=[
            StageTiming(
                name=str(item["name"]),
                duration_ms=int(item["duration_ms"]),
                cache_hit=bool(item.get("cache_hit")),
                skipped=bool(item.get("skipped")),
            )
            for item in timings_raw
        ],
        cache_hits=row.cache_hits,
        cache_misses=row.cache_misses,
        fact_count=row.fact_count,
        finding_count=row.finding_count,
        llm_provider=row.llm_provider or "null",
        llm_model=row.llm_model,
        llm_fallback=bool(row.llm_fallback),
        sync_quality=quality if isinstance(quality, dict) else None,
    )


def _fail_running_rows(session: Session, now_ms: int) -> int:
    rows = session.scalars(select(AnalysisJobRow).where(AnalysisJobRow.status == JOB_RUNNING)).all()
    for row in rows:
        row.status = JOB_FAILED
        row.error_code = "INTERRUPTED"
        row.error_message = "Process restarted while the job was running"
        row.completed_at = now_ms
    return len(rows)
