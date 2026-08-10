from __future__ import annotations

import sys
from typing import Any

from riftlens.replay_host.port import ReplayHostPort
from riftlens.replay_host.unsupported import UnsupportedReplayHost


def create_replay_host(
    *,
    platform: str | None = None,
    **windows_kwargs: Any,
) -> ReplayHostPort:
    """Return WindowsReplayHost on win32, otherwise UnsupportedReplayHost."""
    plat = sys.platform if platform is None else platform
    if plat != "win32":
        return UnsupportedReplayHost()
    from riftlens.replay_host.windows.host import WindowsReplayHost

    return WindowsReplayHost(**windows_kwargs)
