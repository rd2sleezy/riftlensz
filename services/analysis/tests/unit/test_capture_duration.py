"""Deterministic capture-duration coverage / truncation tests (Mac Case D fix)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from riftlens.domain.capture import (
    CaptureCoverageVerdict,
    CaptureMode,
    CaptureStatus,
    RecordingCompletionMethod,
    capture_duration_covers,
    min_acceptable_capture_duration_ms,
)
from riftlens.domain.clock_map import ClockMap
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.api.models import ReplayRecording
from riftlens.replay_host.api.replay_client import ReplayApiClient
from riftlens.replay_host.capture import artifact_store
from riftlens.replay_host.capture.media_probe import probe_clip_media
from riftlens.replay_host.capture.recording import (
    TEMP_STABLE_POLLS,
    RecordingOrchestrator,
    run_capture,
)
from tests.fakes.fake_replay_runtime import FakeClock
from tests.fakes.fake_replay_server import FakeReplayApiServer, FakeReplayBehavior

_START_MS = 829_881
_END_MS = 846_881  # 17_000 ms — the real truncated Mac interval


def _clock() -> ClockMap:
    return ClockMap.identity(duration_ms=1_800_000)


def _client(server: FakeReplayApiServer) -> ReplayApiClient:
    return ReplayApiClient(
        server.origin,
        ca_file=str(server.ca_file),
        timeout_s=2.0,
        connect_timeout_s=1.0,
        max_retries=0,
    )


def _write_webm(path: Path, *, duration_s: float, fps: int = 10) -> None:
    import av

    target = Path(path)
    # League uses ``clip.webm.tmp``; PyAV needs a real ``.webm`` suffix to mux.
    write_path = target
    if target.suffix == ".tmp" or target.name.endswith(".webm.tmp"):
        write_path = target.with_name(target.name + ".mux.webm")
    frame_count = max(1, int(round(duration_s * fps)))
    frames = [
        np.zeros((64, 64, 3), dtype=np.uint8) + np.uint8(index % 32) for index in range(frame_count)
    ]
    container = av.open(str(write_path), mode="w")
    stream = container.add_stream("libvpx", rate=fps)
    stream.width = 64
    stream.height = 64
    stream.pix_fmt = "yuv420p"
    try:
        stream.bit_rate = 120_000
    except Exception:
        pass
    for image in frames:
        video_frame = av.VideoFrame.from_ndarray(image, format="rgb24")
        for packet in stream.encode(video_frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    if write_path != target:
        write_path.replace(target)


def test_min_acceptable_duration_rejects_case_d_short_clip() -> None:
    requested = 17_000
    min_ok = min_acceptable_capture_duration_ms(requested)
    assert min_ok >= 15_000
    assert (
        capture_duration_covers(requested_duration_ms=requested, actual_duration_ms=4_366) is False
    )
    assert (
        capture_duration_covers(requested_duration_ms=requested, actual_duration_ms=16_500) is True
    )


def test_full_requested_duration_completes(tmp_path: Path) -> None:
    behavior = FakeReplayBehavior(recording_instant=True, recording_write_output=False)
    with FakeReplayApiServer(behavior) as server:
        client = _client(server)
        output_dir = tmp_path / "cap"
        output_dir.mkdir()
        # Pre-create final path the fake would write; run_capture allocates clip.webm.
        # Intercept by writing a full-length webm after recording via monkeypatch-ish hook:
        real_start = RecordingOrchestrator.start

        def start_and_seed(self: RecordingOrchestrator, path: Path, **kwargs: Any) -> Any:
            result = real_start(self, path, **kwargs)
            _write_webm(path, duration_s=17.0)
            return result

        RecordingOrchestrator.start = start_and_seed  # type: ignore[method-assign]
        try:
            result = run_capture(
                client=client,
                clock=_clock(),
                capture_id="cap_full",
                start_game_ms=_START_MS,
                end_game_ms=_END_MS,
                directory=output_dir,
                mode=CaptureMode.CLIP,
                sleep_clock=FakeClock(),
            )
        finally:
            RecordingOrchestrator.start = real_start  # type: ignore[method-assign]
    assert result.ok is True
    assert result.status is CaptureStatus.COMPLETE
    assert result.capture_coverage is not None
    assert result.capture_coverage.coverage_verdict is CaptureCoverageVerdict.COVERED
    assert result.capture_coverage.requested_duration_ms == 17_000
    assert result.capture_coverage.actual_duration_ms is not None
    assert result.capture_coverage.actual_duration_ms >= 15_000


def test_short_existing_output_is_truncated(tmp_path: Path) -> None:
    behavior = FakeReplayBehavior(recording_instant=True, recording_write_output=False)
    with FakeReplayApiServer(behavior) as server:
        client = _client(server)
        output_dir = tmp_path / "cap"
        output_dir.mkdir()
        real_start = RecordingOrchestrator.start

        def start_and_seed(self: RecordingOrchestrator, path: Path, **kwargs: Any) -> Any:
            result = real_start(self, path, **kwargs)
            _write_webm(path, duration_s=4.366)
            return result

        RecordingOrchestrator.start = start_and_seed  # type: ignore[method-assign]
        try:
            result = run_capture(
                client=client,
                clock=_clock(),
                capture_id="cap_short",
                start_game_ms=_START_MS,
                end_game_ms=_END_MS,
                directory=output_dir,
                mode=CaptureMode.CLIP,
                sleep_clock=FakeClock(),
            )
        finally:
            RecordingOrchestrator.start = real_start  # type: ignore[method-assign]
    assert result.ok is False
    assert result.status is CaptureStatus.FAILED
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.CAPTURE_TRUNCATED
    assert result.capture_coverage is not None
    assert result.capture_coverage.coverage_verdict is CaptureCoverageVerdict.TRUNCATED
    assert result.error.details["requested_duration_ms"] == 17_000
    assert int(result.error.details["actual_duration_ms"]) < 5_000


def test_replay_end_then_encode_finalize_waits(tmp_path: Path) -> None:
    """recording=false early is ignored until playback/currentTime covers the interval."""
    behavior = FakeReplayBehavior(recording_poll_steps=4)
    output = tmp_path / "clip.webm"
    with FakeReplayApiServer(behavior) as server:
        client = _client(server)
        orchestrator = RecordingOrchestrator(client, clock=FakeClock())
        orchestrator.start(output, start_s=10.0, end_s=20.0, codec="webm", fps=30.0)
        # Force an early false reading once, then resume normal progress.
        calls = {"n": 0}
        real_get = client.get_recording

        def flaky() -> object:
            calls["n"] += 1
            if calls["n"] == 1:
                rec = real_get()
                return ReplayRecording(
                    recording=False,
                    path=rec.path,
                    currentTime=10.5,
                    startTime=10.0,
                    endTime=20.0,
                )
            return real_get()

        client.get_recording = flaky  # type: ignore[method-assign]
        final = orchestrator.wait_until_complete(timeout_s=30.0, poll_s=0.1)
    assert final.recording is False
    assert final.currentTime == pytest.approx(20.0)
    assert calls["n"] > 1
    assert orchestrator.completion_method is RecordingCompletionMethod.API_RECORDING_FALSE


def test_transient_recording_api_drop_recovers(tmp_path: Path) -> None:
    behavior = FakeReplayBehavior(recording_poll_steps=3)
    with FakeReplayApiServer(behavior) as server:
        client = _client(server)
        orchestrator = RecordingOrchestrator(client, clock=FakeClock())
        orchestrator.start(tmp_path / "clip.webm", start_s=1.0, end_s=2.0, codec="webm", fps=30.0)
        calls = {"n": 0}
        real_get = client.get_recording

        def flaky_get() -> object:
            calls["n"] += 1
            if calls["n"] <= 2:
                raise ReplayError(
                    ReplayErrorCode.REPLAY_API_UNAVAILABLE,
                    details={"reason": "timeout", "url": "/replay/recording"},
                )
            return real_get()

        client.get_recording = flaky_get  # type: ignore[method-assign]
        final = orchestrator.wait_until_complete(timeout_s=30.0, poll_s=0.1)
    assert final.recording is False
    assert orchestrator.api_dropout_count >= 2
    assert calls["n"] >= 3


def test_timeout_with_sufficient_finalized_media_completes(tmp_path: Path) -> None:
    behavior = FakeReplayBehavior(recording_poll_steps=50)
    behavior.time_frozen = True
    behavior.playback["time"] = 1.0
    with FakeReplayApiServer(behavior) as server:
        client = _client(server)
        output_dir = tmp_path / "cap"
        output_dir.mkdir()

        def always_timeout() -> object:
            raise ReplayError(
                ReplayErrorCode.REPLAY_API_UNAVAILABLE,
                details={"reason": "timeout", "url": "/replay/recording"},
            )

        real_start = RecordingOrchestrator.start

        def start_seed(self: RecordingOrchestrator, path: Path, **kwargs: Any) -> Any:
            result = real_start(self, path, **kwargs)
            _write_webm(Path(str(path) + ".tmp"), duration_s=17.0)
            self._client.get_recording = always_timeout  # type: ignore[method-assign]
            return result

        RecordingOrchestrator.start = start_seed  # type: ignore[method-assign]
        try:
            result = run_capture(
                client=client,
                clock=_clock(),
                capture_id="cap_evidence",
                start_game_ms=_START_MS,
                end_game_ms=_END_MS,
                directory=output_dir,
                mode=CaptureMode.CLIP,
                timeout_s=1.0,
                poll_s=0.1,
                sleep_clock=FakeClock(),
            )
        finally:
            RecordingOrchestrator.start = real_start  # type: ignore[method-assign]
    assert result.ok is True
    assert result.capture_coverage is not None
    assert result.capture_coverage.coverage_verdict is CaptureCoverageVerdict.COVERED
    assert result.capture_coverage.api_dropout_count >= TEMP_STABLE_POLLS


def test_tmp_with_insufficient_duration_does_not_succeed(tmp_path: Path) -> None:
    behavior = FakeReplayBehavior(recording_poll_steps=50)
    behavior.time_frozen = True
    behavior.playback["time"] = 1.0
    with FakeReplayApiServer(behavior) as server:
        client = _client(server)
        output_dir = tmp_path / "cap"
        output_dir.mkdir()

        def always_timeout() -> object:
            raise ReplayError(
                ReplayErrorCode.REPLAY_API_UNAVAILABLE,
                details={"reason": "timeout", "url": "/replay/recording"},
            )

        real_start = RecordingOrchestrator.start

        def start_seed(self: RecordingOrchestrator, path: Path, **kwargs: Any) -> Any:
            result = real_start(self, path, **kwargs)
            _write_webm(Path(str(path) + ".tmp"), duration_s=4.366)
            self._client.get_recording = always_timeout  # type: ignore[method-assign]
            return result

        RecordingOrchestrator.start = start_seed  # type: ignore[method-assign]
        try:
            result = run_capture(
                client=client,
                clock=_clock(),
                capture_id="cap_tmp_short",
                start_game_ms=_START_MS,
                end_game_ms=_END_MS,
                directory=output_dir,
                mode=CaptureMode.CLIP,
                timeout_s=1.0,
                poll_s=0.1,
                sleep_clock=FakeClock(),
            )
        finally:
            RecordingOrchestrator.start = real_start  # type: ignore[method-assign]
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.CAPTURE_TRUNCATED


def test_file_duration_stabilizes_finalize_once(tmp_path: Path) -> None:
    path = tmp_path / "clip.webm"
    _write_webm(path, duration_s=2.0)
    first = probe_clip_media(path)
    second = probe_clip_media(path)
    assert first is not None and second is not None
    assert first.duration_ms == second.duration_ms
    assert first.duration_ms >= 1_500


def test_timeout_with_short_media_fails(tmp_path: Path) -> None:
    behavior = FakeReplayBehavior(recording_poll_steps=50)
    behavior.time_frozen = True
    behavior.playback["time"] = 1.0
    with FakeReplayApiServer(behavior) as server:
        client = _client(server)
        output_dir = tmp_path / "cap"
        output_dir.mkdir()

        def always_timeout() -> object:
            raise ReplayError(
                ReplayErrorCode.REPLAY_API_UNAVAILABLE,
                details={"reason": "timeout", "url": "/replay/recording"},
            )

        real_start = RecordingOrchestrator.start

        def start_seed(self: RecordingOrchestrator, path: Path, **kwargs: Any) -> Any:
            result = real_start(self, path, **kwargs)
            _write_webm(Path(str(path) + ".tmp"), duration_s=1.0)
            self._client.get_recording = always_timeout  # type: ignore[method-assign]
            return result

        RecordingOrchestrator.start = start_seed  # type: ignore[method-assign]
        try:
            result = run_capture(
                client=client,
                clock=_clock(),
                capture_id="cap_timeout_short",
                start_game_ms=_START_MS,
                end_game_ms=_END_MS,
                directory=output_dir,
                mode=CaptureMode.CLIP,
                timeout_s=1.0,
                poll_s=0.1,
                sleep_clock=FakeClock(),
            )
        finally:
            RecordingOrchestrator.start = real_start  # type: ignore[method-assign]
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.CAPTURE_TRUNCATED


def test_case_d_17s_request_4_4s_actual_fails(tmp_path: Path) -> None:
    """Exact discovered bug shape: requested 17s, media ~4.4s must not be COMPLETE."""
    behavior = FakeReplayBehavior(recording_instant=True, recording_write_output=False)
    with FakeReplayApiServer(behavior) as server:
        client = _client(server)
        output_dir = tmp_path / "cap"
        output_dir.mkdir()
        real_start = RecordingOrchestrator.start

        def start_and_seed(self: RecordingOrchestrator, path: Path, **kwargs: Any) -> Any:
            result = real_start(self, path, **kwargs)
            _write_webm(path, duration_s=4.366, fps=30)
            return result

        RecordingOrchestrator.start = start_and_seed  # type: ignore[method-assign]
        try:
            result = run_capture(
                client=client,
                clock=_clock(),
                capture_id="cap_case_d",
                start_game_ms=829_881,
                end_game_ms=846_881,
                directory=output_dir,
                mode=CaptureMode.CLIP,
                sleep_clock=FakeClock(),
            )
        finally:
            RecordingOrchestrator.start = real_start  # type: ignore[method-assign]
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.CAPTURE_TRUNCATED
    assert result.capture_coverage is not None
    assert result.capture_coverage.requested_duration_ms == 17_000
    assert result.capture_coverage.actual_duration_ms is not None
    assert abs(result.capture_coverage.actual_duration_ms - 4_366) < 500


def test_ordinary_no_framing_capture_still_works(tmp_path: Path) -> None:
    behavior = FakeReplayBehavior(recording_instant=True)
    with FakeReplayApiServer(behavior) as server:
        result = run_capture(
            client=_client(server),
            clock=_clock(),
            capture_id="cap_plain",
            start_game_ms=1_110_000,
            end_game_ms=1_135_000,
            directory=tmp_path,
            mode=CaptureMode.CLIP,
            sleep_clock=FakeClock(),
        )
    assert result.ok is True
    assert result.camera_framing is None
    assert result.capture_coverage is not None
    assert result.capture_coverage.coverage_verdict is CaptureCoverageVerdict.UNPROBED_API_COMPLETE


def test_promote_helper_still_renames(tmp_path: Path) -> None:
    final = tmp_path / "clip.webm"
    Path(str(final) + ".tmp").write_bytes(b"abc")
    assert artifact_store.promote_temp_recorder_output(final) == final
