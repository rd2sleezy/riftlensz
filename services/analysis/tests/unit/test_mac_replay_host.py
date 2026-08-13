"""Deterministic MacReplayHost / install / Game/Config tests (no real League)."""

from __future__ import annotations

from pathlib import Path

import pytest
from riftlens.domain.gameplay_source import NATIVE_REPLAY_CAPABILITIES
from riftlens.domain.replay_errors import ReplayErrorCode
from riftlens.replay_host.factory import create_replay_host
from riftlens.replay_host.mac.game_config import (
    enable_mac_replay_api,
    read_mac_replay_api_state,
    restore_mac_replay_api,
)
from riftlens.replay_host.mac.host import MacReplayHost
from riftlens.replay_host.mac.install_locator import (
    locate_league_install_mac,
    validate_mac_install_root,
)
from riftlens.replay_host.mac.process import direct_exe_args
from riftlens.replay_host.unsupported import UnsupportedReplayHost
from riftlens.replay_host.windows.install_locator import InstallDiscoveryMethod


def _mac_tree(root: Path, *, enable_api: bool = False) -> Path:
    """Create a minimal validated Mac League tree under ``root`` (as LoL root)."""
    game = root / "Game"
    cfg_dir = game / "Config"
    exe = game / "LeagueofLegends.app" / "Contents" / "MacOS" / "LeagueofLegends"
    wad = game / "DATA" / "FINAL" / "Bootstrap.macos.wad.client"
    cfg_dir.mkdir(parents=True)
    exe.parent.mkdir(parents=True)
    wad.parent.mkdir(parents=True)
    exe.write_bytes(b"\0")
    wad.write_bytes(b"wad")
    lines = ["[General]\r\n", "EnableAudio=1\r\n", "AutoAcquireTarget=1\r\n"]
    if enable_api:
        lines.insert(2, "EnableReplayApi=1\r\n")
    (cfg_dir / "game.cfg").write_bytes("".join(lines).encode("utf-8"))
    (root / "Config").mkdir(parents=True, exist_ok=True)
    (root / "Config" / "game.cfg").write_bytes(b"[General]\r\nEnableAudio=1\r\n")
    return root


def test_validate_mac_install_requires_structure(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(Exception) as exc:
        validate_mac_install_root(empty)
    assert exc.value.code is ReplayErrorCode.INSTALL_INVALID  # type: ignore[attr-defined]


def test_validate_mac_install_accepts_app_bundle_shape(tmp_path: Path) -> None:
    app = tmp_path / "League of Legends.app"
    lol = app / "Contents" / "LoL"
    _mac_tree(lol)
    install = validate_mac_install_root(app)
    assert install.game_cfg == (lol / "Game" / "Config" / "game.cfg").resolve()
    assert install.game_dir == (lol / "Game").resolve()
    assert install.discovery_method is InstallDiscoveryMethod.CONFIGURED
    assert "LeagueofLegends" in install.game_exe.name


def test_locate_mac_well_known(tmp_path: Path) -> None:
    lol = _mac_tree(tmp_path / "LoL")
    result = locate_league_install_mac(
        platform="darwin",
        well_known_candidates=[lol],
    )
    assert result.install is not None
    assert result.error is None


def test_locate_mac_rejects_non_darwin(tmp_path: Path) -> None:
    lol = _mac_tree(tmp_path / "LoL")
    result = locate_league_install_mac(lol, platform="linux")
    assert result.install is None
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.PLATFORM_UNSUPPORTED


def test_game_config_enable_targets_game_config(tmp_path: Path) -> None:
    lol = _mac_tree(tmp_path / "LoL", enable_api=False)
    install = validate_mac_install_root(lol)
    assert read_mac_replay_api_state(install).enable_replay_api is False
    with pytest.raises(ValueError, match="consent"):
        enable_mac_replay_api(install, consent=False)  # type: ignore[arg-type]
    result = enable_mac_replay_api(install, consent=True)
    assert result.ok is True
    assert result.primary.changed is True
    assert result.primary.backup_path is not None
    assert result.primary.backup_path.is_file()
    assert read_mac_replay_api_state(install).enable_replay_api is True
    # Minimal edit: only EnableReplayApi added under General
    text = install.game_cfg.read_text(encoding="utf-8")
    assert "EnableReplayApi=1" in text
    assert "EnableAudio=1" in text
    # LoL/Config mirrored when present
    assert result.secondary is not None
    assert result.secondary.changed is True
    restored = restore_mac_replay_api(install, consent=True)
    assert restored.ok is True or restored.primary.state is not None
    assert read_mac_replay_api_state(install).enable_replay_api is False


def test_direct_exe_args_use_game_dir(tmp_path: Path) -> None:
    install = validate_mac_install_root(_mac_tree(tmp_path / "LoL"))
    rofl = tmp_path / "NA1-1.rofl"
    rofl.write_bytes(b"RIOT")
    args = direct_exe_args(install, rofl, platform_id="NA1")
    assert args[0] == str(rofl)
    assert args[1] == f"-GameBaseDir={install.game_dir}"
    assert "-PlatformID=NA1" in args
    assert "-SkipBuild" in args
    # Must NOT use LoL root (spike: wrong base dir fails wad mount)
    assert f"-GameBaseDir={install.root}" not in args


def test_factory_darwin_returns_mac_host() -> None:
    host = create_replay_host(platform="darwin")
    assert isinstance(host, MacReplayHost)
    assert host.platform_supported() is True
    assert host.platform_capabilities() == NATIVE_REPLAY_CAPABILITIES


def test_factory_linux_still_unsupported() -> None:
    host = create_replay_host(platform="linux")
    assert isinstance(host, UnsupportedReplayHost)
    assert host.platform_supported() is False


def test_mac_host_environment_reports_disabled_cfg(tmp_path: Path) -> None:
    from riftlens.replay_host.windows.capability_probe import ReplayApiCapability

    lol = _mac_tree(tmp_path / "LoL", enable_api=False)
    host = MacReplayHost(
        locate=lambda: locate_league_install_mac(lol, platform="darwin"),
        probe=lambda: ReplayApiCapability(
            reachable=False,
            replay_playback_present=False,
            documented_paths=(),
            spec_path=None,
            error=None,
        ),
    )
    env = host.check_environment()
    assert env.supported is True
    assert env.install_found is True
    assert any(w.code is ReplayErrorCode.REPLAY_API_DISABLED for w in env.warnings)


def test_mac_host_open_fails_when_api_disabled(tmp_path: Path) -> None:
    lol = _mac_tree(tmp_path / "LoL", enable_api=False)
    from riftlens.replay_host.windows.capability_probe import ReplayApiCapability

    host = MacReplayHost(
        locate=lambda: locate_league_install_mac(lol, platform="darwin"),
        probe=lambda: ReplayApiCapability(
            reachable=False,
            replay_playback_present=False,
            documented_paths=(),
            spec_path=None,
            error=None,
        ),
    )
    snap = host.open_session(str(tmp_path / "missing.rofl"))
    assert snap.error is not None
    assert snap.error.code is ReplayErrorCode.REPLAY_API_DISABLED
