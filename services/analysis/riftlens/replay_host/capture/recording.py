"""``/replay/recording`` choreography and the synchronous capture engine (§7.1)."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from riftlens.domain.camera_framing import (
    CameraFramingMetadata,
    CameraFramingPlan,
    CameraFramingStatus,
    metadata_for_plan,
)
from riftlens.domain.capture import (
    ARTIFACT_KIND_CLIP,
    DEFAULT_CAPTURE_POLL_S,
    DEFAULT_CAPTURE_TIMEOUT_S,
    DEFAULT_MAX_ARTIFACTS,
    CaptureArtifactSpec,
    CaptureCoverage,
    CaptureCoverageVerdict,
    CaptureMode,
    CaptureProgress,
    CaptureResult,
    CaptureStatus,
    RecordingCompletionMethod,
    capture_duration_covers,
    min_acceptable_capture_duration_ms,
    resolve_mode_settings,
    validate_interval,
)
from riftlens.domain.clock_map import ClockMap
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.api.models import ReplayPlayback, ReplayRecording
from riftlens.replay_host.capture import artifact_store, frames
from riftlens.replay_host.capture.camera_framing import (
    FramingApiClient,
    FramingStickyClient,
    RenderClient,
    SavedRenderState,
    apply_framing,
    restore_framing,
)
from riftlens.replay_host.capture.media_probe import probe_clip_media
from riftlens.replay_host.timing import SleepClock, WallClock

DEFAULT_POLL_INTERVAL_S = DEFAULT_CAPTURE_POLL_S
START_GRACE_POLLS = 3
SEEK_BEFORE_RECORD_TIMEOUT_S = 90.0
SEEK_LANDING_TOLERANCE_S = 1.5
TEMP_STABLE_POLLS = 3
PLAYBACK_END_TOLERANCE_S = 0.75

ProgressSink = Callable[[CaptureProgress], None]


class RecordingClient(Protocol):
    """Replay API subset the capture engine needs. Tests inject the R.4 client verbatim."""

    def get_recording(self) -> ReplayRecording:
        """GET /replay/recording."""

    def set_recording(self, patch: Mapping[str, Any]) -> ReplayRecording:
        """POST /replay/recording."""

    def get_playback(self) -> ReplayPlayback:
        """GET /replay/playback."""

    def set_playback(
        self,
        *,
        paused: bool | None = None,
        time: float | None = None,
        speed: float | None = None,
        readback: bool = True,
    ) -> ReplayPlayback | None:
        """POST /replay/playback."""


@dataclass(frozen=True)
class RecordingProgress:
    """One ``GET /replay/recording`` sample expressed as a 0..1 fraction."""

    recording: bool
    current_source_ms: int | None
    fraction: float


class RecordingOrchestrator:
    """Starts, polls, and stops one recording. Owns no files and no retention policy."""

    def __init__(self, client: RecordingClient, *, clock: SleepClock | None = None) -> None:
        self._client = client
        self._clock = clock if clock is not None else WallClock()
        self._start_s = 0.0
        self._end_s = 0.0
        self._output_path: Path | None = None
        self.api_dropout_count = 0
        self.completion_method: RecordingCompletionMethod | None = None
        self.temp_promotion_method: str | None = None
        self._last_progress: RecordingProgress | None = None
        self._started_mono = 0.0

    def start(
        self,
        path: Path,
        *,
        start_s: float,
        end_s: float,
        codec: str,
        fps: float,
        lossless: bool = False,
        enforce_frame_rate: bool = True,
    ) -> ReplayRecording:
        """Seek to ``start_s``, unpause, then POST ``recording=true``. Times are source seconds.

        ``enforce_frame_rate`` must be False on macOS: True makes League accelerate
        playback ~5x during encode, so a 17s game interval becomes ~4s of media.
        """
        self._start_s = float(start_s)
        self._end_s = float(end_s)
        self._output_path = Path(path)
        self.api_dropout_count = 0
        self.completion_method = None
        self.temp_promotion_method = None
        self._last_progress = None
        self._started_mono = self._clock.monotonic()
        # Land the seek before encode — starting mid-seek crashes macOS League encode.
        self._await_seek_landing(float(start_s))
        self._client.set_playback(paused=False, speed=1.0, readback=False)
        patch = {
            "recording": True,
            "codec": codec,
            "path": str(path),
            "startTime": float(start_s),
            "endTime": float(end_s),
            "framesPerSecond": float(fps),
            "enforceFrameRate": bool(enforce_frame_rate),
            "lossless": bool(lossless),
            "replaySpeed": 1.0,
        }
        try:
            return self._client.set_recording(patch)
        except ReplayError as exc:
            # POST often succeeds; the follow-up GET /replay/recording times out mid-encode.
            if not _is_transient_recording_poll(exc):
                raise
            recovered = self._recover_recording_after_start_timeout()
            if recovered is not None:
                return recovered
            return ReplayRecording(
                recording=True,
                codec=codec,
                path=str(path),
                startTime=float(start_s),
                endTime=float(end_s),
                framesPerSecond=float(fps),
                enforceFrameRate=bool(enforce_frame_rate),
                lossless=bool(lossless),
                replaySpeed=1.0,
            )

    def poll(self) -> RecordingProgress:
        """Return one progress sample. Assumes ``start`` already ran."""
        return self._progress(self._client.get_recording())

    def stop(self) -> ReplayRecording:
        """POST ``recording=false``. Safe to call when the client already stopped."""
        return self._client.set_recording({"recording": False})

    def wait_until_complete(
        self,
        *,
        timeout_s: float = DEFAULT_CAPTURE_TIMEOUT_S,
        poll_s: float = DEFAULT_POLL_INTERVAL_S,
        cancel: threading.Event | None = None,
        on_progress: Callable[[RecordingProgress], None] | None = None,
    ) -> ReplayRecording:
        """Poll until replay covered the interval and encode finished. Raises typed errors."""
        deadline = self._clock.monotonic() + max(0.0, timeout_s)
        started = False
        idle_polls = 0
        stable_bytes: int | None = None
        stable_count = 0
        source_budget_s = max(5.0, (self._end_s - self._start_s) + 30.0)
        while True:
            if cancel is not None and cancel.is_set():
                self._safe_stop()
                raise ReplayError(
                    ReplayErrorCode.CAPTURE_CANCELLED,
                    details={"reason": "cancelled_during_recording"},
                )
            try:
                recording = self._client.get_recording()
            except ReplayError as exc:
                if cancel is not None and cancel.is_set():
                    self._safe_stop()
                    raise ReplayError(
                        ReplayErrorCode.CAPTURE_CANCELLED,
                        details={
                            "reason": "cancelled_during_api_loss",
                            "underlying": exc.code.value,
                        },
                    ) from exc
                self.api_dropout_count += 1
                size = (
                    0
                    if self._output_path is None
                    else artifact_store.recorder_output_bytes(self._output_path)
                )
                if size > 0 and size == stable_bytes:
                    stable_count += 1
                elif size > 0:
                    stable_bytes = size
                    stable_count = 1
                else:
                    stable_bytes = None
                    stable_count = 0
                recovered = self._recover_from_temp_output(
                    previous_bytes=stable_bytes,
                    stable_count=stable_count,
                    near_deadline=(
                        self._clock.monotonic() >= deadline
                        or (self._clock.monotonic() - self._started_mono) >= source_budget_s
                    ),
                )
                if recovered is not None:
                    return recovered
                if _is_transient_recording_poll(exc) and self._clock.monotonic() < deadline:
                    self._clock.sleep(max(0.01, poll_s))
                    continue
                raise
            progress = self._progress(recording)
            self._last_progress = progress
            if on_progress is not None:
                on_progress(progress)
            if progress.recording:
                started = True
                idle_polls = 0
            else:
                idle_polls += 1
                if self._interval_covered(progress):
                    self.completion_method = RecordingCompletionMethod.API_RECORDING_FALSE
                    return recording
                if started or idle_polls >= START_GRACE_POLLS:
                    # recording=false before end is not success; wait for replay clock or timeout.
                    if self._playback_reached_end():
                        self.completion_method = RecordingCompletionMethod.API_RECORDING_FALSE
                        return recording
            if self._clock.monotonic() >= deadline:
                recovered = self._recover_from_temp_output(
                    previous_bytes=stable_bytes,
                    stable_count=max(stable_count, TEMP_STABLE_POLLS),
                    near_deadline=True,
                )
                if recovered is not None:
                    return recovered
                self._safe_stop()
                raise ReplayError(
                    ReplayErrorCode.CAPTURE_TIMEOUT,
                    details={
                        "reason": "recording_did_not_finish",
                        "timeout_s": timeout_s,
                        "fraction": (
                            0.0 if self._last_progress is None else self._last_progress.fraction
                        ),
                        "api_dropout_count": self.api_dropout_count,
                    },
                )
            self._clock.sleep(max(0.01, poll_s))

    def _progress(self, recording: ReplayRecording) -> RecordingProgress:
        current = recording.currentTime
        span = self._end_s - self._start_s
        if current is None or span <= 0:
            fraction = 0.0 if current is None else 1.0
        else:
            fraction = (float(current) - self._start_s) / span
        return RecordingProgress(
            recording=bool(recording.recording),
            current_source_ms=None if current is None else int(round(float(current) * 1000.0)),
            fraction=min(1.0, max(0.0, fraction)),
        )

    def _interval_covered(self, progress: RecordingProgress) -> bool:
        if progress.current_source_ms is None:
            return False
        return progress.fraction >= 1.0 or (
            float(progress.current_source_ms) / 1000.0 >= self._end_s - PLAYBACK_END_TOLERANCE_S
        )

    def _playback_reached_end(self) -> bool:
        try:
            playback = self._client.get_playback()
        except ReplayError as exc:
            if _is_transient_recording_poll(exc):
                self.api_dropout_count += 1
                return False
            raise
        return float(playback.time) >= self._end_s - PLAYBACK_END_TOLERANCE_S

    def _safe_stop(self) -> None:
        try:
            self.stop()
        except ReplayError:
            return

    def _await_seek_landing(self, start_s: float) -> None:
        """Pause and seek until playback lands near ``start_s``."""
        self._client.set_playback(paused=True, time=float(start_s), readback=False)
        deadline = self._clock.monotonic() + SEEK_BEFORE_RECORD_TIMEOUT_S
        while self._clock.monotonic() < deadline:
            try:
                playback = self._client.get_playback()
            except ReplayError as exc:
                if _is_transient_recording_poll(exc):
                    self._clock.sleep(max(0.01, DEFAULT_POLL_INTERVAL_S))
                    continue
                raise
            if (not playback.seeking) and abs(float(playback.time) - float(start_s)) <= (
                SEEK_LANDING_TOLERANCE_S
            ):
                return
            self._clock.sleep(0.25)
        raise ReplayError(
            ReplayErrorCode.SEEK_FAILED,
            details={
                "reason": "capture_seek_timeout",
                "target_source_s": float(start_s),
                "timeout_s": SEEK_BEFORE_RECORD_TIMEOUT_S,
            },
        )

    def _recover_recording_after_start_timeout(self) -> ReplayRecording | None:
        """Retry GET /replay/recording briefly after a start-time read timeout."""
        for _ in range(START_GRACE_POLLS * 4):
            try:
                return self._client.get_recording()
            except ReplayError as exc:
                if not _is_transient_recording_poll(exc):
                    raise
                self.api_dropout_count += 1
                self._clock.sleep(max(0.01, DEFAULT_POLL_INTERVAL_S))
        return None

    def _recover_from_temp_output(
        self,
        *,
        previous_bytes: int | None,
        stable_count: int,
        near_deadline: bool,
    ) -> ReplayRecording | None:
        """Promote a stable ``*.webm.tmp`` only after the requested interval was covered.

        Size stability alone is not completion — promoting mid-encode truncates Mac captures.
        """
        if self._output_path is None:
            return None
        size = artifact_store.recorder_output_bytes(self._output_path)
        if size <= 0:
            return None
        if previous_bytes != size or stable_count < TEMP_STABLE_POLLS:
            return None
        covered = (
            self._last_progress is not None and self._interval_covered(self._last_progress)
        ) or self._playback_reached_end()
        if not covered and not near_deadline:
            return None
        promoted = artifact_store.promote_temp_recorder_output(self._output_path)
        path = str(promoted or self._output_path)
        self.temp_promotion_method = "stable_webm_tmp"
        if covered:
            self.completion_method = RecordingCompletionMethod.TEMP_STABLE_AFTER_END
            current = self._end_s
            last = self._last_progress
            if last is not None and last.current_source_ms is not None:
                current = float(last.current_source_ms) / 1000.0
        else:
            self.completion_method = RecordingCompletionMethod.TIMEOUT_TEMP_PROMOTE
            current = None
        return ReplayRecording(
            recording=False,
            path=path,
            currentTime=current,
            startTime=self._start_s,
            endTime=self._end_s,
        )


def _is_transient_recording_poll(exc: ReplayError) -> bool:
    """Timeouts and mid-encode connection drops are transient while a tmp file may exist."""
    if exc.code is not ReplayErrorCode.REPLAY_API_UNAVAILABLE:
        return False
    reason = str(exc.details.get("reason", ""))
    return reason in {"timeout", "http_error", "connect_failed"}


def run_capture(
    *,
    client: RecordingClient,
    clock: ClockMap,
    capture_id: str,
    start_game_ms: int,
    end_game_ms: int,
    directory: Path,
    mode: CaptureMode = CaptureMode.CLIP,
    fps: float | None = None,
    max_artifacts: int = DEFAULT_MAX_ARTIFACTS,
    lossless: bool = False,
    timeout_s: float = DEFAULT_CAPTURE_TIMEOUT_S,
    poll_s: float = DEFAULT_POLL_INTERVAL_S,
    cancel: threading.Event | None = None,
    on_progress: ProgressSink | None = None,
    sleep_clock: SleepClock | None = None,
    camera_framing: CameraFramingPlan | None = None,
    allow_capture_without_framing: bool = True,
    enforce_frame_rate: bool = True,
) -> CaptureResult:
    """Record one interval and return timestamped artifacts. Blocks; never touches the DB.

    When ``camera_framing`` is set (automated visual captures only), applies path+GST
    framing, re-applies after capture seek, then restores prior ``/replay/render``.

    A capture is COMPLETE only when the requested interval was covered and clip media
    (when applicable) probes to an acceptable duration. File existence alone is not enough.
    """
    framing_meta: CameraFramingMetadata | None = None
    saved_render: SavedRenderState | None = None
    active: RecordingClient = client
    coverage: CaptureCoverage | None = None
    try:
        if camera_framing is not None:
            framing_meta, saved_render, active = _prepare_framing(
                client,
                camera_framing,
                sleep_clock=sleep_clock,
                allow_without=allow_capture_without_framing,
            )
            if framing_meta is not None and framing_meta.status is CameraFramingStatus.APPLY_FAILED:
                if not allow_capture_without_framing:
                    raise ReplayError(
                        ReplayErrorCode.CAPTURE_RECORDING_FAILED,
                        details={
                            "reason": "camera_framing_apply_failed",
                            "error": framing_meta.placement_error,
                        },
                    )
                active = client
                saved_render = None
        validate_interval(start_game_ms, end_game_ms)
        settings = resolve_mode_settings(mode, fps, start_game_ms, end_game_ms)
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
        output = artifact_store.allocate_output_path(Path(directory), settings.codec)
        orchestrator = RecordingOrchestrator(active, clock=sleep_clock)
        _emit(on_progress, capture_id, CaptureStatus.RUNNING, 0.0, "recording_started", None)
        orchestrator.start(
            output,
            start_s=start_source_ms / 1000.0,
            end_s=end_source_ms / 1000.0,
            codec=settings.codec,
            fps=settings.fps,
            lossless=lossless,
            enforce_frame_rate=enforce_frame_rate,
        )
        try:
            orchestrator.wait_until_complete(
                timeout_s=timeout_s,
                poll_s=poll_s,
                cancel=cancel,
                on_progress=lambda sample: _emit(
                    on_progress,
                    capture_id,
                    CaptureStatus.RUNNING,
                    sample.fraction,
                    "recording",
                    sample.current_source_ms,
                ),
            )
        except ReplayError as wait_exc:
            # macOS may drop the API after writing clip.webm.tmp; promote only for verification.
            if wait_exc.code is ReplayErrorCode.CAPTURE_CANCELLED:
                raise
            promoted = artifact_store.promote_temp_recorder_output(output)
            if promoted is None:
                raise wait_exc
            orchestrator.temp_promotion_method = (
                orchestrator.temp_promotion_method or "wait_exception_temp_promote"
            )
            if wait_exc.code is ReplayErrorCode.CAPTURE_TIMEOUT:
                orchestrator.completion_method = RecordingCompletionMethod.TIMEOUT_TEMP_PROMOTE
            else:
                orchestrator.completion_method = (
                    RecordingCompletionMethod.WAIT_EXCEPTION_TEMP_PROMOTE
                )
            # Fall through: duration verification decides COMPLETE vs CAPTURE_TRUNCATED.
        else:
            artifact_store.promote_temp_recorder_output(output)
        if cancel is not None and cancel.is_set():
            raise ReplayError(
                ReplayErrorCode.CAPTURE_CANCELLED, details={"reason": "cancelled_after_recording"}
            )
        coverage = _verify_and_build_coverage(
            output_path=output,
            kind=settings.kind,
            start_game_ms=int(start_game_ms),
            end_game_ms=int(end_game_ms),
            orchestrator=orchestrator,
            api_fraction_complete=_last_fraction_complete(orchestrator),
        )
        if coverage.coverage_verdict is CaptureCoverageVerdict.TRUNCATED:
            raise ReplayError(
                ReplayErrorCode.CAPTURE_TRUNCATED,
                details={
                    "reason": "media_shorter_than_requested"
                    if coverage.actual_duration_ms is not None
                    else "unprobed_insufficient_evidence",
                    "requested_duration_ms": coverage.requested_duration_ms,
                    "actual_duration_ms": coverage.actual_duration_ms,
                    "min_acceptable_duration_ms": coverage.min_acceptable_duration_ms,
                    "requested_start_game_ms": coverage.requested_start_game_ms,
                    "requested_end_game_ms": coverage.requested_end_game_ms,
                    "actual_frame_count": coverage.actual_frame_count,
                    "completion_method": (
                        None
                        if coverage.completion_method is None
                        else coverage.completion_method.value
                    ),
                    "api_dropout_count": coverage.api_dropout_count,
                },
            )
        artifacts = frames.collect_artifacts(
            output_path=output,
            destination=Path(directory),
            kind=settings.kind,
            clock=clock,
            start_game_ms=int(start_game_ms),
            end_game_ms=int(end_game_ms),
            max_artifacts=_artifact_cap(mode, settings.expected_artifacts, max_artifacts),
            fps=settings.fps,
        )
    except ReplayError as exc:
        framing_meta = _restore_after_capture(client, camera_framing, saved_render, framing_meta)
        _cleanup_partials(Path(directory))
        cancelled = exc.code is ReplayErrorCode.CAPTURE_CANCELLED or (
            cancel is not None and cancel.is_set()
        )
        status = CaptureStatus.CANCELLED if cancelled else CaptureStatus.FAILED
        error = (
            ReplayError(ReplayErrorCode.CAPTURE_CANCELLED, details=exc.details)
            if cancelled and exc.code is not ReplayErrorCode.CAPTURE_CANCELLED
            else exc
        )
        _emit(on_progress, capture_id, status, 0.0, error.code.value, None)
        return CaptureResult(
            ok=False,
            capture_id=capture_id,
            status=status,
            error=error,
            camera_framing=framing_meta,
            capture_coverage=coverage if exc.code is ReplayErrorCode.CAPTURE_TRUNCATED else None,
        )
    framing_meta = _restore_after_capture(client, camera_framing, saved_render, framing_meta)
    _cleanup_output(Path(directory))
    _emit(on_progress, capture_id, CaptureStatus.COMPLETE, 1.0, "complete", end_source_ms)
    return CaptureResult(
        ok=True,
        capture_id=capture_id,
        status=CaptureStatus.COMPLETE,
        artifacts=artifacts,
        progress=CaptureProgress(
            capture_id=capture_id,
            status=CaptureStatus.COMPLETE,
            fraction=1.0,
            message="complete",
            current_source_ms=end_source_ms,
        ),
        camera_framing=framing_meta,
        capture_coverage=coverage,
    )


def _last_fraction_complete(orchestrator: RecordingOrchestrator) -> bool:
    progress = orchestrator._last_progress  # noqa: SLF001 - same module
    return progress is not None and progress.fraction >= 1.0


def _verify_and_build_coverage(
    *,
    output_path: Path,
    kind: str,
    start_game_ms: int,
    end_game_ms: int,
    orchestrator: RecordingOrchestrator,
    api_fraction_complete: bool,
) -> CaptureCoverage:
    """Probe clip duration. Caller raises ``CAPTURE_TRUNCATED`` when verdict is truncated."""
    requested = int(end_game_ms) - int(start_game_ms)
    min_ok = min_acceptable_capture_duration_ms(requested)
    method = orchestrator.completion_method
    temp_method = orchestrator.temp_promotion_method
    dropouts = int(orchestrator.api_dropout_count)
    if kind != ARTIFACT_KIND_CLIP:
        return CaptureCoverage(
            requested_start_game_ms=int(start_game_ms),
            requested_end_game_ms=int(end_game_ms),
            requested_duration_ms=requested,
            actual_duration_ms=None,
            actual_frame_count=None,
            coverage_verdict=CaptureCoverageVerdict.NOT_APPLICABLE,
            completion_method=method,
            temp_promotion_method=temp_method,
            api_dropout_count=dropouts,
            min_acceptable_duration_ms=min_ok,
        )
    probe = probe_clip_media(Path(output_path))
    if probe is None:
        # Placeholder / unreadable bytes: accept only when the API itself reported full coverage.
        if api_fraction_complete and method is RecordingCompletionMethod.API_RECORDING_FALSE:
            return CaptureCoverage(
                requested_start_game_ms=int(start_game_ms),
                requested_end_game_ms=int(end_game_ms),
                requested_duration_ms=requested,
                actual_duration_ms=None,
                actual_frame_count=None,
                coverage_verdict=CaptureCoverageVerdict.UNPROBED_API_COMPLETE,
                completion_method=method,
                temp_promotion_method=temp_method,
                api_dropout_count=dropouts,
                min_acceptable_duration_ms=min_ok,
            )
        return CaptureCoverage(
            requested_start_game_ms=int(start_game_ms),
            requested_end_game_ms=int(end_game_ms),
            requested_duration_ms=requested,
            actual_duration_ms=None,
            actual_frame_count=None,
            coverage_verdict=CaptureCoverageVerdict.TRUNCATED,
            completion_method=method,
            temp_promotion_method=temp_method,
            api_dropout_count=dropouts,
            min_acceptable_duration_ms=min_ok,
        )
    covered = capture_duration_covers(
        requested_duration_ms=requested, actual_duration_ms=probe.duration_ms
    )
    return CaptureCoverage(
        requested_start_game_ms=int(start_game_ms),
        requested_end_game_ms=int(end_game_ms),
        requested_duration_ms=requested,
        actual_duration_ms=probe.duration_ms,
        actual_frame_count=probe.frame_count,
        coverage_verdict=(
            CaptureCoverageVerdict.COVERED if covered else CaptureCoverageVerdict.TRUNCATED
        ),
        completion_method=method,
        temp_promotion_method=temp_method,
        api_dropout_count=dropouts,
        min_acceptable_duration_ms=min_ok,
    )


def _prepare_framing(
    client: RecordingClient,
    plan: CameraFramingPlan,
    *,
    sleep_clock: SleepClock | None,
    allow_without: bool,
) -> tuple[CameraFramingMetadata, SavedRenderState | None, RecordingClient]:
    """Apply framing or return APPLY_FAILED metadata. ``allow_without`` is for callers."""
    del allow_without
    render_client = cast(RenderClient, client)
    try:
        saved, meta = apply_framing(render_client, plan, clock=sleep_clock)
    except ReplayError as exc:
        failed = metadata_for_plan(
            plan,
            status=CameraFramingStatus.APPLY_FAILED,
            placement_error=str(exc),
        )
        return failed, None, client
    return meta, saved, FramingStickyClient(cast(FramingApiClient, client), plan)


def _restore_after_capture(
    client: RecordingClient,
    plan: CameraFramingPlan | None,
    saved: SavedRenderState | None,
    placed: CameraFramingMetadata | None,
) -> CameraFramingMetadata | None:
    """Restore prior render when framing was applied. Logs failures inside restore_framing."""
    if plan is None or saved is None or placed is None:
        return placed
    if not placed.camera_controlled:
        return placed
    return restore_framing(cast(RenderClient, client), saved, plan=plan, placed_meta=placed)


def total_bytes(artifacts: tuple[CaptureArtifactSpec, ...]) -> int:
    """Return the summed artifact size. Used for budget accounting."""
    return sum(item.bytes for item in artifacts)


def _artifact_cap(mode: CaptureMode, expected: int, requested: int) -> int:
    """STILL is capped at its expected frame count; other modes tolerate recorder overshoot."""
    if mode is CaptureMode.STILL:
        return max(1, min(int(requested), expected))
    return max(1, min(int(requested), expected * 4))


def _cleanup_output(directory: Path) -> None:
    """Remove the recorder staging directories, keeping renamed artifacts in place."""
    for name in (artifact_store.FRAMES_DIRNAME, "extracted"):
        staging = Path(directory) / name
        if staging.is_dir():
            artifact_store.delete_capture_dir(staging)


def _cleanup_partials(directory: Path) -> None:
    """Remove staging dirs and un-renamed recorder output so failures leave no partials."""
    _cleanup_output(directory)
    artifact_store.delete_files([Path(directory) / artifact_store.CLIP_FILENAME])


def _emit(
    sink: ProgressSink | None,
    capture_id: str,
    status: CaptureStatus,
    fraction: float,
    message: str,
    current_source_ms: int | None,
) -> None:
    if sink is None:
        return
    sink(
        CaptureProgress(
            capture_id=capture_id,
            status=status,
            fraction=fraction,
            message=message,
            current_source_ms=current_source_ms,
        )
    )
