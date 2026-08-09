from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from riftlens.pipeline.ingest_video.probe import (
    HandlingDecision,
    MediaProbe,
    MediaProbeError,
    chromium_playable,
    content_hash,
    decide_handling,
    probe,
    validate_probe,
)


def _probe(
    *,
    width: int = 1920,
    height: int = 1080,
    codec: str = "h264",
    pix: str = "yuv420p",
    duration_s: float = 600.0,
    faststart: bool = True,
) -> MediaProbe:
    return MediaProbe(
        path="/tmp/fake.mp4",
        width=width,
        height=height,
        codec_name=codec,
        pix_fmt=pix,
        r_frame_rate="60/1",
        avg_frame_rate="60/1",
        duration_s=duration_s,
        start_time_s=0.0,
        nb_frames=None,
        bit_rate=None,
        size_bytes=1_000,
        has_faststart=faststart,
        content_hash="abc",
    )


def test_validate_rejects_low_resolution() -> None:
    errors = validate_probe(_probe(width=1280, height=719))
    assert any("1280x720" in item for item in errors)


def test_validate_rejects_aspect_ratio() -> None:
    errors = validate_probe(_probe(width=1280, height=1024))
    assert any("Aspect ratio" in item for item in errors)


def test_validate_rejects_short_duration() -> None:
    errors = validate_probe(_probe(duration_s=119.0))
    assert any("5 minutes" in item for item in errors)


def test_validate_accepts_1080p60_long_enough() -> None:
    assert validate_probe(_probe()) == []


def test_handling_playable_faststart_uses_in_place() -> None:
    assert decide_handling(_probe()) == HandlingDecision.USE_IN_PLACE


def test_handling_playable_without_faststart_remuxes() -> None:
    assert decide_handling(_probe(faststart=False)) == HandlingDecision.REMUX_FASTSTART


def test_handling_hevc_transcodes() -> None:
    media = _probe(codec="hevc", pix="yuv420p")
    assert decide_handling(media) == HandlingDecision.TRANSCODE
    assert chromium_playable(media) is False


def test_handling_reject_when_too_small() -> None:
    assert decide_handling(_probe(width=640, height=480)) == HandlingDecision.REJECT


def test_missing_file_raises_clear_error(tmp_path: Path) -> None:
    with pytest.raises(MediaProbeError, match="not found"):
        probe(tmp_path / "missing.mp4")


def test_empty_file_raises(tmp_path: Path) -> None:
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    with pytest.raises(MediaProbeError, match="empty"):
        probe(empty)


def test_invalid_bytes_raise(tmp_path: Path) -> None:
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video at all " * 50)
    with pytest.raises(MediaProbeError):
        probe(junk)


def test_content_hash_stable_and_size_sensitive(tmp_path: Path) -> None:
    first = tmp_path / "a.bin"
    second = tmp_path / "b.bin"
    first.write_bytes(b"x" * 1000)
    second.write_bytes(b"x" * 1000)
    assert content_hash(first) == content_hash(second)
    second.write_bytes(b"x" * 1001)
    assert content_hash(first) != content_hash(second)


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _make_video(
    path: Path,
    *,
    seconds: int,
    size: str = "1280x720",
    codec: str = "libx264",
    fps: str = "60",
    vsync: str | None = None,
    start_offset: str | None = None,
) -> None:
    cmd = [
        _ffmpeg() or "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={size}:d={seconds}:r={fps}",
        "-c:v",
        codec,
        "-pix_fmt",
        "yuv420p",
    ]
    if vsync is not None:
        cmd.extend(["-fps_mode", vsync])
    if start_offset is not None:
        cmd.extend(["-output_ts_offset", start_offset])
    if codec == "libx264":
        cmd.extend(["-movflags", "+faststart"])
    cmd.append(str(path))
    subprocess.run(cmd, check=True, capture_output=True)


@pytest.mark.skipif(_ffmpeg() is None, reason="ffmpeg not installed")
def test_probe_cfr_h264_fixture(tmp_path: Path) -> None:
    path = tmp_path / "cfr.mp4"
    _make_video(path, seconds=2, fps="60")
    media = probe(path)
    assert media.width == 1280
    assert media.height == 720
    assert media.codec_name in {"h264", "avc1"}
    assert media.duration_s > 1.5
    assert decide_handling(media) == HandlingDecision.REJECT  # under 5 min


@pytest.mark.skipif(_ffmpeg() is None, reason="ffmpeg not installed")
def test_probe_nonzero_start_time(tmp_path: Path) -> None:
    path = tmp_path / "offset.mp4"
    _make_video(path, seconds=2, start_offset="1.25")
    media = probe(path)
    assert media.start_time_s >= 0.0


@pytest.mark.skipif(_ffmpeg() is None, reason="ffmpeg not installed")
def test_probe_hevc_routes_to_transcode_when_long(tmp_path: Path) -> None:
    path = tmp_path / "hevc.mp4"
    try:
        _make_video(path, seconds=2, codec="libx265")
    except subprocess.CalledProcessError:
        pytest.skip("libx265 not available")
    media = probe(path)
    media_long = MediaProbe(
        **{**media.__dict__, "duration_s": 600.0, "has_faststart": True}
    )
    assert decide_handling(media_long) == HandlingDecision.TRANSCODE
