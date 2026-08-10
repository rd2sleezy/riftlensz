from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.api.live_client import LiveClientDataClient
from riftlens.replay_host.api.models import ActivePlayerError, ReplayPlayback
from riftlens.replay_host.api.replay_client import ReplayApiClient
from riftlens.replay_host.api.tls import riot_ca_path
from tests.fakes.fake_replay_server import FakeReplayApiServer, FakeReplayBehavior

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "replay_api"
SAMPLES = FIXTURES / "16.15" / "playback_samples.json"
SESSION = FIXTURES / "16.15" / "session.jsonl"


def _clients(
    server: FakeReplayApiServer,
    *,
    timeout_s: float = 5.0,
    connect_timeout_s: float = 2.0,
    max_retries: int = 2,
) -> tuple[ReplayApiClient, LiveClientDataClient]:
    origin = server.origin
    ca = str(server.ca_file)
    replay = ReplayApiClient(
        origin,
        ca_file=ca,
        timeout_s=timeout_s,
        connect_timeout_s=connect_timeout_s,
        max_retries=max_retries,
    )
    live = LiveClientDataClient(
        origin,
        ca_file=ca,
        timeout_s=timeout_s,
        connect_timeout_s=connect_timeout_s,
        max_retries=max_retries,
    )
    return replay, live


def _closed_loopback_origin() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return f"https://127.0.0.1:{port}"


def test_successful_playback_get() -> None:
    with FakeReplayApiServer() as server:
        replay, _live = _clients(server)
        playback = replay.get_playback()
        assert playback.paused is False
        assert playback.seeking is False
        assert playback.length > 0
        state = playback.to_playback_state()
        assert state.length_ms == round(playback.length * 1000)
        assert state.t_source_ms == round(playback.time * 1000)


def test_successful_playback_post_readback() -> None:
    with FakeReplayApiServer() as server:
        replay, _live = _clients(server)
        playback = replay.set_playback(paused=True, time=60.0, speed=1.0)
        assert playback is not None
        assert playback.paused is True
        assert playback.time == 60.0
        assert playback.speed == 1.0
        assert playback.seeking is False


def test_malformed_playback_response() -> None:
    behavior = FakeReplayBehavior(malformed_paths={"/replay/playback"})
    with FakeReplayApiServer(behavior) as server:
        replay, _live = _clients(server, max_retries=0)
        with pytest.raises(ReplayError) as exc_info:
            replay.get_playback()
        assert exc_info.value.code is ReplayErrorCode.REPLAY_API_UNAVAILABLE
        assert exc_info.value.details.get("reason") == "malformed_json"


def test_http_500() -> None:
    behavior = FakeReplayBehavior(status_overrides={"/replay/playback": 500})
    with FakeReplayApiServer(behavior) as server:
        replay, _live = _clients(server, max_retries=0)
        with pytest.raises(ReplayError) as exc_info:
            replay.get_playback()
        assert exc_info.value.code is ReplayErrorCode.REPLAY_API_UNAVAILABLE
        assert exc_info.value.details.get("status") == 500


def test_timeout() -> None:
    behavior = FakeReplayBehavior(slow_paths={"/replay/playback": 1.2})
    with FakeReplayApiServer(behavior) as server:
        replay, _live = _clients(server, timeout_s=0.2, max_retries=0)
        with pytest.raises(ReplayError) as exc_info:
            replay.get_playback()
        assert exc_info.value.details.get("reason") == "timeout"


def test_connection_refused() -> None:
    replay = ReplayApiClient(
        _closed_loopback_origin(),
        ca_file=str(FIXTURES / "unrelated_cert.pem"),
        timeout_s=3.0,
        connect_timeout_s=3.0,
        max_retries=0,
    )
    with pytest.raises(ReplayError) as exc_info:
        replay.get_playback()
    assert exc_info.value.code is ReplayErrorCode.REPLAY_API_UNAVAILABLE
    assert exc_info.value.details.get("reason") == "connect_failed"


def test_connection_drop() -> None:
    behavior = FakeReplayBehavior(drop_next=1)
    with FakeReplayApiServer(behavior) as server:
        replay, _live = _clients(server, max_retries=0)
        with pytest.raises(ReplayError) as exc_info:
            replay.get_playback()
        assert exc_info.value.code in {
            ReplayErrorCode.REPLAY_API_UNAVAILABLE,
            ReplayErrorCode.REPLAY_API_TLS,
        }


def test_delayed_seek_response() -> None:
    behavior = FakeReplayBehavior(seek_delay_s=0.15)
    with FakeReplayApiServer(behavior) as server:
        replay, _live = _clients(server, timeout_s=3.0)
        playback = replay.set_playback(paused=True, time=180.0)
        assert playback is not None
        assert playback.time == 180.0
        assert playback.seeking is False


def test_stuck_seeking() -> None:
    behavior = FakeReplayBehavior(seeking_stuck=True)
    with FakeReplayApiServer(behavior) as server:
        replay, _live = _clients(server)
        playback = replay.set_playback(time=90.0)
        assert playback is not None
        assert playback.time == 90.0
        assert playback.seeking is True


def test_playback_time_not_advancing() -> None:
    behavior = FakeReplayBehavior(time_frozen=True)
    with FakeReplayApiServer(behavior) as server:
        replay, _live = _clients(server)
        first = replay.get_playback()
        second = replay.get_playback()
        assert first.paused is False
        assert first.time == second.time


