from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode

BACKUP_SUFFIX = ".riftlens.bak"
ENABLE_KEY = "EnableReplayApi"
GENERAL_SECTION = "General"
MAX_CFG_BYTES = 1 * 1024 * 1024
_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(?:\r?\n)?$")
_KEY_RE = re.compile(r"^([^=\r\n]+?)\s*=\s*(.*?)\s*$")


@dataclass(frozen=True)
class GameConfigState:
    """Parsed ``game.cfg`` Replay API flag. Unrelated keys are not interpreted."""

    path: Path
    exists: bool
    general_present: bool
    enable_replay_api: bool
    newline: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready mapping. Assumes the state was already parsed."""
        return {
            "path": str(self.path),
            "exists": self.exists,
            "general_present": self.general_present,
            "enable_replay_api": self.enable_replay_api,
            "newline": "crlf" if self.newline == "\r\n" else "lf",
        }


@dataclass(frozen=True)
class GameConfigWriteResult:
    """Outcome of a consent-gated write or restore."""

    state: GameConfigState | None
    backup_path: Path | None
    changed: bool
    error: ReplayError | None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready mapping. Assumes the result was already constructed."""
        error = self.error
        return {
            "state": None if self.state is None else self.state.to_dict(),
            "backup_path": None if self.backup_path is None else str(self.backup_path),
            "changed": self.changed,
            "error": None
            if error is None
            else {"code": error.code.value, "message": str(error), "details": dict(error.details)},
        }


def backup_path_for(cfg_path: Path) -> Path:
    """Return ``game.cfg.riftlens.bak`` beside the config. Assumes ``cfg_path`` is the live file."""
    return cfg_path.with_name(cfg_path.name + BACKUP_SUFFIX)


def read_game_cfg(path: str | Path) -> GameConfigState:
    """Read Replay API enablement from ``game.cfg``. Does not write."""
    cfg_path = Path(path)
    text = _read_cfg_text(cfg_path)
    return _state_from_text(cfg_path, text)


def enable_replay_api(path: str | Path, *, consent: Literal[True]) -> GameConfigWriteResult:
    """Set ``[General] EnableReplayApi=1`` after backup. Refuses to run without ``consent=True``."""
    if consent is not True:
        raise ValueError("game.cfg edits require consent=True")
    cfg_path = Path(path)
    try:
        original = _read_cfg_text(cfg_path)
    except ReplayError as exc:
        return GameConfigWriteResult(state=None, backup_path=None, changed=False, error=exc)
    state = _state_from_text(cfg_path, original)
    if state.enable_replay_api:
        return GameConfigWriteResult(
            state=state, backup_path=_existing_backup(cfg_path), changed=False, error=None
        )
    rendered = _render_enabled(original, newline=state.newline)
    backup = _copy_backup_if_needed(cfg_path)
    try:
        cfg_path.write_text(rendered, encoding="utf-8", newline="")
    except OSError as exc:
        return GameConfigWriteResult(
            state=state,
            backup_path=backup,
            changed=False,
            error=ReplayError(
                ReplayErrorCode.INSTALL_INVALID,
                details={"reason": "write_failed", "error": type(exc).__name__},
            ),
        )
    return GameConfigWriteResult(
        state=_state_from_text(cfg_path, rendered),
        backup_path=backup,
        changed=True,
        error=None,
    )


def restore_game_cfg(path: str | Path, *, consent: Literal[True]) -> GameConfigWriteResult:
    """Restore ``game.cfg`` from ``game.cfg.riftlens.bak``. Requires explicit consent."""
    if consent is not True:
        raise ValueError("game.cfg restore requires consent=True")
    cfg_path = Path(path)
    backup = backup_path_for(cfg_path)
    if not backup.is_file():
        return GameConfigWriteResult(
            state=None,
            backup_path=None,
            changed=False,
            error=ReplayError(
                ReplayErrorCode.INSTALL_INVALID,
                details={"reason": "backup_missing", "backup_path": str(backup)},
            ),
        )
    try:
        shutil.copyfile(backup, cfg_path)
        text = _read_cfg_text(cfg_path)
    except (OSError, ReplayError) as exc:
        error = (
            exc
            if isinstance(exc, ReplayError)
            else ReplayError(
                ReplayErrorCode.INSTALL_INVALID,
                details={"reason": "restore_failed", "error": type(exc).__name__},
            )
        )
        return GameConfigWriteResult(state=None, backup_path=backup, changed=False, error=error)
    return GameConfigWriteResult(
        state=_state_from_text(cfg_path, text),
        backup_path=backup,
        changed=True,
        error=None,
    )


