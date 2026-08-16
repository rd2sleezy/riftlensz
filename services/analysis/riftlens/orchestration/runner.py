from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Sequence

from sqlalchemy.orm import Session, sessionmaker

from riftlens.adapters.db.repositories.job import SqlJobRepository
from riftlens.config import Settings
from riftlens.orchestration.cache import StageCache
from riftlens.orchestration.context import (
    DEFAULT_STAGE_VERSIONS,
    STAGE_ORDER,
    VIDEO_STAGES,
    StageContext,
)
from riftlens.orchestration.job import (
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_QUEUED,
    JOB_RUNNING,
    AnalysisJob,
    JobCancelled,
    JobInputs,
    StageTiming,
)
from riftlens.orchestration.progress import ProgressBus, ProgressEvent, now_ms
from riftlens.orchestration.stages import BaseStage, default_stages
from riftlens.pipeline.sync.errors import AutoSyncError

_PARALLEL_FIRST = ("ingest_riot", "ingest_video")


class JobRunner:
    """Execute the H.11 DAG with cache, cancel, and progress. Wraps existing stages."""

    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: sessionmaker[Session] | None,
        bus: ProgressBus,
        stages: Sequence[BaseStage] | None = None,
        stage_versions: dict[str, str] | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._bus = bus
        self._stages = list(stages) if stages is not None else default_stages()
        self._stage_versions = dict(stage_versions or DEFAULT_STAGE_VERSIONS)
        self._cache = StageCache(settings.cache_dir / "stages")

    async def run(self, job: AnalysisJob, *, api_key: str | None = None) -> AnalysisJob:
        """Run all applicable stages. Assumes ``job`` is QUEUED or RUNNING."""
        ctx = StageContext(
            job=job,
            settings=self._settings,
            session_factory=self._session_factory,
            cache=self._cache,
            bus=self._bus,
            stage_versions=self._stage_versions,
            api_key=api_key,
        )
        job.status = JOB_RUNNING
        job.started_at = job.started_at or now_ms()
        job.llm_provider = job.inputs.llm_provider
        self._emit_status(job, "starting")
        by_name = {stage.name: stage for stage in self._stages}
        try:
            await self._run_ingest(ctx, by_name)
            for name in STAGE_ORDER:
                if name in _PARALLEL_FIRST:
                    continue
                stage = by_name[name]
                await self._run_one(ctx, stage)
            job.status = JOB_COMPLETED
            job.review_id = str(ctx.artifacts.get("review_id") or "") or None
            job.fact_count = ctx.artifacts.get("fact_count")
            findings = ctx.artifacts.get("findings")
            job.finding_count = len(findings) if findings is not None else None
            job.llm_fallback = bool(ctx.artifacts.get("llm_fallback"))
            job.llm_model = ctx.artifacts.get("llm_model")
            quality = ctx.artifacts.get("sync_quality")
            job.sync_quality = quality if isinstance(quality, dict) else None
            job.progress_pct = 100
            job.progress_message = "Completed"
            job.current_stage = "persist"
        except JobCancelled:
            job.status = JOB_CANCELLED
            job.error_code = "CANCELLED"
            job.error_message = "Job cancelled"
            job.failure_stage = job.current_stage
        except AutoSyncError as exc:
            job.status = JOB_FAILED
            job.error_code = exc.code
            job.error_message = exc.message
            job.failure_stage = job.current_stage
        except Exception as exc:
            job.status = JOB_FAILED
            job.error_code = type(exc).__name__
            job.error_message = str(exc) or type(exc).__name__
            job.failure_stage = job.current_stage
        job.completed_at = now_ms()
        self._emit_status(job, job.progress_message or job.status)
        return job

    async def _run_ingest(self, ctx: StageContext, by_name: dict[str, BaseStage]) -> None:
        riot = by_name["ingest_riot"]
        video = by_name["ingest_video"]
        if ctx.has_video():
            await asyncio.gather(self._run_one(ctx, riot), self._run_one(ctx, video))
            return
        await self._run_one(ctx, riot)
        await self._run_one(ctx, video)

    async def _run_one(self, ctx: StageContext, stage: BaseStage) -> None:
        ctx.job.current_stage = stage.name
        ctx.cancel.raise_if_set()
        ctx.last_stage_pct = 0
        skip_video = (not ctx.has_video()) and stage.name in VIDEO_STAGES
        started = now_ms()
        if skip_video:
            ctx.job.stage_timings.append(
                StageTiming(name=stage.name, duration_ms=0, cache_hit=False, skipped=True)
            )
            await ctx.tick(stage.name, 100, f"Skipped {stage.name}")
            return
        version = stage.bound_version(ctx)
        refs = self._cache_refs(ctx, stage)
        if stage.cacheable:
            cached = ctx.cache.get(stage.name, version, refs)
            if cached is not None:
                stage.restore(ctx, cached)
                elapsed = max(0, now_ms() - started)
                ctx.job.stage_timings.append(
                    StageTiming(name=stage.name, duration_ms=elapsed, cache_hit=True)
                )
                ctx.job.cache_hits += 1
                await ctx.tick(stage.name, 100, f"Cache hit {stage.name}")
                return
        ctx.job.cache_misses += 1
        result = await stage.run(ctx)
        if result.skipped:
            elapsed = max(0, now_ms() - started)
            ctx.job.stage_timings.append(
                StageTiming(name=stage.name, duration_ms=elapsed, cache_hit=False, skipped=True)
            )
            return
        ctx.artifacts.update(result.outputs)
        if stage.cacheable:
            ctx.cache.put(stage.name, version, refs, stage.stored_outputs(result.outputs))
        elapsed = max(0, now_ms() - started)
        ctx.job.stage_timings.append(
            StageTiming(name=stage.name, duration_ms=elapsed, cache_hit=False)
        )

    def _cache_refs(self, ctx: StageContext, stage: BaseStage) -> dict[str, object]:
        return {
            **ctx.input_refs(stage.inputs, stage_name=stage.name),
            **stage.extra_cache_refs(ctx),
        }

    def _emit_status(self, job: AnalysisJob, message: str) -> None:
        self._bus.emit(
            ProgressEvent(
                job_id=job.id,
                stage=job.current_stage or "",
                pct=job.progress_pct,
                message=message,
                ts=now_ms(),
                status=job.status,
            )
        )


