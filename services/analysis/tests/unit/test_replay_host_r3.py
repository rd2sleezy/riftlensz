from __future__ import annotations

import json
import re
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.windows.capability_probe import (
    probe_replay_api_capability,
    riot_ca_path,
)
from riftlens.replay_host.windows.game_config import (
    backup_path_for,
    enable_replay_api,
    read_game_cfg,
    restore_game_cfg,
)
from riftlens.replay_host.windows.install_locator import (
    GAME_EXE_NAME,
    InstallDiscoveryMethod,
    locate_league_install,
    validate_install_root,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "replay_api"
UNRELATED_CERT = FIXTURES / "unrelated_cert.pem"
UNRELATED_KEY = FIXTURES / "unrelated_key.pem"
PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "riftlens"
REAL_INSTALL = Path(r"C:\Riot Games\League of Legends")


def _make_install(root: Path) -> Path:
    (root / "Config").mkdir(parents=True)
    (root / "Game").mkdir()
    (root / "Game" / GAME_EXE_NAME).write_bytes(b"mz")
    (root / "LeagueClient.exe").write_bytes(b"mz")
    (root / "Config" / "game.cfg").write_text("[General]\nCfgVersion=1\n", encoding="utf-8")
    return root


class _SpecServer(HTTPServer):
    spec_paths: dict[str, object]


class _SpecHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path not in {"/swagger/v3/openapi.json", "/swagger/v2/swagger.json"}:
            self.send_error(404)
            return
        server = self.server
        assert isinstance(server, _SpecServer)
        body = json.dumps({"paths": server.spec_paths}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def _start_https_server(paths: dict[str, object]) -> tuple[HTTPServer, int]:
    server = _SpecServer(("127.0.0.1", 0), _SpecHandler)
    server.spec_paths = paths
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(UNRELATED_CERT), str(UNRELATED_KEY))
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    return server, port


def test_valid_install_root(tmp_path: Path) -> None:
    root = _make_install(tmp_path / "League of Legends")
    install = validate_install_root(root)
    assert install.game_exe.is_file()
    assert install.config_dir.name == "Config"
    assert install.discovery_method is InstallDiscoveryMethod.CONFIGURED


def test_invalid_and_missing_install_structure(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    with pytest.raises(ReplayError) as not_found:
        validate_install_root(missing)
    assert not_found.value.code is ReplayErrorCode.INSTALL_NOT_FOUND
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ReplayError) as invalid:
        validate_install_root(empty)
    assert invalid.value.code is ReplayErrorCode.INSTALL_INVALID


def test_configured_path_takes_precedence(tmp_path: Path) -> None:
    configured = _make_install(tmp_path / "configured")
    other = _make_install(tmp_path / "registry")
    result = locate_league_install(
        configured,
        platform="win32",
        registry_candidates=[other],
        well_known_candidates=[other],
        running_client_candidates=[],
    )
    assert result.install is not None
    assert result.install.root == configured.resolve()
    assert result.install.discovery_method is InstallDiscoveryMethod.CONFIGURED


def test_registry_then_well_known_fallback(tmp_path: Path) -> None:
    well_known = _make_install(tmp_path / "well-known")
    missing = tmp_path / "missing-reg"
    result = locate_league_install(
        platform="win32",
        registry_candidates=[missing],
        well_known_candidates=[well_known],
        running_client_candidates=[],
    )
    assert result.install is not None
    assert result.install.discovery_method is InstallDiscoveryMethod.WELL_KNOWN
    registry = _make_install(tmp_path / "registry-hit")
    result_reg = locate_league_install(
        platform="win32",
        registry_candidates=[registry],
        well_known_candidates=[well_known],
        running_client_candidates=[],
    )
    assert result_reg.install is not None
    assert result_reg.install.discovery_method is InstallDiscoveryMethod.REGISTRY


def test_non_windows_platform_is_unsupported(tmp_path: Path) -> None:
    root = _make_install(tmp_path / "League of Legends")
    result = locate_league_install(root, platform="darwin")
    assert result.install is None
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.PLATFORM_UNSUPPORTED


def test_game_cfg_enabled_disabled_and_missing_general(tmp_path: Path) -> None:
    enabled = tmp_path / "enabled.cfg"
    enabled.write_text("[General]\r\nEnableReplayApi=1\r\nFoo=bar\r\n", encoding="utf-8")
    assert read_game_cfg(enabled).enable_replay_api is True
    disabled = tmp_path / "disabled.cfg"
    disabled.write_text("[General]\nEnableReplayApi=0\n", encoding="utf-8")
    assert read_game_cfg(disabled).enable_replay_api is False
    missing = tmp_path / "nogen.cfg"
    missing.write_text("[Other]\nKeep=1\n", encoding="utf-8")
    state = read_game_cfg(missing)
    assert state.general_present is False
    assert state.enable_replay_api is False


def test_enable_preserves_unrelated_keys_and_writes_backup(tmp_path: Path) -> None:
    cfg = tmp_path / "game.cfg"
    original = (
        b"[General]\r\nCfgVersion=16.15.801.3452\r\nFoo=bar\r\n\r\n"
        b"[Performance]\r\nWaitForVBlank=0\r\n"
    )
    cfg.write_bytes(original)
    result = enable_replay_api(cfg, consent=True)
    assert result.error is None
    assert result.changed is True
    assert result.backup_path == backup_path_for(cfg)
    assert result.backup_path is not None
    assert result.backup_path.read_bytes() == original
    text = cfg.read_text(encoding="utf-8", newline="")
    assert "CfgVersion=16.15.801.3452" in text
    assert "Foo=bar" in text
    assert "[Performance]" in text
    assert "WaitForVBlank=0" in text
    assert "EnableReplayApi=1" in text
    assert b"\r\n" in cfg.read_bytes()
    assert read_game_cfg(cfg).enable_replay_api is True


def test_restore_and_stable_backup(tmp_path: Path) -> None:
    cfg = tmp_path / "game.cfg"
    cfg.write_text("[General]\nEnableReplayApi=0\nKeep=yes\n", encoding="utf-8")
    first = enable_replay_api(cfg, consent=True)
    assert first.changed is True
    restored = restore_game_cfg(cfg, consent=True)
    assert restored.error is None
    assert read_game_cfg(cfg).enable_replay_api is False
    assert "Keep=yes" in cfg.read_text(encoding="utf-8")
    cfg.write_text("[General]\nEnableReplayApi=0\nKeep=changed\n", encoding="utf-8")
    second = enable_replay_api(cfg, consent=True)
    assert second.changed is True
    assert first.backup_path is not None
    assert "Keep=yes" in first.backup_path.read_text(encoding="utf-8")


def test_malformed_config_is_typed_error(tmp_path: Path) -> None:
    cfg = tmp_path / "game.cfg"
    cfg.write_bytes(b"[General]\nEnableReplayApi=1\n\x00oops")
    with pytest.raises(ReplayError) as exc_info:
        read_game_cfg(cfg)
    assert exc_info.value.code is ReplayErrorCode.INSTALL_INVALID
    assert exc_info.value.details.get("reason") == "malformed_config"


def test_enable_without_consent_is_rejected(tmp_path: Path) -> None:
    cfg = tmp_path / "game.cfg"
    cfg.write_text("[General]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="consent"):
        enable_replay_api(cfg, consent=False)  # type: ignore[arg-type]


def test_probe_replay_paths_present() -> None:
    server, port = _start_https_server({"/replay/playback": {}, "/replay/game": {}})
    try:
        result = probe_replay_api_capability(
            origin=f"https://127.0.0.1:{port}",
            ca_file=UNRELATED_CERT,
        )
    finally:
        server.shutdown()
        server.server_close()
    assert result.error is None
    assert result.reachable is True
    assert result.replay_playback_present is True
    assert "/replay/playback" in result.documented_paths


def test_probe_reachable_without_replay_paths() -> None:
    server, port = _start_https_server({"/liveclientdata/gamestats": {}})
    try:
        result = probe_replay_api_capability(
            origin=f"https://127.0.0.1:{port}",
            ca_file=UNRELATED_CERT,
        )
    finally:
        server.shutdown()
        server.server_close()
    assert result.reachable is True
    assert result.replay_playback_present is False
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.REPLAY_API_DISABLED


def test_probe_unreachable() -> None:
    result = probe_replay_api_capability(
        origin="https://127.0.0.1:59998",
        ca_file=UNRELATED_CERT,
        timeout_s=0.5,
    )
    assert result.reachable is False
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.REPLAY_API_UNAVAILABLE


def test_probe_tls_failure_is_typed() -> None:
    server, port = _start_https_server({"/replay/playback": {}})
    try:
        result = probe_replay_api_capability(
            origin=f"https://127.0.0.1:{port}",
            ca_file=riot_ca_path(),
            timeout_s=2.0,
        )
    finally:
        server.shutdown()
        server.server_close()
    assert result.reachable is False
    assert result.error is not None
    assert result.error.code is ReplayErrorCode.REPLAY_API_TLS


def test_winreg_stays_inside_windows_package() -> None:
    pattern = re.compile(r"^\s*(import winreg|from winreg import)\b", re.MULTILINE)
    offenders: list[str] = []
    windows_hits = 0
    for path in PACKAGE_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if not pattern.search(text):
            continue
        rel = path.relative_to(PACKAGE_ROOT).as_posix()
        if rel.startswith("replay_host/windows/"):
            windows_hits += 1
            continue
        offenders.append(rel)
    assert offenders == []
    assert windows_hits >= 1


@pytest.mark.skipif(
    not (REAL_INSTALL / "Game" / GAME_EXE_NAME).is_file(),
    reason="League install not present",
)
def test_t3_real_league_install_discovery() -> None:
    result = locate_league_install(
        platform="win32",
        well_known_candidates=None,
        running_client_candidates=[],
    )
    assert result.install is not None
    assert result.install.game_exe.is_file()
    assert result.install.config_dir.is_dir()
    assert result.error is None
    cfg = result.install.game_cfg
    if cfg.is_file():
        state = read_game_cfg(cfg)
        assert isinstance(state.enable_replay_api, bool)
