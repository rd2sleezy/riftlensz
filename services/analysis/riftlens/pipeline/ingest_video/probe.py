from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from riftlens.adapters.ffmpeg.ffprobe import FfprobeError, run_ffprobe

_CHUNK_BYTES = 8 * 1024 * 1024
_MIN_WIDTH = 1280
_MIN_HEIGHT = 720
_MIN_DURATION_S = 5 * 60
_ASPECT_LO = 1.7
_ASPECT_HI = 2.4
_PLAYABLE_CODECS = frozenset({"h264", "avc1"})
_PLAYABLE_PIX_FMTS = frozenset({"yuv420p"})


class MediaProbeError(ValueError):
    """User-facing probe / validation failure."""


class HandlingDecision(StrEnum):
    USE_IN_PLACE = "use_in_place"
    REMUX_FASTSTART = "remux_faststart"
    TRANSCODE = "transcode"
    REJECT = "reject"


@dataclass(frozen=True)
class MediaProbe:
    """ffprobe (or PyAV fallback) snapshot. Times from the container, not frame index."""

    path: str
    width: int
    height: int
    codec_name: str
    pix_fmt: str
    r_frame_rate: str
    avg_frame_rate: str
    duration_s: float
    start_time_s: float
    nb_frames: int | None
    bit_rate: int | None
    size_bytes: int
    has_faststart: bool
    content_hash: str

    @property
    def duration_ms(self) -> int:
        """Return duration in integer milliseconds."""
        return max(0, int(round(self.duration_s * 1000.0)))

    @property
    def aspect_ratio(self) -> float:
        """Return width/height. Assumes height is positive."""
        return self.width / max(1, self.height)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready mapping for IPC / API."""
        return {
            "path": self.path,
            "width": self.width,
            "height": self.height,
            "codec_name": self.codec_name,
            "pix_fmt": self.pix_fmt,
            "r_frame_rate": self.r_frame_rate,
            "avg_frame_rate": self.avg_frame_rate,
            "duration_s": self.duration_s,
            "duration_ms": self.duration_ms,
            "start_time_s": self.start_time_s,
            "nb_frames": self.nb_frames,
            "bit_rate": self.bit_rate,
            "size_bytes": self.size_bytes,
            "has_faststart": self.has_faststart,
            "content_hash": self.content_hash,
            "aspect_ratio": self.aspect_ratio,
        }


def probe(path: str | Path) -> MediaProbe:
    """Probe a video file. Assumes ``path`` is a user-supplied filesystem path."""
    resolved = Path(path).expanduser()
    if not resolved.is_file():
        raise MediaProbeError(f"Video file not found: {resolved}")
    size_bytes = resolved.stat().st_size
    if size_bytes <= 0:
        raise MediaProbeError(f"Video file is empty: {resolved}")
    raw = _read_container(resolved)
    video = _video_stream(raw)
    fmt = raw.get("format") if isinstance(raw.get("format"), Mapping) else {}
    width = _as_int(video.get("width"), 0)
    height = _as_int(video.get("height"), 0)
    if width <= 0 or height <= 0:
        raise MediaProbeError("Video has no usable width/height.")
    duration_s = _duration_s(video, fmt if isinstance(fmt, Mapping) else {})
    start_time_s = _as_float(video.get("start_time"), _as_float(
        fmt.get("start_time") if isinstance(fmt, Mapping) else None, 0.0
    ))
    return MediaProbe(
        path=str(resolved),
        width=width,
        height=height,
        codec_name=str(video.get("codec_name") or ""),
        pix_fmt=str(video.get("pix_fmt") or ""),
        r_frame_rate=str(video.get("r_frame_rate") or ""),
        avg_frame_rate=str(video.get("avg_frame_rate") or ""),
        duration_s=duration_s,
        start_time_s=start_time_s,
        nb_frames=_optional_int(video.get("nb_frames")),
        bit_rate=_optional_int(
            video.get("bit_rate")
            or (fmt.get("bit_rate") if isinstance(fmt, Mapping) else None)
        ),
        size_bytes=size_bytes,
        has_faststart=_moov_before_mdat(resolved),
        content_hash=content_hash(resolved),
    )


def content_hash(path: str | Path) -> str:
    """Return sha256 of ``size || first 8MB || last 8MB``. Assumes the file exists."""
    resolved = Path(path)
    size = resolved.stat().st_size
    digest = hashlib.sha256()
    digest.update(str(size).encode("ascii"))
    with resolved.open("rb") as handle:
        digest.update(handle.read(_CHUNK_BYTES))
        if size > _CHUNK_BYTES:
            handle.seek(max(0, size - _CHUNK_BYTES))
            digest.update(handle.read(_CHUNK_BYTES))
    return digest.hexdigest()


def validate_probe(media: MediaProbe) -> list[str]:
    """Return specific ingest validation errors. Empty means the file may be ingested."""
    errors: list[str] = []
    if media.width < _MIN_WIDTH or media.height < _MIN_HEIGHT:
        errors.append(
            f"Video is below {_MIN_WIDTH}x{_MIN_HEIGHT} "
            f"(got {media.width}x{media.height})."
        )
    aspect = media.aspect_ratio
    if aspect < _ASPECT_LO or aspect > _ASPECT_HI:
        errors.append(
            f"Aspect ratio {aspect:.3f} is outside [{_ASPECT_LO}, {_ASPECT_HI}]."
        )
    if media.duration_s < _MIN_DURATION_S:
        errors.append(
            f"Duration is under 5 minutes (got {media.duration_s:.1f}s)."
        )
    return errors


def decide_handling(media: MediaProbe) -> HandlingDecision:
    """Route a probed file to in-place / remux / transcode / reject."""
    if validate_probe(media):
        return HandlingDecision.REJECT
    codec = media.codec_name.lower()
    pix = media.pix_fmt.lower()
    playable = codec in _PLAYABLE_CODECS and (pix in _PLAYABLE_PIX_FMTS or pix == "")
    if playable and media.has_faststart:
        return HandlingDecision.USE_IN_PLACE
    if playable:
        return HandlingDecision.REMUX_FASTSTART
    return HandlingDecision.TRANSCODE


def chromium_playable(media: MediaProbe) -> bool:
    """Return True when Chromium can likely play the file without transcode."""
    codec = media.codec_name.lower()
    pix = media.pix_fmt.lower()
    return codec in _PLAYABLE_CODECS and (pix in _PLAYABLE_PIX_FMTS or pix == "")


def _read_container(path: Path) -> Mapping[str, Any]:
    try:
        return run_ffprobe(str(path))
    except FfprobeError:
        return _probe_with_pyav(path)


def _probe_with_pyav(path: Path) -> dict[str, Any]:
    try:
        import av
    except ImportError as exc:  # pragma: no cover - av is a declared dependency
        raise MediaProbeError(
            f"Cannot read video metadata (ffprobe missing and PyAV unavailable): {path}"
        ) from exc
    try:
        container = av.open(str(path))
    except Exception as exc:
        raise MediaProbeError(f"Invalid or unreadable video file: {path}") from exc
    try:
        stream = next((item for item in container.streams.video), None)
        if stream is None:
            raise MediaProbeError(f"No video stream in file: {path}")
        duration_s = _pyav_duration_s(container, stream)
        start_time_s = 0.0
        if stream.start_time is not None and stream.time_base is not None:
            start_time_s = float(stream.start_time * stream.time_base)
        nb_frames = int(stream.frames) if stream.frames else None
        bit_rate = int(stream.bit_rate) if stream.bit_rate else None
        fmt_bit_rate = int(container.bit_rate) if container.bit_rate else None
        codec = stream.codec_context.name if stream.codec_context else ""
        pix_fmt = str(getattr(stream.codec_context, "pix_fmt", "") or "")
        rate = stream.average_rate or stream.base_rate
        rate_s = f"{rate.numerator}/{rate.denominator}" if rate is not None else "0/1"
        return {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": codec,
                    "pix_fmt": pix_fmt,
                    "width": int(stream.width or 0),
                    "height": int(stream.height or 0),
                    "r_frame_rate": rate_s,
                    "avg_frame_rate": rate_s,
                    "duration": str(duration_s),
                    "start_time": str(start_time_s),
                    "nb_frames": None if nb_frames is None else str(nb_frames),
                    "bit_rate": None if bit_rate is None else str(bit_rate),
                }
            ],
            "format": {
                "duration": str(duration_s),
                "start_time": str(start_time_s),
                "bit_rate": None if fmt_bit_rate is None else str(fmt_bit_rate),
                "format_name": container.format.name if container.format else "",
                "tags": dict(container.metadata or {}),
            },
        }
    finally:
        container.close()


def _pyav_duration_s(container: object, stream: object) -> float:
    duration = getattr(container, "duration", None)
    if duration is not None:
        return max(0.0, float(duration) / 1_000_000.0)
    stream_duration = getattr(stream, "duration", None)
    time_base = getattr(stream, "time_base", None)
    if stream_duration is not None and time_base is not None:
        return max(0.0, float(stream_duration * time_base))
    return 0.0


def _video_stream(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    streams = raw.get("streams")
    if not isinstance(streams, list):
        raise MediaProbeError("Probe output has no streams.")
    for stream in streams:
        if isinstance(stream, Mapping) and stream.get("codec_type") == "video":
            return stream
    raise MediaProbeError("No video stream found in file.")


def _duration_s(video: Mapping[str, Any], fmt: Mapping[str, Any]) -> float:
    for candidate in (video.get("duration"), fmt.get("duration")):
        value = _as_float(candidate, -1.0)
        if value >= 0.0:
            return value
    return 0.0


def _moov_before_mdat(path: Path) -> bool:
    """Return True when a ``moov`` atom appears before ``mdat`` in the file head."""
    with path.open("rb") as handle:
        head = handle.read(512 * 1024)
    moov = head.find(b"moov")
    mdat = head.find(b"mdat")
    if moov < 0:
        return False
    if mdat < 0:
        return True
    return moov < mdat


def _as_int(value: object, default: int) -> int:
    try:
        if value is None or value == "N/A":
            return default
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _optional_int(value: object) -> int | None:
    if value is None or value == "N/A" or value == "":
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _as_float(value: object, default: float) -> float:
    try:
        if value is None or value == "N/A":
            return default
        return float(str(value))
    except (TypeError, ValueError):
        return default
