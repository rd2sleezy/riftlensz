"""PTS sparse video reader tests (H.9.1)."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pytest
from riftlens.pipeline.ingest_video.reader import VideoReaderError, iter_samples


def _write_cfr(
    path: Path, *, seconds: float = 2.0, fps: int = 30, start_offset_s: float = 0.0
) -> None:
    total = int(round(seconds * fps))
    container = av.open(str(path), mode="w")
    stream = container.add_stream("libx264", rate=fps)
    stream.width = 320
    stream.height = 240
    stream.pix_fmt = "yuv420p"
    stream.time_base = Fraction(1, fps)
    stream.codec_context.options = {"crf": "28", "preset": "ultrafast"}
    start_pts = int(round(start_offset_s * fps)) if start_offset_s > 0 else 0
    for index in range(total):
        frame = av.VideoFrame.from_ndarray(
            np.zeros((240, 320, 3), dtype=np.uint8), format="rgb24"
        )
        frame = frame.reformat(format="yuv420p")
        frame.pts = start_pts + index
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()


def _write_vfr(path: Path) -> None:
    """Variable inter-frame gaps via irregular PTS."""
    container = av.open(str(path), mode="w")
    stream = container.add_stream("libx264", rate=25)
    stream.width = 320
    stream.height = 240
    stream.pix_fmt = "yuv420p"
    stream.codec_context.options = {"crf": "28", "preset": "ultrafast"}
    # Irregular PTS steps (in stream time_base units; rate=25 → 1 frame = 1 unit often).
    pts_list = [0, 1, 2, 4, 7, 11, 12, 20, 21, 22]
    for pts in pts_list:
        frame = av.VideoFrame.from_ndarray(
            np.full((240, 320, 3), 40, dtype=np.uint8), format="rgb24"
        )
        frame = frame.reformat(format="yuv420p")
        frame.pts = pts
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()


def test_iter_samples_cfr_monotonic(tmp_path: Path) -> None:
    path = tmp_path / "cfr.mp4"
    _write_cfr(path, seconds=2.0, fps=30)
    samples = list(iter_samples(path, hz=5.0))
    assert len(samples) >= 8
    times = [item.t_video_ms for item in samples]
    assert times == sorted(times)
    assert all(isinstance(t, int) for t in times)
    # Cadence roughly 200 ms.
    if len(times) >= 3:
        deltas = [times[i + 1] - times[i] for i in range(len(times) - 1)]
        assert min(deltas) >= 0
        assert max(deltas) <= 500


def test_iter_samples_timestamp_near_target(tmp_path: Path) -> None:
    path = tmp_path / "cfr2.mp4"
    _write_cfr(path, seconds=1.0, fps=25)
    samples = list(iter_samples(path, hz=2.0, max_samples=3))
    assert samples
    # First sample near 0.
    assert samples[0].t_video_ms <= 80


def test_iter_samples_vfr_does_not_crash(tmp_path: Path) -> None:
    path = tmp_path / "vfr.mp4"
    _write_vfr(path)
    samples = list(iter_samples(path, hz=2.0, max_samples=5))
    assert samples
    times = [item.t_video_ms for item in samples]
    assert times == sorted(times)


def test_iter_samples_nonzero_start(tmp_path: Path) -> None:
    path = tmp_path / "offset.mp4"
    _write_cfr(path, seconds=1.0, fps=20, start_offset_s=1.0)
    samples = list(iter_samples(path, hz=2.0, max_samples=3))
    assert samples
    # Normalized against stream start → near-zero first sample.
    assert samples[0].t_video_ms < 250


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(VideoReaderError, match="not found"):
        list(iter_samples(tmp_path / "nope.mp4"))


def test_invalid_hz_raises(tmp_path: Path) -> None:
    path = tmp_path / "cfr.mp4"
    _write_cfr(path, seconds=0.5, fps=10)
    with pytest.raises(VideoReaderError, match="hz"):
        list(iter_samples(path, hz=0))
