from __future__ import annotations

from pathlib import Path

from riftlens.replay_host.api import (
    DEFAULT_REPLAY_API_ORIGIN,
    LiveClientDataClient,
    ReplayApiClient,
    ReplayPlayback,
    replay_api_ssl_context,
    riot_ca_path,
)
from riftlens.replay_host.windows.capability_probe import (
    ReplayApiCapability,
    probe_replay_api_capability,
)
from riftlens.replay_host.windows.game_config import (
    BACKUP_SUFFIX,
    GameConfigState,
    GameConfigWriteResult,
    backup_path_for,
    enable_replay_api,
    read_game_cfg,
    restore_game_cfg,
)
from riftlens.replay_host.windows.install_locator import (
    InstallDiscoveryMethod,
    LeagueInstall,
    LeagueInstallResult,
    default_well_known_roots,
    locate_league_install,
    validate_install_root,
)

__all__ = [
    "BACKUP_SUFFIX",
    "DEFAULT_REPLAY_API_ORIGIN",
    "GameConfigState",
    "GameConfigWriteResult",
    "InstallDiscoveryMethod",
    "LeagueInstall",
    "LeagueInstallResult",
    "LiveClientDataClient",
    "ReplayApiCapability",
    "ReplayApiClient",
    "ReplayPlayback",
    "backup_path_for",
    "default_well_known_roots",
    "enable_replay_api",
    "locate_league_install",
    "probe_replay_api_capability",
    "read_game_cfg",
    "replay_api_ssl_context",
    "restore_game_cfg",
    "riot_ca_path",
    "validate_install_root",
]


def replay_host_root() -> Path:
    """Return this package directory. Assumes the package is importable from source or wheel."""
    return Path(__file__).resolve().parent
