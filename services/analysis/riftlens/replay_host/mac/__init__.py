"""macOS-native League replay host (install, launch, config)."""

from __future__ import annotations

from riftlens.replay_host.mac.host import MacReplayHost
from riftlens.replay_host.mac.install_locator import (
    DEFAULT_APP_BUNDLE,
    locate_league_install_mac,
    validate_mac_install_root,
)

__all__ = [
    "DEFAULT_APP_BUNDLE",
    "MacReplayHost",
    "locate_league_install_mac",
    "validate_mac_install_root",
]
