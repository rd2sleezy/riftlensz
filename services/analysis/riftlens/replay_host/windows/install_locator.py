from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode

GAME_EXE_NAME = "League of Legends.exe"
CLIENT_EXE_NAME = "LeagueClient.exe"
_UNSAFE_PREFIXES = ("\\\\", "//")


class InstallDiscoveryMethod(StrEnum):
    """How a League install root was found. User browse is a caller-supplied configured path."""

    CONFIGURED = "configured"
    REGISTRY = "registry"
    WELL_KNOWN = "well_known"
    RUNNING_CLIENT = "running_client"


@dataclass(frozen=True)
class LeagueInstall:
    """A structurally validated League install. Paths are resolved; no process is launched."""

    root: Path
    game_dir: Path
    config_dir: Path
    game_exe: Path
    client_exe: Path | None
    game_cfg: Path
    discovery_method: InstallDiscoveryMethod

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready mapping. Assumes the install was already validated."""
        return {
            "root": str(self.root),
            "game_dir": str(self.game_dir),
            "config_dir": str(self.config_dir),
            "game_exe": str(self.game_exe),
            "client_exe": None if self.client_exe is None else str(self.client_exe),
            "game_cfg": str(self.game_cfg),
            "discovery_method": self.discovery_method.value,
        }


@dataclass(frozen=True)
class LeagueInstallResult:
    """Locate outcome. ``error`` is set when no usable install was found."""

    install: LeagueInstall | None
    error: ReplayError | None
    attempts: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready mapping. Assumes the result was already constructed."""
        error = self.error
        return {
            "install": None if self.install is None else self.install.to_dict(),
            "error": None
            if error is None
            else {"code": error.code.value, "message": str(error), "details": dict(error.details)},
            "attempts": [{"method": method, "path": path} for method, path in self.attempts],
        }


def default_well_known_roots() -> tuple[Path, ...]:
    """Return conventional League install locations. Assumes env vars may be absent."""
    roots: list[Path] = []
    for drive in ("C", "D", "E", "F"):
        roots.append(Path(f"{drive}:/Riot Games/League of Legends"))
    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env_name)
        if base:
            roots.append(Path(base) / "Riot Games" / "League of Legends")
    return _dedupe_paths(roots)


def validate_install_root(
    path: str | Path,
    *,
    discovery_method: InstallDiscoveryMethod = InstallDiscoveryMethod.CONFIGURED,
) -> LeagueInstall:
    """Return a validated install or raise ``ReplayError``. Never trusts the folder name alone."""
    candidate = Path(path)
    if _is_unsafe_path(candidate):
        raise ReplayError(
            ReplayErrorCode.INSTALL_INVALID,
            details={"reason": "unsafe_path", "path": str(candidate)},
        )
    try:
        root = candidate.expanduser().resolve()
    except OSError as exc:
        raise ReplayError(
            ReplayErrorCode.INSTALL_INVALID,
            details={"reason": "resolve_failed", "error": type(exc).__name__},
        ) from exc
    if _is_unsafe_path(root) or not root.is_absolute():
        raise ReplayError(
            ReplayErrorCode.INSTALL_INVALID,
            details={"reason": "unsafe_resolved_path", "path": str(root)},
        )
    if not root.is_dir():
        raise ReplayError(
            ReplayErrorCode.INSTALL_NOT_FOUND,
            details={"reason": "not_a_directory", "path": str(root)},
        )
    config_dir = root / "Config"
    game_dir = root / "Game"
    game_exe = game_dir / GAME_EXE_NAME
    if not config_dir.is_dir() or not game_dir.is_dir() or not game_exe.is_file():
        raise ReplayError(
            ReplayErrorCode.INSTALL_INVALID,
            details={
                "reason": "missing_structure",
                "path": str(root),
                "has_config": config_dir.is_dir(),
                "has_game": game_dir.is_dir(),
                "has_game_exe": game_exe.is_file(),
            },
        )
    resolved_exe = game_exe.resolve()
    if not _is_within(resolved_exe, root):
        raise ReplayError(
            ReplayErrorCode.INSTALL_INVALID,
            details={"reason": "exe_outside_root", "path": str(root)},
        )
    client = root / CLIENT_EXE_NAME
    client_exe = None
    if client.is_file() and _is_within(client.resolve(), root):
        client_exe = client.resolve()
    return LeagueInstall(
        root=root,
        game_dir=game_dir.resolve(),
        config_dir=config_dir.resolve(),
        game_exe=resolved_exe,
        client_exe=client_exe,
        game_cfg=config_dir / "game.cfg",
        discovery_method=discovery_method,
    )


