from __future__ import annotations

import sys
from typing import Any

from riftlens.replay_host.port import ReplayHostPort
from riftlens.replay_host.unsupported import UnsupportedReplayHost


def create_replay_host(
    *,
    platform: str | None = None,
    **kwargs: Any,
) -> ReplayHostPort:
    """Return WindowsReplayHost on win32, MacReplayHost on darwin, else Unsupported."""
    plat = sys.platform if platform is None else platform
    if plat == "win32":
        from riftlens.replay_host.windows.host import WindowsReplayHost

        return WindowsReplayHost(**kwargs)
    if plat == "darwin":
        from riftlens.replay_host.mac.host import MacReplayHost

        return MacReplayHost(**kwargs)
    return UnsupportedReplayHost()
