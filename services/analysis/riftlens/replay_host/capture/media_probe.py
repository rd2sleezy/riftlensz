"""Probe recorder clip duration/frame count. Capture-local; not the VOD ingest probe."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ClipMediaProbe:
    """Decoded container summary for one recorder clip."""

    duration_ms: int
    frame_count: int | None
    width: int | None
    height: int | None


def probe_clip_media(path: Path) -> ClipMediaProbe | None:
    """Return duration/frames for a readable video file, else None for placeholders."""
    target = Path(path)
    if not target.is_file() or target.stat().st_size <= 0:
        return None
    try:
        import av
    except ImportError:
        return None
    try:
        with av.open(str(target)) as container:
            if not container.streams.video:
                return None
            stream = container.streams.video[0]
            duration_s = _container_duration_s(container, stream)
            frame_count = stream.frames if stream.frames and stream.frames > 0 else None
            if duration_s is None or duration_s <= 0 or frame_count is None:
                decoded_ms, decoded_frames = _decode_metrics(container, stream)
                if duration_s is None or duration_s <= 0:
                    duration_s = None if decoded_ms is None else decoded_ms / 1000.0
                if frame_count is None:
                    frame_count = decoded_frames
            if duration_s is None or duration_s <= 0:
                return None
            return ClipMediaProbe(
                duration_ms=max(0, int(round(duration_s * 1000.0))),
                frame_count=frame_count,
                width=int(stream.width) if stream.width else None,
                height=int(stream.height) if stream.height else None,
            )
    except Exception:  # noqa: BLE001 - unreadable fake/placeholder bytes are expected
        return None


def _container_duration_s(container: object, stream: object) -> float | None:
    duration = getattr(container, "duration", None)
    if duration is not None and int(duration) > 0:
        return float(duration) / 1_000_000.0
    stream_duration = getattr(stream, "duration", None)
    time_base = getattr(stream, "time_base", None)
    if stream_duration is not None and time_base is not None and int(stream_duration) > 0:
        return float(stream_duration) * float(time_base)
    return None


def _decode_metrics(container: object, stream: object) -> tuple[float | None, int | None]:
    time_base = float(getattr(stream, "time_base", 0) or 0) or 0.0
    last_ms = 0.0
    count = 0
    decode = getattr(container, "decode", None)
    if decode is None:
        return None, None
    try:
        for frame in decode(stream):
            count += 1
            pts = getattr(frame, "pts", None)
            if pts is None or time_base <= 0:
                continue
            last_ms = max(last_ms, float(pts) * time_base * 1000.0)
    except Exception:  # noqa: BLE001
        pass
    duration_ms = None if last_ms <= 0 else last_ms
    frames = None if count <= 0 else count
    return duration_ms, frames
