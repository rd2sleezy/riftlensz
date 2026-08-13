"""Consent-gated EnableReplayApi for the Mac game-read config path."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.mac.install_locator import lol_config_game_cfg
from riftlens.replay_host.windows.game_config import (
    GameConfigState,
    GameConfigWriteResult,
    enable_replay_api,
    read_game_cfg,
    restore_game_cfg,
)
from riftlens.replay_host.windows.install_locator import LeagueInstall


@dataclass(frozen=True)
class MacReplayApiConfigResult:
    """Outcome of enabling or inspecting Mac Replay API config."""

    primary: GameConfigWriteResult
    secondary: GameConfigWriteResult | None = None

    @property
    def ok(self) -> bool:
        """Return True when the game-read config is enabled and writes succeeded."""
        if self.primary.error is not None:
            return False
        if self.primary.state is None or not self.primary.state.enable_replay_api:
            return False
        if self.secondary is not None and self.secondary.error is not None:
            return False
        return True

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready mapping."""
        return {
            "ok": self.ok,
            "primary": self.primary.to_dict(),
            "secondary": None if self.secondary is None else self.secondary.to_dict(),
        }


def read_mac_replay_api_state(install: LeagueInstall) -> GameConfigState:
    """Read enablement from ``Game/Config/game.cfg`` (required Mac path)."""
    return read_game_cfg(install.game_cfg)


def enable_mac_replay_api(
    install: LeagueInstall,
    *,
    consent: Literal[True],
    also_patch_lol_config: bool = True,
) -> MacReplayApiConfigResult:
    """Set ``EnableReplayApi=1`` on the game-read config after backup.

    Refuses to run without ``consent=True``. Optionally mirrors the flag into
    ``LoL/Config/game.cfg`` when that file exists (not sufficient alone).
    """
    if consent is not True:
        raise ValueError("game.cfg edits require consent=True")
    if not install.game_cfg.is_file():
        return MacReplayApiConfigResult(
            primary=GameConfigWriteResult(
                state=None,
                backup_path=None,
                changed=False,
                error=ReplayError(
                    ReplayErrorCode.INSTALL_INVALID,
                    details={
                        "reason": "game_cfg_missing",
                        "path": str(install.game_cfg),
                        "hint": "Mac Replay API requires Game/Config/game.cfg",
                    },
                ),
            )
        )
    primary = enable_replay_api(install.game_cfg, consent=True)
    secondary: GameConfigWriteResult | None = None
    if also_patch_lol_config:
        lol_cfg = lol_config_game_cfg(install)
        if lol_cfg.is_file():
            secondary = enable_replay_api(lol_cfg, consent=True)
    return MacReplayApiConfigResult(primary=primary, secondary=secondary)


def restore_mac_replay_api(
    install: LeagueInstall,
    *,
    consent: Literal[True],
    also_restore_lol_config: bool = True,
) -> MacReplayApiConfigResult:
    """Restore Mac game.cfg files from ``.riftlens.bak`` backups."""
    if consent is not True:
        raise ValueError("game.cfg restore requires consent=True")
    primary = restore_game_cfg(install.game_cfg, consent=True)
    secondary: GameConfigWriteResult | None = None
    if also_restore_lol_config:
        lol_cfg = lol_config_game_cfg(install)
        backup = Path(str(lol_cfg) + ".riftlens.bak")
        if backup.is_file():
            secondary = restore_game_cfg(lol_cfg, consent=True)
    return MacReplayApiConfigResult(primary=primary, secondary=secondary)
