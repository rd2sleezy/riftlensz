"""``/replay/recording`` choreography and the synchronous capture engine (§7.1)."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from riftlens.domain.capture import (
    DEFAULT_CAPTURE_POLL_S,
    DEFAULT_CAPTURE_TIMEOUT_S,
    DEFAULT_MAX_ARTIFACTS,
    CaptureArtifactSpec,
    CaptureMode,
    CaptureProgress,
    CaptureResult,
    CaptureStatus,
    resolve_mode_settings,
    validate_interval,
)
from riftlens.domain.clock_map import ClockMap
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.api.models import ReplayPlayback, ReplayRecording
from riftlens.replay_host.capture import artifact_store, frames
from riftlens.replay_host.timing import SleepClock, WallClock

DEFAULT_POLL_INTERVAL_S = DEFAULT_CAPTURE_POLL_S
START_GRACE_POLLS = 3

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

    def start(
        self,
        path: Path,
        *,
        start_s: float,
        end_s: float,
        codec: str,
        fps: float,
        lossless: bool = False,
    ) -> ReplayRecording:
        """Seek to ``start_s``, unpause, then POST ``recording=true``. Times are source seconds."""
        self._start_s = float(start_s)
        self._end_s = float(end_s)
        self._client.set_playback(paused=False, time=float(start_s))
        return self._client.set_recording(
            {
                "recording": True,
                "codec": codec,
                "path": str(path),
                "startTime": float(start_s),
                "endTime": float(end_s),
                "framesPerSecond": float(fps),
                "enforceFrameRate": True,
                "lossless": bool(lossless),
            }
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
        """Poll until the client reports ``recording=false``. Raises typed capture errors."""
        deadline = self._clock.monotonic() + max(0.0, timeout_s)
        started = False
        idle_polls = 0
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
                raise
            progress = self._progress(recording)
            if on_progress is not None:
                on_progress(progress)
            if progress.recording:
                started = True
            else:
                idle_polls += 1
                if started or idle_polls >= START_GRACE_POLLS or self._reached_end(progress):
                    return recording
            if self._clock.monotonic() >= deadline:
                self._safe_stop()
                raise ReplayError(
                    ReplayErrorCode.CAPTURE_TIMEOUT,
                    details={
                        "reason": "recording_did_not_finish",
                        "timeout_s": timeout_s,
                        "fraction": progress.fraction,
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

    def _reached_end(self, progress: RecordingProgress) -> bool:
        return progress.current_source_ms is not None and progress.fraction >= 1.0

    def _safe_stop(self) -> None:
        try:
            self.stop()
        except ReplayError:
            return


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
) -> CaptureResult:
    """Record one interval and return timestamped artifacts. Blocks; never touches the DB."""
    try:
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
        orchestrator = RecordingOrchestrator(client, clock=sleep_clock)
        _emit(on_progress, capture_id, CaptureStatus.RUNNING, 0.0, "recording_started", None)
        orchestrator.start(
            output,
            start_s=start_source_ms / 1000.0,
            end_s=end_source_ms / 1000.0,
            codec=settings.codec,
            fps=settings.fps,
            lossless=lossless,
        )
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
        if cancel is not None and cancel.is_set():
            raise ReplayError(
                ReplayErrorCode.CAPTURE_CANCELLED, details={"reason": "cancelled_after_recording"}
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
        return CaptureResult(ok=False, capture_id=capture_id, status=status, error=error)
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
    )


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
