"""macOS process launch for native .rofl replay.

Spike-proven launch (no shell-string interpolation):

``LeagueofLegends <rofl> -GameBaseDir=<Game> -Region=… -PlatformID=… -Locale=… -SkipBuild``

``GameBaseDir`` must be the Game directory (where ``DATA/FINAL`` lives), not LoL root.
"""

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
        """Return exit code if exited, else None."""
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
    """Return the Mac-proven argument vector. ``GameBaseDir`` is ``install.game_dir``."""
    platform = (platform_id or "NA1").upper()
    region = _PLATFORM_REGION.get(platform, "NA")
    return [
        str(rofl_path),
        f"-GameBaseDir={install.game_dir}",
        f"-Region={region}",
        f"-PlatformID={platform}",
        f"-Locale={locale}",
        "-SkipBuild",
    ]


def spawn_direct_exe(
    install: LeagueInstall, rofl_path: Path, *, platform_id: str | None = None
) -> OwnedProcess:
    """Spawn the Mac game binary with the spike-proven argument list."""
    if sys.platform != "darwin":
        raise ReplayError(
            ReplayErrorCode.PLATFORM_UNSUPPORTED,
            details={"reason": "direct_exe_requires_darwin"},
        )
    rofl = Path(rofl_path).expanduser().resolve()
    if not rofl.is_file():
        raise ReplayError(
            ReplayErrorCode.ROFL_MISSING,
            details={"reason": "rofl_not_file", "path": str(rofl)},
        )
    args = direct_exe_args(install, rofl, platform_id=platform_id)
    # Remove accidental SOFT_REPAIR left by wrong-GameBaseDir crashes (probe-era).
    soft_repair = install.game_dir / "LeagueofLegends.app" / "Contents" / "SOFT_REPAIR"
    try:
        if soft_repair.is_file():
            soft_repair.unlink()
    except OSError:
        pass
    try:
        popen = subprocess.Popen(  # noqa: S603 — exe path is a validated install binary
            [str(install.game_exe), *args],
            cwd=str(install.game_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
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
    """Attempt Finder association open. On macOS this typically fails for .rofl."""
    if sys.platform != "darwin":
        raise ReplayError(
            ReplayErrorCode.PLATFORM_UNSUPPORTED,
            details={"reason": "shell_open_requires_darwin"},
        )
    try:
        completed = subprocess.run(  # noqa: S603
            ["/usr/bin/open", str(rofl_path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReplayError(
            ReplayErrorCode.LAUNCH_FAILED,
            details={"reason": "shell_open_failed", "error": type(exc).__name__},
        ) from exc
    if completed.returncode != 0:
        raise ReplayError(
            ReplayErrorCode.LAUNCH_FAILED,
            details={
                "reason": "shell_open_rejected",
                "returncode": completed.returncode,
                "stderr": (completed.stderr or "")[:200],
            },
        )


def pid_is_running(pid: int) -> bool:
    """Return True when ``pid`` still exists. Does not inspect image names."""
    if pid <= 0:
        return False
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
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