def test_transient_500_is_retried_then_succeeds() -> None:
    behavior = FakeReplayBehavior(transient_failures={"/replay/playback": 2})
    with FakeReplayApiServer(behavior) as server:
        replay, _live = _clients(server, max_retries=2)
        playback = replay.get_playback()
        assert playback.length > 0


def test_http_400_is_not_retried() -> None:
    behavior = FakeReplayBehavior(status_overrides={"/replay/playback": 400})
    with FakeReplayApiServer(behavior) as server:
        replay, _live = _clients(server, max_retries=2)
        with pytest.raises(ReplayError) as exc_info:
            replay.get_playback()
        assert exc_info.value.details.get("status") == 400


def test_playback_schema_drift_is_typed() -> None:
    behavior = FakeReplayBehavior(playback={"paused": True, "length": 10.0})
    with FakeReplayApiServer(behavior) as server:
        replay, _live = _clients(server, max_retries=0)
        with pytest.raises(ReplayError) as exc_info:
            replay.get_playback()
        assert exc_info.value.code is ReplayErrorCode.PLAYBACK_UNREADABLE


def test_optional_unsupported_replay_endpoint_is_not_fatal() -> None:
    with FakeReplayApiServer() as server:
        replay, _live = _clients(server)
        assert replay.try_get_json("/replay/not-a-documented-endpoint") is None
        spec = replay.try_get_json("/swagger/v3/openapi.json")
        assert isinstance(spec, dict)
        assert "/replay/playback" in spec["paths"]


def test_live_client_parsing_and_optional_activeplayer() -> None:
    with FakeReplayApiServer() as server:
        _replay, live = _clients(server)
        stats = live.get_gamestats()
        assert stats.gameTime == 12.5
        assert stats.mapName == "Map11"
        events = live.get_eventdata()
        assert events.Events[1].EventTime == 95.2
        players = live.get_playerlist()
        dumped = players[0].model_dump()
        assert dumped.get("championName") == "Ahri"
        assert live.get_activeplayer() is None
        assert live.get_activeplayername() == ""


def test_optional_lcd_404_is_not_fatal() -> None:
    behavior = FakeReplayBehavior(activeplayer_status=404)
    with FakeReplayApiServer(behavior) as server:
        _replay, live = _clients(server)
        assert live.get_activeplayer() is None
        assert live.get_gamestats().gameTime == 12.5


def test_activeplayer_error_body_matches_r0_shape() -> None:
    model = ActivePlayerError.model_validate(
        {
            "errorCode": "RPC_ERROR",
            "httpStatus": 400,
            "implementationDetails": "",
            "message": "Unable to get active player data",
        }
    )
    assert model.httpStatus == 400
    assert model.errorCode == "RPC_ERROR"


def test_tls_success_with_pinned_server_cert() -> None:
    with FakeReplayApiServer() as server:
        replay = ReplayApiClient(server.origin, ca_file=str(server.ca_file), max_retries=0)
        assert replay.get_game().processID == 14520


def test_tls_mismatch_is_typed() -> None:
    with FakeReplayApiServer() as server:
        replay = ReplayApiClient(
            server.origin,
            ca_file=str(riot_ca_path()),
            max_retries=0,
            timeout_s=2.0,
        )
        with pytest.raises(ReplayError) as exc_info:
            replay.get_playback()
        assert exc_info.value.code is ReplayErrorCode.REPLAY_API_TLS


def test_loopback_only_enforced() -> None:
    for origin in (
        "https://example.com:2999",
        "https://localhost:2999",
        "http://127.0.0.1:2999",
        "https://0.0.0.0:2999",
        "https://[::1]:2999",
    ):
        with pytest.raises(ReplayError) as exc_info:
            ReplayApiClient(origin)
        assert exc_info.value.details.get("reason") == "invalid_origin"


def test_transcript_playback_samples_validate() -> None:
    payload = json.loads(SAMPLES.read_text(encoding="utf-8"))
    assert payload["live_http_status"]["/liveclientdata/activeplayer"] == 400
    for sample in payload["playback_samples"]:
        model = ReplayPlayback.model_validate(sample)
        assert model.length > 0
        state = model.to_playback_state()
        assert state.speed_milli == 1000


def test_session_jsonl_playback_snapshot_is_compatible() -> None:
    found = 0
    for line in SESSION.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        data = record.get("data")
        if not isinstance(data, dict):
            continue
        if {"length", "paused", "seeking", "speed", "time"} <= set(data):
            ReplayPlayback.model_validate(data)
            found += 1
    assert found >= 1


def test_render_recording_sequence_transport_only() -> None:
    with FakeReplayApiServer() as server:
        replay, _live = _clients(server)
        assert replay.get_render().fogOfWar is True
        recording = replay.get_recording()
        assert recording.recording is False
        assert replay.get_sequence().playbackSpeed == 1.0


def test_real_machine_adapter_smoke_if_replay_open() -> None:
    try:
        replay = ReplayApiClient(timeout_s=1.0, max_retries=0)
        playback = replay.get_playback()
    except ReplayError as exc:
        if exc.code in {ReplayErrorCode.REPLAY_API_UNAVAILABLE, ReplayErrorCode.REPLAY_API_TLS}:
            pytest.skip(f"no live replay on 2999: {exc.code}")
        raise
    assert playback.length > 0
    live = LiveClientDataClient(timeout_s=1.0, max_retries=0)
    try:
        stats = live.get_gamestats()
    except ReplayError as exc:
        assert exc.code is ReplayErrorCode.LIVE_CLIENT_DATA_UNAVAILABLE
        return
    assert stats.gameTime >= 0
    assert live.get_activeplayer() is None or isinstance(live.get_activeplayer(), dict)
