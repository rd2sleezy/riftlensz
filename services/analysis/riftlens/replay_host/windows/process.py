from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.windows.install_locator import LeagueInstall

_PLATFORM_REGION = {
    "NA1": "NA",
    "EUW1": "EUW",
    "EUN1": "EUNE",
    "KR": "KR",
    "BR1": "BR",
    "LA1": "LAN",
    "LA2": "LAS",
    "OC1": "OCE",
    "RU": "RU",
    "TR1": "TR",
    "JP1": "JP",
    "PH2": "PH",
    "SG2": "SG",
    "TH2": "TH",
    "TW2": "TW",
    "VN2": "VN",
    "ME1": "ME",
}


@dataclass
class OwnedProcess:
    """A process RiftLens spawned. Teardown may terminate only this pid."""

    pid: int
    popen: subprocess.Popen[Any] | None = None
    terminated: bool = False

    def poll(self) -> int | None:
        """Return exit code if exited, else None. Assumes the handle is ours."""
        if self.popen is not None:
            return self.popen.poll()
        if not pid_is_running(self.pid):
            return 0
        return None

    def terminate(self) -> None:
        """Terminate only this pid. Never image-name kills League/Riot."""
        if self.terminated:
            return
        self.terminated = True
        if self.popen is not None:
            try:
                self.popen.terminate()
            except OSError:
                return
            return
        terminate_pid(self.pid)


def direct_exe_args(
    install: LeagueInstall,
    rofl_path: Path,
    *,
    platform_id: str | None = None,
    locale: str = "en_US",
) -> list[str]:
    """Return the R.0-proven ``League of Legends.exe`` argument vector."""
    platform = (platform_id or "NA1").upper()
    region = _PLATFORM_REGION.get(platform, "NA")
    return [
        str(rofl_path),
        f"-GameBaseDir={install.root}",
        f"-Region={region}",
        f"-PlatformID={platform}",
        f"-Locale={locale}",
        "-SkipBuild",
        "-EnableCrashpad=true",
    ]


def spawn_direct_exe(
    install: LeagueInstall, rofl_path: Path, *, platform_id: str | None = None
) -> OwnedProcess:
    """Spawn the game executable with the R.0 argument list. Windows-only."""
    if sys.platform != "win32":
        raise ReplayError(
            ReplayErrorCode.PLATFORM_UNSUPPORTED,
            details={"reason": "direct_exe_requires_win32"},
        )
    args = direct_exe_args(install, rofl_path, platform_id=platform_id)
    creationflags = 0
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creationflags |= subprocess.DETACHED_PROCESS
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        popen = subprocess.Popen(  # noqa: S603 — exe path is a validated install binary
            [str(install.game_exe), *args],
            cwd=str(install.game_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except OSError as exc:
        raise ReplayError(
            ReplayErrorCode.LAUNCH_FAILED,
            details={"reason": "spawn_failed", "error": type(exc).__name__},
        ) from exc
    if popen.pid is None:
        raise ReplayError(
            ReplayErrorCode.LAUNCH_FAILED,
            details={"reason": "spawn_no_pid"},
        )
    return OwnedProcess(pid=int(popen.pid), popen=popen)


def shell_open_rofl(rofl_path: Path) -> None:
    """Invoke the OS file association. Does not return a reliable pid."""
    if sys.platform != "win32":
        raise ReplayError(
            ReplayErrorCode.PLATFORM_UNSUPPORTED,
            details={"reason": "shell_open_requires_win32"},
        )
    startfile = getattr(os, "startfile", None)
    if startfile is None:
        raise ReplayError(
            ReplayErrorCode.PLATFORM_UNSUPPORTED,
            details={"reason": "startfile_missing"},
        )
    try:
        startfile(str(rofl_path))
    except OSError as exc:
        raise ReplayError(
            ReplayErrorCode.LAUNCH_FAILED,
            details={"reason": "shell_open_failed", "error": type(exc).__name__},
        ) from exc


def pid_is_running(pid: int) -> bool:
    """Return True when ``pid`` still exists. Does not inspect image names."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _win_pid_running(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def terminate_pid(pid: int) -> None:
    """Signal one pid. Never enumerates or kills other League/Riot processes."""
    if pid <= 0:
        return
    if sys.platform == "win32":
        _win_terminate(pid)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return


def _win_pid_running(pid: int) -> bool:
    """Query a Windows pid without depending on psutil."""
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    process_query_limited = 0x1000
    handle = kernel32.OpenProcess(process_query_limited, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) == 0:
            return True
        return int(exit_code.value) == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _win_terminate(pid: int) -> None:
    """TerminateProcess on one pid. Assumes the caller owns that process."""
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    process_terminate = 0x0001
    handle = kernel32.OpenProcess(process_terminate, False, pid)
    if not handle:
        return
    try:
        kernel32.TerminateProcess(handle, 1)
    finally:
        kernel32.CloseHandle(handle)
