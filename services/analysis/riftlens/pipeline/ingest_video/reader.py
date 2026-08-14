"""PTS-based sparse video frame sampler for H.9.1 clock OCR.

``t_video_ms`` is always derived from presentation timestamps normalized against
the stream start time — never from frame index.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import av
import numpy as np
from numpy.typing import NDArray

BgrFrame = NDArray[np.uint8]


@dataclass(frozen=True)
class SampledVideoFrame:
    """One decoded frame with its presentation timestamp in integer ms."""

    t_video_ms: int
    frame: BgrFrame  # HxWx3 BGR uint8


class VideoReaderError(ValueError):
    """Unreadable or unsupported video for sparse sampling."""


def iter_samples(
    path: str | Path,
    *,
    hz: float = 1.0,
    max_samples: int | None = None,
) -> Iterator[SampledVideoFrame]:
    """Yield BGR frames at approximately ``hz`` samples per second.

    Seeks near each target PTS then decodes forward. Assumes ``hz > 0``.
    """
    if hz <= 0:
        raise VideoReaderError("hz must be positive")
    resolved = Path(path).expanduser()
    if not resolved.is_file():
        raise VideoReaderError(f"Video file not found: {resolved}")

    container = av.open(str(resolved))
    try:
        stream = _video_stream(container)
        time_base = _time_base(stream)
        start_pts = int(stream.start_time or 0)
        end_ms = _end_ms(container, stream, start_pts=start_pts, time_base=time_base)
        if end_ms <= 0:
            raise VideoReaderError("Video duration is not positive")

        interval_ms = max(1, int(round(1000.0 / float(hz))))
        emitted = 0
        target_ms = 0
        while target_ms <= end_ms:
            if max_samples is not None and emitted >= max_samples:
                break
            frame = _decode_near(
                container, stream, target_ms=target_ms, start_pts=start_pts, time_base=time_base
            )
            if frame is not None:
                yield frame
                emitted += 1
            target_ms += interval_ms
    finally:
        container.close()


def _video_stream(container: Any) -> Any:
    for stream in container.streams.video:
        return stream
    raise VideoReaderError("No video stream found")


def _time_base(stream: Any) -> Fraction:
    raw = stream.time_base
    if raw is None:
        raise VideoReaderError("Video stream has no usable time_base")
    return Fraction(raw.numerator, raw.denominator)


def _end_ms(container: Any, stream: Any, *, start_pts: int, time_base: Fraction) -> int:
    duration_pts = stream.duration
    if duration_pts is not None and int(duration_pts) > 0:
        return _pts_to_ms(start_pts + int(duration_pts), start_pts=start_pts, time_base=time_base)
    if container.duration is not None and int(container.duration) > 0:
        duration_s = float(container.duration) / 1_000_000.0
        end_ms = int(round(duration_s * 1000.0))
        # Some WebM captures advertise a bogus microsecond-scale duration.
        if end_ms >= 50:
            return end_ms
    scanned = _scan_duration_ms(container, stream, start_pts=start_pts, time_base=time_base)
    if scanned > 0:
        return scanned
    raise VideoReaderError("Video duration is not positive")


def _scan_duration_ms(
    container: Any, stream: Any, *, start_pts: int, time_base: Fraction
) -> int:
    """Last-resort duration: demux packets and take the max presentation time."""
    max_ms = 0
    try:
        container.seek(0, stream=stream, any_frame=False, backward=True)
    except av.error.FFmpegError:
        return 0
    for packet in container.demux(stream):
        pts = packet.pts
        if pts is None:
            continue
        max_ms = max(max_ms, _pts_to_ms(int(pts), start_pts=start_pts, time_base=time_base))
    return max_ms


def _pts_to_ms(pts: int, *, start_pts: int, time_base: Fraction) -> int:
    relative = pts - start_pts
    seconds = float(relative * time_base)
    return max(0, int(round(seconds * 1000.0)))


def _ms_to_pts(t_video_ms: int, *, start_pts: int, time_base: Fraction) -> int:
    seconds = float(t_video_ms) / 1000.0
    offset = int(round(seconds / float(time_base)))
    return start_pts + offset


def _decode_near(
    container: Any,
    stream: Any,
    *,
    target_ms: int,
    start_pts: int,
    time_base: Fraction,
) -> SampledVideoFrame | None:
    target_pts = _ms_to_pts(target_ms, start_pts=start_pts, time_base=time_base)
    try:
        container.seek(target_pts, stream=stream, any_frame=False, backward=True)
    except av.error.FFmpegError:
        try:
            container.seek(0, stream=stream, any_frame=False, backward=True)
        except av.error.FFmpegError:
            return None

    best: SampledVideoFrame | None = None
    best_delta = 10**12
    for packet in container.demux(stream):
        for frame in packet.decode():
            if frame.pts is None:
                continue
            t_ms = _pts_to_ms(int(frame.pts), start_pts=start_pts, time_base=time_base)
            delta = abs(t_ms - target_ms)
            if delta < best_delta:
                arr = frame.to_ndarray(format="bgr24")
                best = SampledVideoFrame(t_video_ms=t_ms, frame=arr)
                best_delta = delta
            if t_ms >= target_ms + 100:
                return best
        if best is not None and best.t_video_ms >= target_ms and best_delta <= 100:
            return best
    return best
