from __future__ import annotations

import json
import ssl
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "replay_api"
DEFAULT_CERT = _FIXTURES / "unrelated_cert.pem"
DEFAULT_KEY = _FIXTURES / "unrelated_key.pem"

_DEFAULT_PLAYBACK: dict[str, Any] = {
    "length": 1902.9725341796875,
    "paused": False,
    "seeking": False,
    "speed": 1,
    "time": 2.2609195709228516,
}


@dataclass
class FakeReplayBehavior:
    """Configurable Replay API + LCD misbehaviours for T1 contract tests."""

    playback: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_PLAYBACK))
    game: dict[str, Any] = field(default_factory=lambda: {"processID": 14520})
    render: dict[str, Any] = field(default_factory=lambda: {"fogOfWar": True, "cameraMode": "fps"})
    recording: dict[str, Any] = field(
        default_factory=lambda: {
            "codec": "webm",
            "currentTime": 0.0,
            "endTime": 0.0,
            "enforceFrameRate": False,
            "framesPerSecond": 0.0,
            "height": 0,
            "lossless": False,
            "path": "",
            "recording": False,
            "replaySpeed": 1.0,
            "startTime": 0.0,
            "width": 0,
        }
    )
    sequence: dict[str, Any] = field(default_factory=lambda: {"playbackSpeed": 1.0})
    gamestats: dict[str, Any] = field(
        default_factory=lambda: {
            "gameMode": "CLASSIC",
            "gameTime": 12.5,
            "mapName": "Map11",
            "mapNumber": 11,
            "mapTerrain": "Default",
        }
    )
    eventdata: dict[str, Any] = field(
        default_factory=lambda: {
            "Events": [
                {"EventID": 0, "EventName": "GameStart", "EventTime": 0.0},
                {"EventID": 1, "EventName": "ChampionKill", "EventTime": 95.2},
            ]
        }
    )
    playerlist: list[dict[str, Any]] = field(
        default_factory=lambda: [{"championName": "Ahri", "isDead": False, "level": 6}]
    )
    activeplayer_status: int = 400
    activeplayer_body: dict[str, Any] = field(
        default_factory=lambda: {
            "errorCode": "RPC_ERROR",
            "httpStatus": 400,
            "implementationDetails": "",
            "message": "Unable to get active player data",
        }
    )
    activeplayername: Any = ""
    status_overrides: dict[str, int] = field(default_factory=dict)
    malformed_paths: set[str] = field(default_factory=set)
    slow_paths: dict[str, float] = field(default_factory=dict)
    seek_delay_s: float = 0.0
    seeking_stuck: bool = False
    seeking_polls_remaining: int = 0
    seek_misses_remaining: int = 0
    time_frozen: bool = True
    drop_next: int = 0
    transient_failures: dict[str, int] = field(default_factory=dict)
    post_log: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


class FakeReplayApiServer:
    """Real HTTPS Replay/LCD fake on an ephemeral loopback port."""

    def __init__(
        self,
        behavior: FakeReplayBehavior | None = None,
        *,
        certfile: Path = DEFAULT_CERT,
        keyfile: Path = DEFAULT_KEY,
    ) -> None:
        self.behavior = behavior if behavior is not None else FakeReplayBehavior()
        self.certfile = certfile
        self.keyfile = keyfile
        self._httpd: _ReplayHttpServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def origin(self) -> str:
        """Return ``https://127.0.0.1:<port>``. Assumes the server has started."""
        if self._httpd is None:
            raise RuntimeError("FakeReplayApiServer is not running")
        return f"https://127.0.0.1:{self._httpd.server_address[1]}"

    @property
    def ca_file(self) -> Path:
        """Return the server certificate path for client pinning in tests."""
        return self.certfile

    def start(self) -> FakeReplayApiServer:
        """Bind loopback TLS and serve in a daemon thread."""
        httpd = _ReplayHttpServer(("127.0.0.1", 0), _ReplayHandler)
        httpd.behavior = self.behavior
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(self.certfile), str(self.keyfile))
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        self._httpd = httpd
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self._thread = thread
        return self

    def stop(self) -> None:
        """Shut down the fake server. Safe to call more than once."""
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        self._thread = None

    def __enter__(self) -> FakeReplayApiServer:
        return self.start()

    def __exit__(self, *args: object) -> None:
        self.stop()


class _ReplayHttpServer(HTTPServer):
    behavior: FakeReplayBehavior


