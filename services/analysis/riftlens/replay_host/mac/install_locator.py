"""Locate and validate a macOS League of Legends install.

Spike truth (``spikes/mac_replay_probe/SPIKE_REPORT.md``):

* App bundle: ``/Applications/League of Legends.app``
* LoL root: ``…/Contents/LoL``
* Game dir: ``…/Contents/LoL/Game`` (``-GameBaseDir`` must point here)
* Game-read config: ``…/Game/Config/game.cfg`` (not ``LoL/Config`` alone)
* Binary: ``…/Game/LeagueofLegends.app/Contents/MacOS/LeagueofLegends``
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.windows.install_locator import (
    InstallDiscoveryMethod,
    LeagueInstall,
    LeagueInstallResult,
)

DEFAULT_APP_BUNDLE = Path("/Applications/League of Legends.app")
GAME_BINARY_REL = Path("LeagueofLegends.app/Contents/MacOS/LeagueofLegends")
BOOTSTRAP_WAD_REL = Path("DATA/FINAL/Bootstrap.macos.wad.client")
CLIENT_BINARY_REL = Path("LeagueClient.app/Contents/MacOS/LeagueClient")


def default_well_known_mac_roots() -> tuple[Path, ...]:
    """Return conventional macOS League LoL-root candidates."""
    return (DEFAULT_APP_BUNDLE / "Contents" / "LoL",)


def validate_mac_install_root(
    path: str | Path,
    *,
    discovery_method: InstallDiscoveryMethod = InstallDiscoveryMethod.CONFIGURED,
) -> LeagueInstall:
    """Validate a Mac install root or app bundle. Never trusts the display name alone."""
    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise ReplayError(
            ReplayErrorCode.INSTALL_INVALID,
            details={"reason": "resolve_failed", "error": type(exc).__name__},
        ) from exc
    root = _normalize_to_lol_root(resolved)
    if not root.is_dir():
        raise ReplayError(
            ReplayErrorCode.INSTALL_NOT_FOUND,
            details={"reason": "not_a_directory", "path": str(root)},
        )
    game_dir = root / "Game"
    game_cfg_dir = game_dir / "Config"
    game_exe = game_dir / GAME_BINARY_REL
    bootstrap = game_dir / BOOTSTRAP_WAD_REL
    if not game_dir.is_dir() or not game_exe.is_file():
        raise ReplayError(
            ReplayErrorCode.INSTALL_INVALID,
            details={
                "reason": "missing_structure",
                "path": str(root),
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
    if not bootstrap.is_file():
        raise ReplayError(
            ReplayErrorCode.INSTALL_INVALID,
            details={
                "reason": "missing_bootstrap_wad",
                "path": str(bootstrap),
                "hint": "GameBaseDir must be the Game directory that contains DATA/FINAL",
            },
        )
    if not game_cfg_dir.is_dir():
        raise ReplayError(
            ReplayErrorCode.INSTALL_INVALID,
            details={"reason": "missing_game_config_dir", "path": str(game_cfg_dir)},
        )
    client = root / CLIENT_BINARY_REL
    client_exe = None
    if client.is_file() and _is_within(client.resolve(), root):
        client_exe = client.resolve()
    # game_cfg is the config the game process actually reads (spike: Game/Config).
    return LeagueInstall(
        root=root.resolve(),
        game_dir=game_dir.resolve(),
        config_dir=game_cfg_dir.resolve(),
        game_exe=resolved_exe,
        client_exe=client_exe,
        game_cfg=game_cfg_dir / "game.cfg",
        discovery_method=discovery_method,
    )


def locate_league_install_mac(
    configured_path: str | Path | None = None,
    *,
    platform: str | None = None,
    well_known_candidates: Sequence[Path] | None = None,
) -> LeagueInstallResult:
    """Run the macOS install discovery chain. Registry probing is never used."""
    plat = sys.platform if platform is None else platform
    if plat != "darwin":
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
        list(well_known_candidates)
        if well_known_candidates is not None
        else list(default_well_known_mac_roots())
    ):
        result = _try_one(candidate, InstallDiscoveryMethod.WELL_KNOWN, attempts)
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


def lol_config_game_cfg(install: LeagueInstall) -> Path:
    """Return the secondary ``LoL/Config/game.cfg`` path (not sufficient alone on macOS)."""
    return install.root / "Config" / "game.cfg"


def _normalize_to_lol_root(path: Path) -> Path:
    """Accept app bundle, LoL root, or Game dir and return the LoL root."""
    if path.name.endswith(".app") and (path / "Contents" / "LoL").is_dir():
        return path / "Contents" / "LoL"
    if path.name == "LoL" and (path / "Game").is_dir():
        return path
    if path.name == "Game" and (path / GAME_BINARY_REL).is_file():
        return path.parent
    if (path / "Contents" / "LoL" / "Game").is_dir():
        return path / "Contents" / "LoL"
    return path


def _try_one(
    path: Path,
    method: InstallDiscoveryMethod,
    attempts: list[tuple[str, str]],
) -> LeagueInstallResult:
    """Validate one candidate and record the attempt."""
    attempts.append((method.value, str(path)))
    try:
        install = validate_mac_install_root(path, discovery_method=method)
    except ReplayError as exc:
        return LeagueInstallResult(install=None, error=exc, attempts=tuple(attempts))
    return LeagueInstallResult(install=install, error=None, attempts=tuple(attempts))


def _is_within(child: Path, root: Path) -> bool:
    """Return True when ``child`` resolves inside ``root``."""
    try:
        child.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


__all__ = [
    "DEFAULT_APP_BUNDLE",
    "default_well_known_mac_roots",
    "locate_league_install_mac",
    "lol_config_game_cfg",
    "validate_mac_install_root",
]
