"""Portable media references. Committed fixtures must not use absolute paths."""

from __future__ import annotations

import os
import re
from pathlib import Path

_ABS_WINDOWS = re.compile(r"^[A-Za-z]:[\\/]")
_PORTABLE_PREFIXES = ("r10://", "vod://")


def default_r10_root() -> Path:
    """Return ``~/.riftlens/captures``."""
    return Path.home() / ".riftlens" / "captures"


def default_vod_root() -> Path:
    """Return ``RIFTLENS_VOD_ROOT`` or ``~/.riftlens/vods``."""
    env = os.environ.get("RIFTLENS_VOD_ROOT")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".riftlens" / "vods"


def is_portable_ref(media_ref: str) -> bool:
    """Return True when ``media_ref`` is an r10:// or vod:// URI."""
    return media_ref.startswith(_PORTABLE_PREFIXES)


def is_absolute_ref(media_ref: str) -> bool:
    """Return True when ``media_ref`` looks like a machine-specific path."""
    if media_ref.startswith("file://"):
        return True
    if media_ref.startswith("/"):
        return True
    return bool(_ABS_WINDOWS.match(media_ref))


def resolve_media_ref(
    media_ref: str,
    *,
    r10_root: Path | None = None,
    vod_root: Path | None = None,
    allow_absolute: bool = False,
) -> Path:
    """Resolve a media reference to a local path. Does not require the file to exist."""
    ref = media_ref.strip()
    if ref.startswith("r10://"):
        rest = ref.removeprefix("r10://")
        return (r10_root or default_r10_root()) / rest
    if ref.startswith("vod://"):
        rest = ref.removeprefix("vod://")
        return (vod_root or default_vod_root()) / rest
    if is_absolute_ref(ref):
        if not allow_absolute:
            raise ValueError(f"absolute media_ref is not portable (use r10:// or vod://): {ref}")
        if ref.startswith("file://"):
            return Path(ref.removeprefix("file://")).expanduser()
        return Path(ref).expanduser()
    raise ValueError(f"unsupported media_ref (expected r10:// or vod://): {ref}")