def _read_cfg_text(cfg_path: Path) -> str:
    """Return decoded config text. Missing or oversized files raise typed errors."""
    if not cfg_path.exists():
        raise ReplayError(
            ReplayErrorCode.INSTALL_INVALID,
            details={"reason": "cfg_missing", "path": str(cfg_path)},
        )
    if not cfg_path.is_file():
        raise ReplayError(
            ReplayErrorCode.INSTALL_INVALID,
            details={"reason": "cfg_not_a_file", "path": str(cfg_path)},
        )
    try:
        size = cfg_path.stat().st_size
    except OSError as exc:
        raise ReplayError(
            ReplayErrorCode.INSTALL_INVALID,
            details={"reason": "stat_failed", "error": type(exc).__name__},
        ) from exc
    if size > MAX_CFG_BYTES:
        raise ReplayError(
            ReplayErrorCode.INSTALL_INVALID,
            details={"reason": "cfg_too_large", "size_bytes": size},
        )
    try:
        data = cfg_path.read_bytes()
    except OSError as exc:
        raise ReplayError(
            ReplayErrorCode.INSTALL_INVALID,
            details={"reason": "read_failed", "error": type(exc).__name__},
        ) from exc
    if b"\x00" in data:
        raise ReplayError(
            ReplayErrorCode.INSTALL_INVALID,
            details={"reason": "malformed_config", "detail": "nul_bytes"},
        )
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("cp1252")
        except UnicodeDecodeError as exc:
            raise ReplayError(
                ReplayErrorCode.INSTALL_INVALID,
                details={"reason": "malformed_config", "detail": "undecodable"},
            ) from exc


def _state_from_text(cfg_path: Path, text: str) -> GameConfigState:
    """Parse enablement from already-loaded text. Assumes ``text`` is trusted size-bounded."""
    newline = "\r\n" if "\r\n" in text else "\n"
    general_present = False
    enabled = False
    current = ""
    for line in text.splitlines():
        section = _SECTION_RE.match(line + "\n")
        if section:
            current = section.group(1).strip()
            if current.lower() == GENERAL_SECTION.lower():
                general_present = True
            continue
        if current.lower() != GENERAL_SECTION.lower():
            continue
        key_match = _KEY_RE.match(line)
        if key_match is None:
            continue
        key = key_match.group(1).strip()
        value = key_match.group(2).strip()
        if key.lower() == ENABLE_KEY.lower():
            enabled = value == "1"
    return GameConfigState(
        path=cfg_path,
        exists=True,
        general_present=general_present,
        enable_replay_api=enabled,
        newline=newline,
    )


def _render_enabled(text: str, *, newline: str) -> str:
    """Return text with ``EnableReplayApi=1`` under ``[General]``, preserving other lines."""
    if text == "":
        return f"[{GENERAL_SECTION}]{newline}{ENABLE_KEY}=1{newline}"
    lines = text.splitlines(keepends=True)
    general_index = _find_section_index(lines, GENERAL_SECTION)
    if general_index is None:
        prefix = f"[{GENERAL_SECTION}]{newline}{ENABLE_KEY}=1{newline}"
        if text and not text.endswith(("\n", "\r")):
            return prefix + newline + text
        return prefix + text
    key_index = _find_key_in_section(lines, general_index, ENABLE_KEY)
    if key_index is not None:
        ending = _line_ending(lines[key_index], newline)
        lines[key_index] = f"{ENABLE_KEY}=1{ending}"
        return "".join(lines)
    insert_at = general_index + 1
    ending = newline
    lines.insert(insert_at, f"{ENABLE_KEY}=1{ending}")
    return "".join(lines)


def _find_section_index(lines: list[str], section: str) -> int | None:
    """Return the line index of ``[section]`` or None."""
    for index, line in enumerate(lines):
        match = _SECTION_RE.match(line)
        if match and match.group(1).strip().lower() == section.lower():
            return index
    return None


def _find_key_in_section(lines: list[str], section_index: int, key: str) -> int | None:
    """Return the index of ``key`` inside the section starting at ``section_index``."""
    for index in range(section_index + 1, len(lines)):
        if _SECTION_RE.match(lines[index]):
            break
        match = _KEY_RE.match(lines[index].rstrip("\r\n"))
        if match and match.group(1).strip().lower() == key.lower():
            return index
    return None


def _line_ending(line: str, default: str) -> str:
    """Return the existing line ending, or ``default`` when the line has none."""
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return default


def _copy_backup_if_needed(cfg_path: Path) -> Path:
    """Create ``game.cfg.riftlens.bak`` once as a byte-for-byte copy."""
    backup = backup_path_for(cfg_path)
    if not backup.exists():
        shutil.copyfile(cfg_path, backup)
    return backup


def _existing_backup(cfg_path: Path) -> Path | None:
    """Return the backup path when present."""
    backup = backup_path_for(cfg_path)
    return backup if backup.is_file() else None