def locate_league_install(
    configured_path: str | Path | None = None,
    *,
    platform: str | None = None,
    registry_candidates: Sequence[Path] | None = None,
    well_known_candidates: Sequence[Path] | None = None,
    running_client_candidates: Sequence[Path] | None = None,
) -> LeagueInstallResult:
    """Run the install strategy chain. Registry probing runs only on a real win32 interpreter."""
    plat = sys.platform if platform is None else platform
    if plat != "win32":
        return LeagueInstallResult(
            install=None,
            error=ReplayError(
                ReplayErrorCode.PLATFORM_UNSUPPORTED,
                details={"platform": plat, "suggested_action": "attach_video"},
            ),
        )
    attempts: list[tuple[str, str]] = []
    if configured_path is not None:
        return _try_one(Path(configured_path), InstallDiscoveryMethod.CONFIGURED, attempts)
    for candidate in (
        list(registry_candidates)
        if registry_candidates is not None
        else _registry_install_candidates()
    ):
        result = _try_one(candidate, InstallDiscoveryMethod.REGISTRY, attempts)
        if result.install is not None:
            return result
    for candidate in (
        list(well_known_candidates)
        if well_known_candidates is not None
        else list(default_well_known_roots())
    ):
        result = _try_one(candidate, InstallDiscoveryMethod.WELL_KNOWN, attempts)
        if result.install is not None:
            return result
    running = (
        list(running_client_candidates)
        if running_client_candidates is not None
        else _running_client_candidates()
    )
    for candidate in running:
        result = _try_one(candidate, InstallDiscoveryMethod.RUNNING_CLIENT, attempts)
        if result.install is not None:
            return result
    return LeagueInstallResult(
        install=None,
        error=ReplayError(
            ReplayErrorCode.INSTALL_NOT_FOUND,
            details={"reason": "no_valid_candidate", "suggested_action": "browse_to_install"},
        ),
        attempts=tuple(attempts),
    )


def _try_one(
    path: Path,
    method: InstallDiscoveryMethod,
    attempts: list[tuple[str, str]],
) -> LeagueInstallResult:
    """Validate one candidate and record the attempt. Assumes ``path`` is untrusted."""
    attempts.append((method.value, str(path)))
    try:
        install = validate_install_root(path, discovery_method=method)
    except ReplayError as exc:
        return LeagueInstallResult(install=None, error=exc, attempts=tuple(attempts))
    return LeagueInstallResult(install=install, error=None, attempts=tuple(attempts))


def _registry_install_candidates() -> list[Path]:
    """Read Riot / uninstall registry locations. Assumes winreg is unavailable off Windows."""
    if sys.platform != "win32":
        return []
    import winreg

    found: list[Path] = []
    hives = (
        (winreg.HKEY_CURRENT_USER, "HKCU"),
        (winreg.HKEY_LOCAL_MACHINE, "HKLM"),
    )
    key_paths = (
        r"SOFTWARE\Riot Games\League of Legends",
        r"SOFTWARE\WOW6432Node\Riot Games\League of Legends",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Riot Game league_of_legends.live",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
        r"\Riot Game league_of_legends.live",
    )
    value_names = ("Location", "InstallLocation", "Path", "InstallDir")
    for hive, _label in hives:
        for key_path in key_paths:
            found.extend(_reg_values(winreg, hive, key_path, value_names))
        found.extend(_reg_uninstall_scan(winreg, hive))
    return list(_dedupe_paths(found))