class _ReplayHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _dispatch(self, method: str) -> None:
        server = self.server
        assert isinstance(server, _ReplayHttpServer)
        behavior = server.behavior
        path = urlparse(self.path).path
        if behavior.drop_next > 0:
            behavior.drop_next -= 1
            self.close_connection = True
            try:
                self.connection.close()
            except OSError:
                pass
            return
        delay = behavior.slow_paths.get(path, 0.0)
        if delay > 0:
            time.sleep(delay)
        remaining = behavior.transient_failures.get(path, 0)
        if remaining > 0:
            behavior.transient_failures[path] = remaining - 1
            self._send(500, {"error": "transient"})
            return
        override = behavior.status_overrides.get(path)
        if override is not None:
            self._send(override, {"error": "injected"})
            return
        if path in behavior.malformed_paths:
            self._send_raw(200, b"{not-json")
            return
        if method == "POST":
            body = self._read_json_body()
            self._apply_post(path, body, behavior)
        payload = self._payload_for(path, behavior)
        if payload is _MISSING:
            self._send(404, {"error": "not_found", "path": path})
            return
        if path == "/liveclientdata/activeplayer":
            self._send(behavior.activeplayer_status, behavior.activeplayer_body)
            return
        self._send(200, payload)

    def _apply_post(self, path: str, body: dict[str, Any], behavior: FakeReplayBehavior) -> None:
        """Mutate fake state from a POST. Delayed seek sleeps before applying time."""
        if path == "/replay/playback":
            behavior.post_log.append((path, dict(body)))
            if "time" in body and behavior.seek_delay_s > 0:
                time.sleep(behavior.seek_delay_s)
            if "paused" in body:
                behavior.playback["paused"] = bool(body["paused"])
            if "speed" in body:
                behavior.playback["speed"] = body["speed"]
            if "time" in body:
                requested = float(body["time"])
                if behavior.seek_misses_remaining > 0:
                    behavior.seek_misses_remaining -= 1
                    behavior.playback["time"] = requested + 2.0
                else:
                    behavior.playback["time"] = requested
                if behavior.seeking_stuck:
                    behavior.playback["seeking"] = True
                elif behavior.seeking_polls_remaining > 0:
                    behavior.playback["seeking"] = True
                else:
                    behavior.playback["seeking"] = False
            return
        if path == "/replay/render" and isinstance(body, dict):
            behavior.render.update(body)
            return
        if path == "/replay/recording" and isinstance(body, dict):
            behavior.recording.update(body)
            return
        if path == "/replay/sequence" and isinstance(body, dict):
            behavior.sequence.update(body)

    def _payload_for(self, path: str, behavior: FakeReplayBehavior) -> Any:
        if path == "/replay/playback":
            if behavior.playback.get("seeking") and behavior.seeking_polls_remaining > 0:
                behavior.seeking_polls_remaining -= 1
                if behavior.seeking_polls_remaining <= 0 and not behavior.seeking_stuck:
                    behavior.playback["seeking"] = False
            snapshot = dict(behavior.playback)
            if not behavior.time_frozen and not snapshot.get("paused") and not snapshot.get(
                "seeking"
            ):
                behavior.playback["time"] = float(snapshot.get("time") or 0.0) + 1.0
            return snapshot
        if path == "/replay/game":
            return dict(behavior.game)
        if path == "/replay/render":
            return dict(behavior.render)
        if path == "/replay/recording":
            return dict(behavior.recording)
        if path == "/replay/sequence":
            return dict(behavior.sequence)
        if path == "/liveclientdata/gamestats":
            return dict(behavior.gamestats)
        if path == "/liveclientdata/eventdata":
            return dict(behavior.eventdata)
        if path == "/liveclientdata/playerlist":
            return list(behavior.playerlist)
        if path == "/liveclientdata/activeplayername":
            return behavior.activeplayername
        if path in {"/swagger/v3/openapi.json", "/swagger/v2/swagger.json"}:
            return {
                "paths": {
                    "/replay/playback": {},
                    "/replay/game": {},
                    "/liveclientdata/gamestats": {},
                }
            }
        if path == "/liveclientdata/activeplayer":
            return dict(behavior.activeplayer_body)
        return _MISSING

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _send(self, status: int, payload: Any) -> None:
        data = json.dumps(payload).encode("utf-8")
        self._send_raw(status, data, content_type="application/json")

    def _send_raw(self, status: int, data: bytes, *, content_type: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


_MISSING = object()
