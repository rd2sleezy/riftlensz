"""On-disk layout for R.10 captures (§7.4). Knows paths and hashes, not the Replay API."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable
from pathlib import Path

from riftlens.domain.capture import (
    CAPTURE_MANIFEST_NAME,
    CODEC_PNG,
    CaptureManifest,
)
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode

IMAGE_SUFFIXES: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".tga"})
CLIP_SUFFIXES: frozenset[str] = frozenset({".webm", ".mp4", ".avi", ".mkv"})
MEDIA_SUFFIXES: frozenset[str] = IMAGE_SUFFIXES | CLIP_SUFFIXES
FRAMES_DIRNAME = "frames"
CLIP_FILENAME = "clip.webm"
TEMP_CLIP_SUFFIX = ".webm.tmp"
_HASH_CHUNK = 1024 * 1024


def capture_dir(root: Path, match_id: str, capture_id: str) -> Path:
    """Return ``captures/{match_id}/{capture_id}``. Does not touch the filesystem."""
    return Path(root) / _safe_component(match_id) / _safe_component(capture_id)


def ensure_capture_dir(root: Path, match_id: str, capture_id: str) -> Path:
    """Create and return the per-capture directory. Raises ``CAPTURE_DISK_FAILED``."""
    target = capture_dir(root, match_id, capture_id)
    _mkdir(target)
    return target


def allocate_output_path(directory: Path, codec: str) -> Path:
    """Return the path handed to ``/replay/recording``: a frames dir for png, a file for clips."""
    if codec == CODEC_PNG:
        frames = Path(directory) / FRAMES_DIRNAME
        _mkdir(frames)
        return frames
    _mkdir(Path(directory))
    return Path(directory) / CLIP_FILENAME


def list_output_files(path: Path) -> tuple[Path, ...]:
    """Return recorded media files under ``path``, name-sorted. Missing paths yield ()."""
    target = Path(path)
    promote_temp_recorder_output(target)
    if target.is_file():
        return (target,)
    if not target.is_dir():
        # clip.webm may still be missing while clip.webm.tmp was just promoted beside it
        promoted = promote_temp_recorder_output(target)
        if promoted is not None and promoted.is_file():
            return (promoted,)
        return ()
    found = [
        item
        for item in target.rglob("*")
        if item.is_file() and item.suffix.lower() in MEDIA_SUFFIXES
    ]
    return tuple(sorted(found, key=lambda item: item.name))


def temp_recorder_sidecar(output: Path) -> Path:
    """Return League's macOS sidecar path (``clip.webm`` → ``clip.webm.tmp``)."""
    return Path(str(Path(output)) + ".tmp")


def promote_temp_recorder_output(output: Path) -> Path | None:
    """Promote a non-empty ``*.webm.tmp`` sidecar to the final clip path.

    macOS League often finishes encoding into ``clip.webm.tmp`` and never renames
    when ``GET /replay/recording`` stalls. Returns the usable final path, or None.
    """
    final = Path(output)
    if final.is_file() and file_size(final) > 0:
        return final
    candidates: list[Path] = []
    if final.suffix.lower() in CLIP_SUFFIXES or final.name.endswith(TEMP_CLIP_SUFFIX):
        candidates.append(temp_recorder_sidecar(final))
        candidates.append(final.with_name(final.name + ".tmp"))
    parent = final if final.is_dir() else final.parent
    if parent.is_dir():
        candidates.extend(sorted(parent.glob(f"*{TEMP_CLIP_SUFFIX}")))
    seen: set[Path] = set()
    for tmp in candidates:
        try:
            resolved = tmp.resolve()
        except OSError:
            resolved = tmp
        if resolved in seen:
            continue
        seen.add(resolved)
        if not tmp.is_file() or file_size(tmp) <= 0:
            continue
        target = final
        if target.is_dir() or target.suffix.lower() not in CLIP_SUFFIXES:
            target = parent / CLIP_FILENAME
        if target.exists() and file_size(target) > 0:
            return target
        try:
            tmp.replace(target)
        except OSError:
            continue
        if target.is_file() and file_size(target) > 0:
            return target
    return None


def recorder_output_bytes(output: Path) -> int:
    """Return bytes written for ``output``, including a League ``.tmp`` sidecar."""
    final = Path(output)
    size = file_size(final) if final.is_file() else directory_size(final) if final.is_dir() else 0
    if size > 0:
        return size
    return file_size(temp_recorder_sidecar(final))


def sha256_file(path: Path) -> str:
    """Return the hex digest of ``path``. Raises ``CAPTURE_DISK_FAILED`` when unreadable."""
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            while True:
                chunk = handle.read(_HASH_CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise _disk_error("hash_failed", path, exc) from exc
    return digest.hexdigest()


def file_size(path: Path) -> int:
    """Return the byte size of ``path``. Missing files count as zero."""
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def directory_size(path: Path) -> int:
    """Return the recursive byte size of ``path``. Missing directories count as zero."""
    target = Path(path)
    if target.is_file():
        return file_size(target)
    if not target.is_dir():
        return 0
    total = 0
    for item in target.rglob("*"):
        if item.is_file():
            total += file_size(item)
    return total


def write_manifest(directory: Path, manifest: CaptureManifest) -> Path:
    """Write ``manifest.json`` beside the artifacts. Raises ``CAPTURE_DISK_FAILED``."""
    target = Path(directory) / CAPTURE_MANIFEST_NAME
    try:
        _mkdir(Path(directory))
        target.write_text(
            json.dumps(manifest.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
        )
    except OSError as exc:
        raise _disk_error("manifest_write_failed", target, exc) from exc
    return target


def read_manifest(directory: Path) -> CaptureManifest | None:
    """Return the stored manifest, or None when it is missing or unparseable."""
    target = Path(directory) / CAPTURE_MANIFEST_NAME
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return CaptureManifest.from_dict(payload)
    except (KeyError, TypeError, ValueError):
        return None


def delete_capture_dir(directory: Path) -> None:
    """Remove a capture directory and its artifacts. Missing directories are fine."""
    shutil.rmtree(Path(directory), ignore_errors=True)


def prune_empty_parents(directory: Path, *, stop_at: Path) -> None:
    """Remove now-empty ``{match_id}`` parents up to ``stop_at``. Never deletes ``stop_at``."""
    current = Path(directory)
    root = Path(stop_at)
    while current != root and root in current.parents:
        try:
            if any(current.iterdir()):
                return
            current.rmdir()
        except OSError:
            return
        current = current.parent


def move_into(source: Path, destination: Path) -> Path:
    """Move ``source`` to ``destination``. Raises ``CAPTURE_DISK_FAILED`` on failure."""
    try:
        _mkdir(Path(destination).parent)
        return Path(shutil.move(str(source), str(destination)))
    except OSError as exc:
        raise _disk_error("move_failed", source, exc) from exc


def delete_files(paths: Iterable[Path]) -> None:
    """Best-effort removal of leftover recorder output. Missing files are ignored."""
    for item in paths:
        try:
            Path(item).unlink(missing_ok=True)
        except OSError:
            continue


def _mkdir(path: Path) -> None:
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _disk_error("mkdir_failed", path, exc) from exc


def _safe_component(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value)
    return cleaned or "unknown"


def _disk_error(reason: str, path: Path, exc: OSError) -> ReplayError:
    return ReplayError(
        ReplayErrorCode.CAPTURE_DISK_FAILED,
        details={"reason": reason, "path": str(path), "error": str(exc)},
    )
