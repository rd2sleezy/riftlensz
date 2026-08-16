from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from riftlens.config import Settings
from riftlens.orchestration.context import StageResult
from riftlens.orchestration.job import (
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_FAILED,
    AnalysisJob,
    JobInputs,
)
from riftlens.orchestration.progress import ProgressBus, ProgressEvent, now_ms
from riftlens.orchestration.runner import JobRunner
from riftlens.orchestration.stages import BaseStage, default_stages

FIXTURE = "NA1_fixture_b"


def _runner(tmp_path: Path, **kwargs: object) -> JobRunner:
    settings = Settings(data_dir=tmp_path, llm_provider="null")
    versions = kwargs.pop("stage_versions", None)
    stages = kwargs.pop("stages", None)
    bus = kwargs.pop("bus", None)
    return JobRunner(
        settings=settings,
        session_factory=None,
        bus=bus if isinstance(bus, ProgressBus) else ProgressBus(),
        stages=stages,  # type: ignore[arg-type]
        stage_versions=versions,  # type: ignore[arg-type]
    )


def _job(media_asset_id: str | None = None) -> AnalysisJob:
    return AnalysisJob(
        id="01H11JOB000000000000000001",
        inputs=JobInputs(
            match_id=FIXTURE,
            participant_id=5,
            media_asset_id=media_asset_id,
            llm_provider="null",
        ),
        created_at=now_ms(),
    )


@pytest.mark.asyncio
async def test_dag_skips_video_when_absent(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    job = await runner.run(_job())
    assert job.status == JOB_COMPLETED
    names = [item.name for item in job.stage_timings]
    assert names[:3] == ["ingest_riot", "ingest_video", "synchronize"]
    skipped = {item.name for item in job.stage_timings if item.skipped}
    assert "ingest_video" in skipped
    assert "synchronize" in skipped
    assert job.review_id


@pytest.mark.asyncio
async def test_rofl_media_does_not_enter_video_sync(tmp_path: Path) -> None:
    """A job without VIDEO media never runs OCR synchronize."""
    runner = _runner(tmp_path)
    job = await runner.run(_job(media_asset_id=None))
    sync = next(item for item in job.stage_timings if item.name == "synchronize")
    assert sync.skipped is True


@pytest.mark.asyncio
async def test_ingest_riot_and_video_may_run_in_parallel(tmp_path: Path) -> None:
    marks: dict[str, list[float]] = {"ingest_riot": [], "ingest_video": []}

    class Marker(BaseStage):
        cacheable = False

        def __init__(self, name: str) -> None:
            self.name = name

        async def run(self, ctx):  # type: ignore[no-untyped-def]
            del ctx
            marks[self.name].append(time.monotonic())
            await asyncio.sleep(0.12)
            marks[self.name].append(time.monotonic())
            return StageResult(outputs={})

    class Dummy(BaseStage):
        cacheable = False

        def __init__(self, name: str) -> None:
            self.name = name

        async def run(self, ctx):  # type: ignore[no-untyped-def]
            if self.name == "persist":
                ctx.artifacts["review_id"] = "parallel"
            return StageResult(outputs={})

    later = [
        Dummy(stage.name)
        for stage in default_stages()
        if stage.name not in {"ingest_riot", "ingest_video"}
    ]
    stages = [Marker("ingest_riot"), Marker("ingest_video"), *later]
    runner = _runner(tmp_path, stages=stages)
    job = await runner.run(_job(media_asset_id="01H11VIDEO0000000000000001"))
    assert job.status == JOB_COMPLETED, job.error_message
    riot = marks["ingest_riot"]
    video = marks["ingest_video"]
    assert riot[0] < video[1]
    assert video[0] < riot[1]


@pytest.mark.asyncio
async def test_stage_failure_records_stage_name(tmp_path: Path) -> None:
    class Boom(BaseStage):
        name = "run_rules"
        cacheable = False

        async def run(self, ctx):  # type: ignore[no-untyped-def]
            del ctx
            raise RuntimeError("rules exploded")

    stages = [Boom() if stage.name == "run_rules" else stage for stage in default_stages()]
    runner = _runner(tmp_path, stages=stages)
    job = await runner.run(_job())
    assert job.status == JOB_FAILED, job.error_message
    assert job.failure_stage == "run_rules"
    assert job.error_code == "RuntimeError"


@pytest.mark.asyncio
async def test_first_run_is_cache_miss(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    job = await runner.run(_job())
    assert job.status == JOB_COMPLETED, job.error_message
    executed = [item for item in job.stage_timings if not item.skipped]
    assert executed
    assert all(item.cache_hit is False for item in executed)


@pytest.mark.asyncio
async def test_ac3_run_rules_version_reuses_upstream(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    first = await runner.run(_job())
    assert first.status == JOB_COMPLETED, first.error_message
    second_runner = _runner(tmp_path, stage_versions={**runner._stage_versions, "run_rules": "2"})
    started = time.monotonic()
    second = await second_runner.run(_job())
    elapsed = time.monotonic() - started
    assert second.status == JOB_COMPLETED, second.error_message
    by_name = {item.name: item for item in second.stage_timings}
    assert by_name["ingest_riot"].cache_hit is True
    assert by_name["build_facts"].cache_hit is True
    assert by_name["compute_metrics"].cache_hit is True
    assert by_name["run_rules"].cache_hit is False
    assert by_name["prioritize"].cache_hit is False
    assert by_name["compose_coaching"].cache_hit is False
    assert elapsed < 10.0


@pytest.mark.asyncio
async def test_cancel_between_stages(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    job = _job()
    job.cancel.cancel()
    finished = await runner.run(job)
    assert finished.status == JOB_CANCELLED


@pytest.mark.asyncio
async def test_progress_is_monotonic_and_terminal(tmp_path: Path) -> None:
    bus = ProgressBus()
    runner = _runner(tmp_path, bus=bus)
    job = await runner.run(_job())
    assert job.status == JOB_COMPLETED
    events = bus.snapshot(job.id)
    assert events
    last_pct = -1
    last_stage = ""
    for event in events:
        if event.stage == last_stage:
            assert event.pct >= last_pct
        last_pct = event.pct
        last_stage = event.stage
    assert events[-1].status == JOB_COMPLETED
    assert events[-1].terminal is True


def test_sse_iterator_stops_on_terminal() -> None:
    bus = ProgressBus()
    bus.emit(
        ProgressEvent(
            job_id="j1",
            stage="persist",
            pct=100,
            message="done",
            ts=now_ms(),
            status=JOB_COMPLETED,
        )
    )
    yielded = list(bus.iter_sse("j1"))
    assert len(yielded) == 1
    assert yielded[0].terminal is True


def test_disconnected_subscriber_does_not_break_emit() -> None:
    bus = ProgressBus()
    bucket = bus.subscribe("j1")
    bus.unsubscribe("j1", bucket)
    bus.emit(
        ProgressEvent(
            job_id="j1",
            stage="ingest_riot",
            pct=10,
            message="ok",
            ts=now_ms(),
            status="RUNNING",
        )
    )
    assert bus.snapshot("j1")