class JobService:
    """In-memory + SQLite job registry with a dedicated worker loop."""

    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session] | None,
        *,
        persist: Callable[[AnalysisJob], None] | None = None,
        stage_versions: dict[str, str] | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._bus = ProgressBus()
        self._lock = threading.Lock()
        self._jobs: dict[str, AnalysisJob] = {}
        self._jobs_repo = (
            None if session_factory is None else SqlJobRepository(session_factory)
        )
        self._persist = persist
        self._stage_versions = dict(stage_versions or DEFAULT_STAGE_VERSIONS)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="h11-jobs", daemon=True)
        self._thread.start()
        self._fail_orphans()

    @property
    def bus(self) -> ProgressBus:
        """Return the progress fan-out bus."""
        return self._bus

    def create(
        self,
        inputs: JobInputs,
        *,
        job_id: str | None = None,
    ) -> AnalysisJob:
        """Queue a new analysis job. Does not start it."""
        from riftlens.domain.ids import new_ulid

        job = AnalysisJob(
            id=job_id or new_ulid(),
            inputs=inputs,
            status=JOB_QUEUED,
            created_at=now_ms(),
            llm_provider=inputs.llm_provider,
            llm_model=inputs.llm_model or None,
        )
        with self._lock:
            self._jobs[job.id] = job
        self._write(job)
        return job

    def submit(self, job_id: str, *, api_key: str | None = None) -> None:
        """Start ``job_id`` on the worker loop. API keys are not persisted."""
        asyncio.run_coroutine_threadsafe(self._execute(job_id, api_key), self._loop)

    def get(self, job_id: str) -> AnalysisJob | None:
        """Return a job snapshot or None."""
        with self._lock:
            return self._jobs.get(job_id)

    def last_job(self) -> AnalysisJob | None:
        """Return the most recently completed/failed/cancelled job, else the latest."""
        with self._lock:
            jobs = list(self._jobs.values())
        if not jobs:
            return None
        finished = [job for job in jobs if job.completed_at is not None]
        pool = finished or jobs
        return max(pool, key=lambda job: job.completed_at or job.created_at)

    def cancel(self, job_id: str) -> AnalysisJob | None:
        """Request cooperative cancellation. Returns the job or None if missing."""
        job = self.get(job_id)
        if job is None:
            return None
        job.cancel.cancel()
        if job.status == JOB_QUEUED:
            job.status = JOB_CANCELLED
            job.error_code = "CANCELLED"
            job.error_message = "Job cancelled"
            job.completed_at = now_ms()
            self._write(job)
            self._bus.emit(
                ProgressEvent(
                    job_id=job.id,
                    stage=job.current_stage or "",
                    pct=job.progress_pct,
                    message="Cancelled",
                    ts=now_ms(),
                    status=JOB_CANCELLED,
                )
            )
        return job

    def shutdown(self) -> None:
        """Stop the worker loop. Running jobs are cancelled."""
        with self._lock:
            running = [job for job in self._jobs.values() if job.status == JOB_RUNNING]
        for job in running:
            job.cancel.cancel()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=3.0)

    async def _execute(self, job_id: str, api_key: str | None) -> None:
        job = self.get(job_id)
        if job is None:
            return
        runner = JobRunner(
            settings=self._settings,
            session_factory=self._session_factory,
            bus=self._bus,
            stage_versions=self._stage_versions,
        )
        try:
            await runner.run(job, api_key=api_key)
        finally:
            self._write(job)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _write(self, job: AnalysisJob) -> None:
        if self._jobs_repo is not None:
            self._jobs_repo.upsert_sync(job)
        if self._persist is not None:
            self._persist(job)

    def _fail_orphans(self) -> None:
        if self._jobs_repo is None:
            return
        self._jobs_repo.fail_running_sync(now_ms())
