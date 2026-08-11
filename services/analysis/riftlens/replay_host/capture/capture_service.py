"""Async R.10 capture orchestration. Explicit requests only — never the reveal path."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from riftlens.domain.capture import (
    ARTIFACT_KIND_CLIP,
    DEFAULT_CAPTURE_BUDGET,
    DEFAULT_CAPTURE_TIMEOUT_S,
    TERMINAL_STATUSES,
    CaptureArtifactSpec,
    CaptureBudget,
    CaptureManifest,
    CaptureMode,
    CaptureProgress,
    CaptureRequest,
    CaptureResult,
    CaptureStatus,
    RetentionClass,
    check_budget,
    resolve_mode_settings,
    validate_interval,
)
from riftlens.domain.clock_map import ClockMap, ClockMode
from riftlens.domain.ids import new_ulid
from riftlens.domain.ports import (
    CaptureIntervalRecord,
    CaptureRepository,
    ClockCalibrationRecord,
    GameplayRepository,
    GameplaySourceSnapshot,
    MediaArtifactRecord,
)
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.capture import artifact_store
from riftlens.replay_host.capture.budgets import estimate_artifact_bytes, estimate_artifacts
from riftlens.replay_host.capture.recording import DEFAULT_POLL_INTERVAL_S
from riftlens.replay_host.capture.retention import RetentionPolicy, RetentionService
from riftlens.replay_host.port import ReplayHostPort
from riftlens.replay_host.session import ReplaySessionSnapshot

CAPTURE_REASON_USER = "explicit_user_request"


@dataclass
class _CaptureJob:
    """In-flight capture bookkeeping. Progress is written from the recording thread."""

    capture_id: str
    cancel: threading.Event
    directory: Path
    progress: CaptureProgress
    task: asyncio.Task[None] | None = None


class CaptureService:
    """Creates capture rows, drives the host recorder off-thread, and persists artifacts."""

    def __init__(
        self,
        *,
        host: ReplayHostPort,
        captures: CaptureRepository,
        gameplay: GameplayRepository,
        captures_dir: Path,
        budget: CaptureBudget = DEFAULT_CAPTURE_BUDGET,
        retention: RetentionService | None = None,
        retention_policy: RetentionPolicy | None = None,
        timeout_s: float = DEFAULT_CAPTURE_TIMEOUT_S,
        poll_s: float = DEFAULT_POLL_INTERVAL_S,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._host = host
        self._captures = captures
        self._gameplay = gameplay
        self._root = Path(captures_dir)
        self._budget = budget
        self._retention = (
            retention
            if retention is not None
            else RetentionService(
                captures=captures, captures_dir=captures_dir, policy=retention_policy
            )
        )
        self._timeout_s = timeout_s
        self._poll_s = poll_s
        self._clock = clock
        self._jobs: dict[str, _CaptureJob] = {}

    @property
    def retention(self) -> RetentionService:
        """Return the retention service so callers can run GC without a second wiring."""
        return self._retention

    @property
    def captures_dir(self) -> Path:
        """Return the capture root this service writes to."""
        return self._root

    def now_ms(self) -> int:
        """Wall-clock milliseconds for persistence timestamps."""
        return int(self._clock() * 1000)

    async def start_capture(
        self, request: CaptureRequest, *, now_ms: int | None = None
    ) -> CaptureResult:
        """Validate, budget-check, persist a REQUESTED row, and start the background job."""
        stamp = self.now_ms() if now_ms is None else int(now_ms)
        capture_id = new_ulid()
        try:
            validate_interval(request.start_game_ms, request.end_game_ms)
            snapshot = await self._require_source(request.source_id)
            calibration = _require_clock(snapshot)
            clock = calibration.clock
            start_source_ms, end_source_ms = _require_source_window(
                clock, request.start_game_ms, request.end_game_ms
            )
            self._require_ready()
            settings = resolve_mode_settings(
                request.mode, request.fps, request.start_game_ms, request.end_game_ms
            )
            planned_artifacts = estimate_artifacts(
                expected_artifacts=settings.expected_artifacts,
                max_artifacts=request.max_artifacts,
            )
            await self._check_budget(request, planned_artifacts, settings.kind)
        except ReplayError as exc:
            return CaptureResult(
                ok=False,
                capture_id=capture_id,
                status=CaptureStatus.FAILED,
                error=exc,
            )
        record = CaptureIntervalRecord(
            id=capture_id,
            gameplay_source_id=request.source_id,
            match_id=snapshot.source.match_id,
            clock_map_id=calibration.id,
            t_start_ms=int(request.start_game_ms),
            t_end_ms=int(request.end_game_ms),
            reason=CAPTURE_REASON_USER,
            mode=request.mode.value,
            fps=settings.fps,
            status=CaptureStatus.REQUESTED.value,
            progress=0.0,
            retention_class=request.retention.value,
            created_at=stamp,
            t_start_source_ms=start_source_ms,
            t_end_source_ms=end_source_ms,
            review_id=request.review_id,
        )
        await self._captures.upsert_interval(record)
        directory = artifact_store.ensure_capture_dir(
            self._root, snapshot.source.match_id, capture_id
        )
        job = _CaptureJob(
            capture_id=capture_id,
            cancel=threading.Event(),
            directory=directory,
            progress=CaptureProgress(
                capture_id=capture_id,
                status=CaptureStatus.REQUESTED,
                fraction=0.0,
                message="queued",
            ),
        )
        self._jobs[capture_id] = job
        job.task = asyncio.create_task(self._run(job, request, record, snapshot, calibration))
        return CaptureResult(
            ok=True,
            capture_id=capture_id,
            status=CaptureStatus.REQUESTED,
            progress=job.progress,
        )

    async def get_progress(self, capture_id: str) -> CaptureProgress:
        """Return live progress when the job is running, else the persisted snapshot."""
        job = self._jobs.get(capture_id)
        if job is not None:
            return job.progress
        row = await self._captures.get_interval(capture_id)
        if row is None:
            raise ReplayError(
                ReplayErrorCode.CAPTURE_OUTPUT_MISSING,
                details={"reason": "unknown_capture", "capture_id": capture_id},
            )
        status = _status_of(row)
        return CaptureProgress(
            capture_id=capture_id,
            status=status,
            fraction=row.progress,
            message=row.error_code or status.value,
        )

    async def get_result(self, capture_id: str) -> CaptureResult:
        """Return the current result view without waiting for a running job to finish."""
        row = await self._captures.get_interval(capture_id)
        if row is None:
            return CaptureResult(
                ok=False,
                capture_id=capture_id,
                status=CaptureStatus.FAILED,
                error=ReplayError(
                    ReplayErrorCode.CAPTURE_OUTPUT_MISSING,
                    details={"reason": "unknown_capture", "capture_id": capture_id},
                ),
            )
        return self._result_from_row(row)

    async def cancel(self, capture_id: str) -> CaptureResult:
        """Signal cancellation and wait for the worker to unwind. Leaves no partials."""
        job = self._jobs.get(capture_id)
        if job is not None:
            job.cancel.set()
            if job.task is not None:
                await asyncio.gather(job.task, return_exceptions=True)
            result = await self.get_result(capture_id)
            if result.status is CaptureStatus.FAILED:
                await self._force_cancelled(job)
                return await self.get_result(capture_id)
            return result
        row = await self._captures.get_interval(capture_id)
        if row is None:
            return await self.get_result(capture_id)
        if _status_of(row) in TERMINAL_STATUSES:
            return self._result_from_row(row)
        artifact_store.delete_capture_dir(self._directory_for(row))
        await self._captures.update_status(
            capture_id,
            CaptureStatus.CANCELLED.value,
            progress=row.progress,
            error_code=ReplayErrorCode.CAPTURE_CANCELLED.value,
            completed_at=self.now_ms(),
        )
        return await self.get_result(capture_id)

    async def await_result(
        self, capture_id: str, *, timeout_s: float | None = None
    ) -> CaptureResult:
        """Wait for a running capture then return its result. Missing jobs read the row."""
        job = self._jobs.get(capture_id)
        if job is not None and job.task is not None:
            if timeout_s is None:
                await asyncio.gather(job.task, return_exceptions=True)
            else:
                await asyncio.wait({job.task}, timeout=timeout_s)
                if not job.task.done():
                    raise ReplayError(
                        ReplayErrorCode.CAPTURE_TIMEOUT,
                        details={"reason": "await_timeout", "capture_id": capture_id},
                    )
        return await self.get_result(capture_id)

    async def list_for_source(self, source_id: str) -> tuple[CaptureIntervalRecord, ...]:
        """Return persisted captures for a source, newest first."""
        return tuple(await self._captures.list_for_source(source_id))

    async def _run(
        self,
        job: _CaptureJob,
        request: CaptureRequest,
        record: CaptureIntervalRecord,
        snapshot: GameplaySourceSnapshot,
        calibration: ClockCalibrationRecord,
    ) -> None:
        await self._captures.update_status(
            job.capture_id, CaptureStatus.RUNNING.value, progress=0.0
        )
        job.progress = CaptureProgress(
            capture_id=job.capture_id,
            status=CaptureStatus.RUNNING,
            fraction=0.0,
            message="recording",
        )

        def note(progress: CaptureProgress) -> None:
            job.progress = progress

        try:
            result = await asyncio.to_thread(
                self._host.capture_interval,
                request.start_game_ms,
                request.end_game_ms,
                calibration.clock,
                output_dir=str(job.directory),
                capture_id=job.capture_id,
                mode=request.mode,
                fps=request.fps,
                max_artifacts=request.max_artifacts,
                timeout_s=self._timeout_s,
                poll_s=self._poll_s,
                cancel=job.cancel,
                on_progress=note,
            )
        except ReplayError as exc:
            result = CaptureResult(
                ok=False, capture_id=job.capture_id, status=CaptureStatus.FAILED, error=exc
            )
        try:
            if result.ok:
                await self._finish_complete(job, request, record, snapshot, calibration, result)
            else:
                await self._finish_failed(job, result)
        finally:
            self._jobs.pop(job.capture_id, None)

    async def _finish_complete(
        self,
        job: _CaptureJob,
        request: CaptureRequest,
        record: CaptureIntervalRecord,
        snapshot: GameplaySourceSnapshot,
        calibration: ClockCalibrationRecord,
        result: CaptureResult,
    ) -> None:
        completed_at = self.now_ms()
        manifest = _build_manifest(
            record=record,
            request=request,
            snapshot=snapshot,
            calibration=calibration,
            artifacts=result.artifacts,
            completed_at_ms=completed_at,
        )
        artifact_store.write_manifest(job.directory, manifest)
        rows = [
            MediaArtifactRecord(
                id=spec.id,
                capture_interval_id=job.capture_id,
                kind=spec.kind,
                path=str(job.directory / spec.relative_path),
                content_hash=spec.sha256,
                created_at=completed_at,
                game_t_ms=spec.game_t_ms,
                source_t_ms=spec.source_t_ms,
                frame_index=spec.frame_index,
                retention_class=request.retention.value,
                bytes=spec.bytes,
                width=spec.width,
                height=spec.height,
            )
            for spec in result.artifacts
        ]
        await self._captures.replace_artifacts(job.capture_id, rows)
        await self._captures.update_status(
            job.capture_id,
            CaptureStatus.COMPLETE.value,
            progress=1.0,
            completed_at=completed_at,
            artifact_count=len(rows),
            total_bytes=sum(spec.bytes for spec in result.artifacts),
            manifest_json=json.dumps(manifest.to_dict(), sort_keys=True),
        )
        job.progress = CaptureProgress(
            capture_id=job.capture_id,
            status=CaptureStatus.COMPLETE,
            fraction=1.0,
            message="complete",
        )
        await self._retention.enforce_size_ceiling()

    async def _finish_failed(self, job: _CaptureJob, result: CaptureResult) -> None:
        artifact_store.delete_capture_dir(job.directory)
        artifact_store.prune_empty_parents(job.directory.parent, stop_at=self._root)
        cancelled = job.cancel.is_set() or result.status is CaptureStatus.CANCELLED
        status = CaptureStatus.CANCELLED if cancelled else result.status
        error_code = (
            ReplayErrorCode.CAPTURE_CANCELLED.value
            if cancelled
            else (
                result.error.code.value
                if result.error is not None
                else ReplayErrorCode.CAPTURE_RECORDING_FAILED.value
            )
        )
        await self._captures.replace_artifacts(job.capture_id, [])
        await self._captures.update_status(
            job.capture_id,
            status.value,
            progress=0.0,
            error_code=error_code,
            completed_at=self.now_ms(),
            artifact_count=0,
            total_bytes=0,
        )
        job.progress = CaptureProgress(
            capture_id=job.capture_id,
            status=status,
            fraction=0.0,
            message=error_code,
        )

    async def _force_cancelled(self, job: _CaptureJob) -> None:
        """Rewrite a raced FAILED terminal into CANCELLED after an explicit cancel ask."""
        artifact_store.delete_capture_dir(job.directory)
        artifact_store.prune_empty_parents(job.directory.parent, stop_at=self._root)
        await self._captures.replace_artifacts(job.capture_id, [])
        await self._captures.update_status(
            job.capture_id,
            CaptureStatus.CANCELLED.value,
            progress=0.0,
            error_code=ReplayErrorCode.CAPTURE_CANCELLED.value,
            completed_at=self.now_ms(),
            artifact_count=0,
            total_bytes=0,
        )
        job.progress = CaptureProgress(
            capture_id=job.capture_id,
            status=CaptureStatus.CANCELLED,
            fraction=0.0,
            message=ReplayErrorCode.CAPTURE_CANCELLED.value,
        )

    async def _require_source(self, source_id: str) -> GameplaySourceSnapshot:
        snapshot = await self._gameplay.get_source(source_id)
        if snapshot is None:
            raise ReplayError(
                ReplayErrorCode.ROFL_MISSING,
                details={"reason": "unknown_source", "source_id": source_id},
            )
        if not snapshot.file_present:
            raise ReplayError(
                ReplayErrorCode.ROFL_MISSING,
                details={"reason": "source_file_missing", "source_id": source_id},
            )
        return snapshot

    def _require_ready(self) -> None:
        state: ReplaySessionSnapshot = self._host.poll_health()
        if state.error is not None and state.error.code is ReplayErrorCode.SESSION_LOST:
            raise state.error
        if not state.is_active:
            raise ReplayError(
                ReplayErrorCode.SOURCE_NOT_READY, details={"phase": state.phase.value}
            )

    async def _check_budget(
        self, request: CaptureRequest, planned_artifacts: int, kind: str
    ) -> None:
        used_seconds = 0.0
        used_artifacts = 0
        used_bytes = 0
        if request.review_id is not None:
            used_seconds, used_artifacts, used_bytes = await self._captures.sum_usage_for_review(
                request.review_id
            )
        check_budget(
            self._budget,
            duration_ms=request.duration_ms,
            artifact_count=planned_artifacts,
            byte_count=estimate_artifact_bytes(
                kind=kind, artifacts=planned_artifacts, duration_ms=request.duration_ms
            ),
            existing_seconds=used_seconds,
            existing_artifacts=used_artifacts,
            existing_bytes=used_bytes,
        )

    def _directory_for(self, record: CaptureIntervalRecord) -> Path:
        return artifact_store.capture_dir(self._root, record.match_id or "unknown", record.id)

    def _result_from_row(self, row: CaptureIntervalRecord) -> CaptureResult:
        status = _status_of(row)
        manifest = _manifest_from_json(row.manifest_json)
        error = (
            None
            if row.error_code is None
            else ReplayError(_error_code(row.error_code), details={"capture_id": row.id})
        )
        return CaptureResult(
            ok=status is CaptureStatus.COMPLETE,
            capture_id=row.id,
            status=status,
            manifest=manifest,
            artifacts=() if manifest is None else manifest.artifacts,
            error=error,
            progress=CaptureProgress(
                capture_id=row.id,
                status=status,
                fraction=row.progress,
                message=row.error_code or status.value,
            ),
        )


def _require_clock(snapshot: GameplaySourceSnapshot) -> ClockCalibrationRecord:
    calibration = snapshot.clock
    if calibration is None or calibration.clock.mode is ClockMode.UNMAPPED:
        raise ReplayError(
            ReplayErrorCode.CLOCK_UNMAPPED,
            details={"reason": "no_active_clock", "source_id": snapshot.source.id},
        )
    return calibration


def _require_source_window(
    clock: ClockMap, start_game_ms: int, end_game_ms: int
) -> tuple[int, int]:
    start_source_ms = clock.game_to_source(int(start_game_ms))
    end_source_ms = clock.game_to_source(int(end_game_ms))
    if start_source_ms is None or end_source_ms is None:
        raise ReplayError(
            ReplayErrorCode.CLOCK_OUT_OF_BOUNDS,
            details={
                "reason": "capture_interval_uncovered",
                "start_game_ms": int(start_game_ms),
                "end_game_ms": int(end_game_ms),
            },
        )
    return start_source_ms, end_source_ms


def _build_manifest(
    *,
    record: CaptureIntervalRecord,
    request: CaptureRequest,
    snapshot: GameplaySourceSnapshot,
    calibration: ClockCalibrationRecord,
    artifacts: tuple[CaptureArtifactSpec, ...],
    completed_at_ms: int,
) -> CaptureManifest:
    codec = request.codec or (
        "webm" if artifacts and artifacts[0].kind == ARTIFACT_KIND_CLIP else "png"
    )
    resolved_fps = record.fps
    if resolved_fps is None:
        resolved_fps = resolve_mode_settings(
            CaptureMode(record.mode),
            request.fps,
            record.t_start_ms,
            record.t_end_ms,
        ).fps
    return CaptureManifest(
        capture_id=record.id,
        source_id=record.gameplay_source_id,
        match_id=snapshot.source.match_id,
        clock_map_id=calibration.id,
        mode=CaptureMode(record.mode),
        codec=codec,
        fps=float(resolved_fps),
        requested_start_game_ms=record.t_start_ms,
        requested_end_game_ms=record.t_end_ms,
        start_source_ms=record.t_start_source_ms or 0,
        end_source_ms=record.t_end_source_ms or 0,
        retention=RetentionClass(record.retention_class),
        status=CaptureStatus.COMPLETE,
        created_at_ms=record.created_at,
        clock_confidence=calibration.clock.confidence.value,
        clock_verified=calibration.clock.verified,
        review_id=record.review_id,
        completed_at_ms=completed_at_ms,
        declared_patch=None if snapshot.rofl is None else snapshot.rofl.declared_patch,
        artifacts=artifacts,
    )


def _manifest_from_json(payload: str | None) -> CaptureManifest | None:
    if not payload:
        return None
    try:
        decoded = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(decoded, dict):
        return None
    try:
        return CaptureManifest.from_dict(decoded)
    except (KeyError, TypeError, ValueError):
        return None


def _status_of(row: CaptureIntervalRecord) -> CaptureStatus:
    try:
        return CaptureStatus(row.status)
    except ValueError:
        return CaptureStatus.FAILED


def _error_code(value: str) -> ReplayErrorCode:
    try:
        return ReplayErrorCode(value)
    except ValueError:
        return ReplayErrorCode.CAPTURE_RECORDING_FAILED
