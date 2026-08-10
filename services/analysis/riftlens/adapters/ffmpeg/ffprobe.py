from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping
from typing import Any


class FfprobeError(RuntimeError):
    """Raised when ffprobe is missing or returns unusable output."""


def run_ffprobe(path: str) -> Mapping[str, Any]:
    """Return ffprobe JSON for ``path``. Assumes the file exists on disk."""
    binary = shutil.which("ffprobe")
    if binary is None:
        raise FfprobeError("ffprobe is not installed or not on PATH")
    result = subprocess.run(
        [
            binary,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ffprobe failed").strip()
        raise FfprobeError(detail)
    try:
        parsed: object = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise FfprobeError("ffprobe returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise FfprobeError("ffprobe JSON root must be an object")
    return parsed