def _reg_values(
    winreg: Any,
    hive: int,
    key_path: str,
    value_names: tuple[str, ...],
) -> list[Path]:
    """Return path-like values from one key. Missing keys are ignored."""
    try:
        handle = winreg.OpenKey(hive, key_path)
    except OSError:
        return []
    try:
        paths: list[Path] = []
        for name in value_names:
            try:
                value, _typ = winreg.QueryValueEx(handle, name)
            except winreg.error:
                continue
            if isinstance(value, str) and value.strip():
                paths.append(Path(value.strip()))
        return paths
    finally:
        winreg.CloseKey(handle)


def _reg_uninstall_scan(winreg: Any, hive: int) -> list[Path]:
    """Scan uninstall keys for League display names. Bounded; ignores inaccessible keys."""
    uninstall = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    wow = r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    found: list[Path] = []
    for base in (uninstall, wow):
        found.extend(_reg_uninstall_hive(winreg, hive, base))
    return found


def _reg_uninstall_hive(winreg: Any, hive: int, base: str) -> list[Path]:
    """Scan one uninstall hive. Assumes subkeys may be missing or unreadable."""
    try:
        handle = winreg.OpenKey(hive, base)
    except OSError:
        return []
    paths: list[Path] = []
    try:
        for index in range(512):
            try:
                name = winreg.EnumKey(handle, index)
            except OSError:
                break
            try:
                sub = winreg.OpenKey(handle, name)
            except OSError:
                continue
            try:
                try:
                    display, _typ = winreg.QueryValueEx(sub, "DisplayName")
                except winreg.error:
                    continue
                if not isinstance(display, str) or "league of legends" not in display.lower():
                    continue
                try:
                    location, _typ = winreg.QueryValueEx(sub, "InstallLocation")
                except winreg.error:
                    continue
                if isinstance(location, str) and location.strip():
                    paths.append(Path(location.strip()))
            finally:
                winreg.CloseKey(sub)
    finally:
        winreg.CloseKey(handle)
    return paths


def _running_client_candidates() -> list[Path]:
    """Best-effort process image paths. Does not read the LCU lockfile or call LCU HTTP."""
    if sys.platform != "win32":
        return []
    script = (
        "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue "
        "| Where-Object { $_.Name -eq 'LeagueClient.exe' "
        "-or $_.Name -eq 'League of Legends.exe' } "
        "| Select-Object -ExpandProperty ExecutablePath"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    roots: list[Path] = []
    for line in completed.stdout.splitlines():
        image = Path(line.strip())
        if not image.is_file():
            continue
        name = image.name.lower()
        if name == CLIENT_EXE_NAME.lower():
            roots.append(image.parent)
        elif name == GAME_EXE_NAME.lower():
            roots.append(image.parent.parent)
    return list(_dedupe_paths(roots))


def _is_unsafe_path(path: Path) -> bool:
    """Return True for UNC or other non-local roots. Relative paths are resolved by the caller."""
    raw = str(path)
    return raw.startswith(_UNSAFE_PREFIXES) or raw.startswith("\\\\?\\UNC\\")


def _is_within(child: Path, root: Path) -> bool:
    """Return True when ``child`` resolves inside ``root``."""
    try:
        child.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _dedupe_paths(paths: Sequence[Path]) -> tuple[Path, ...]:
    """Preserve first-seen resolved paths. Unresolvable entries are kept as given."""
    seen: set[str] = set()
    ordered: list[Path] = []
    for path in paths:
        key = str(path)
        try:
            key = str(path.resolve())
        except OSError:
            pass
        lowered = key.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        ordered.append(path)
    return tuple(ordered)
