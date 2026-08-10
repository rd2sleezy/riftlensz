from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from riftlens.adapters.db.repositories import SqlMatchRepository
from riftlens.domain.ports import MatchRecord
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.main import create_app
from riftlens.replay_host.session import ReplaySessionPhase
from tests.fakes.fake_replay_host import FakeReplayHost
from tests.fakes.fake_replay_runtime import write_tiny_rofl

_AUTH = {"Authorization": "Bearer test-token"}
_MATCH = "NA1_5617764200"


async def _seed_match(client: TestClient, match_id: str = _MATCH) -> None:
    repo = SqlMatchRepository(client.app.state.session_factory)
    await repo.upsert_match(
        MatchRecord(
            match_id=match_id,
            platform="na1",
            region="americas",
            queue_id=420,
            map_id=11,
            game_version="16.9.1.123",
            patch="16.9",
            game_creation=1,
            game_start=1,
            game_duration_ms=1_800_000,
            game_end_ts=1_800_001,
            winning_team=100,
            raw_match_blob=None,
            raw_timeline_blob=None,
            ingested_at=2,
        )
    )


def _client(settings, host: FakeReplayHost) -> TestClient:
    app = create_app(settings=settings, token="test-token", replay_host=host)
    return TestClient(app)


def test_gameplay_requires_bearer(settings) -> None:
    host = FakeReplayHost()
    with _client(settings, host) as client:
        assert client.get("/gameplay/status", params={"match_id": _MATCH}).status_code == 401


async def test_import_success_does_not_launch(settings, tmp_path: Path) -> None:
    host = FakeReplayHost()
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    with _client(settings, host) as client:
        await _seed_match(client)
        response = client.post(
            "/gameplay/import",
            headers=_AUTH,
            json={"path": str(rofl), "match_id": _MATCH},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["source_id"]
    assert body["match_id"] == _MATCH
    assert body["status"]["source_status"] == "linked"
    assert body["status"]["session_phase"] == "IDLE"
    assert body["status"]["session_reached_ready"] is False
    assert "source_type" not in body["status"]
    assert host.open_count == 0


async def test_import_invalid_rofl(settings, tmp_path: Path) -> None:
    host = FakeReplayHost()
    bad = tmp_path / "NA1-5617764200.rofl"
    bad.write_bytes(b"not a replay")
    with _client(settings, host) as client:
        await _seed_match(client)
        response = client.post(
            "/gameplay/import",
            headers=_AUTH,
            json={"path": str(bad), "match_id": _MATCH},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] in {
        ReplayErrorCode.ROFL_NOT_RECOGNISED.value,
        ReplayErrorCode.ROFL_INVALID.value,
        ReplayErrorCode.ROFL_UNREADABLE.value,
    }
    assert body["error"]["message"]
    assert "something went wrong" not in body["error"]["message"].lower()
    assert host.open_count == 0


async def test_import_match_not_ingested(settings, tmp_path: Path) -> None:
    host = FakeReplayHost()
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    with _client(settings, host) as client:
        response = client.post(
            "/gameplay/import",
            headers=_AUTH,
            json={"path": str(rofl), "match_id": _MATCH},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == ReplayErrorCode.MATCH_NOT_INGESTED.value
    assert body["error"]["suggested_action"] == "ingest_match"


async def test_linked_status_idle_after_import(settings, tmp_path: Path) -> None:
    host = FakeReplayHost()
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    with _client(settings, host) as client:
        await _seed_match(client)
        imported = client.post(
            "/gameplay/import",
            headers=_AUTH,
            json={"path": str(rofl), "match_id": _MATCH},
        ).json()
        status = client.get(
            "/gameplay/status",
            headers=_AUTH,
            params={"match_id": _MATCH, "source_id": imported["source_id"]},
        ).json()
    assert status["active_source_id"] == imported["source_id"]
    assert status["session_phase"] == "IDLE"
    assert status["session_reached_ready"] is False
    assert status["file_present"] is True
    assert "LIVE_CLIENT_DATA" in status["capabilities"]


async def test_open_ready_only_after_host_ready(settings, tmp_path: Path) -> None:
    host = FakeReplayHost(auto_ready=False)
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    with _client(settings, host) as client:
        await _seed_match(client)
        source_id = client.post(
            "/gameplay/import",
            headers=_AUTH,
            json={"path": str(rofl), "match_id": _MATCH},
        ).json()["source_id"]
        opened = client.post(
            "/gameplay/open",
            headers=_AUTH,
            json={"source_id": source_id, "match_id": _MATCH},
        ).json()
        assert opened["ok"] is False
        assert opened["session_reached_ready"] is False
        assert opened["session_phase"] == "CONNECTING"
        host.force_phase(ReplaySessionPhase.READY, reached_ready=True)
        status = client.get(
            "/gameplay/status",
            headers=_AUTH,
            params={"match_id": _MATCH, "source_id": source_id},
        ).json()
    assert status["session_phase"] == "READY"
    assert status["session_reached_ready"] is True


async def test_open_then_reveal_and_close(settings, tmp_path: Path) -> None:
    host = FakeReplayHost()
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    with _client(settings, host) as client:
        await _seed_match(client)
        source_id = client.post(
            "/gameplay/import",
            headers=_AUTH,
            json={"path": str(rofl), "match_id": _MATCH},
        ).json()["source_id"]
        opened = client.post(
            "/gameplay/open",
            headers=_AUTH,
            json={"source_id": source_id, "match_id": _MATCH},
        ).json()
        assert opened["ok"] is True
        assert opened["session_reached_ready"] is True
        revealed = client.post(
            "/gameplay/reveal",
            headers=_AUTH,
            json={
                "source_id": source_id,
                "match_id": _MATCH,
                "game_t_ms": 140_000,
                "lead_in_ms": 8_000,
            },
        ).json()
        assert revealed["ok"] is True
        assert revealed["target_game_ms"] == 132_000
        assert revealed["lead_in_ms"] == 8_000
        assert host.reveal_count == 1
        closed = client.post(
            "/gameplay/close",
            headers=_AUTH,
            json={"source_id": source_id, "match_id": _MATCH},
        ).json()
        assert closed["ok"] is True
        assert closed["status"]["session_phase"] == "CLOSED"
        assert closed["status"]["source_status"] == "linked"
        assert host.close_count == 1
        host.reset_live_session()
        restarted = client.get(
            "/gameplay/status",
            headers=_AUTH,
            params={"match_id": _MATCH, "source_id": source_id},
        ).json()
    assert restarted["source_status"] == "linked"
    assert restarted["session_phase"] == "IDLE"
    assert restarted["session_reached_ready"] is False


async def test_session_lost_and_seek_failure(settings, tmp_path: Path) -> None:
    host = FakeReplayHost(session_lost=True)
    rofl = write_tiny_rofl(tmp_path / "NA1-5617764200.rofl")
    with _client(settings, host) as client:
        await _seed_match(client)
        source_id = client.post(
            "/gameplay/import",
            headers=_AUTH,
            json={"path": str(rofl), "match_id": _MATCH},
        ).json()["source_id"]
        client.post(
            "/gameplay/open",
            headers=_AUTH,
            json={"source_id": source_id, "match_id": _MATCH},
        )
        lost = client.get(
            "/gameplay/status",
            headers=_AUTH,
            params={"match_id": _MATCH, "source_id": source_id},
        ).json()
        assert lost["error"]["code"] == ReplayErrorCode.SESSION_LOST.value
        host.session_lost = False
        host.reveal_error = ReplayError(ReplayErrorCode.SEEK_FAILED)
        host.force_phase(ReplaySessionPhase.READY, reached_ready=True)
        failed = client.post(
            "/gameplay/reveal",
            headers=_AUTH,
            json={"source_id": source_id, "match_id": _MATCH, "game_t_ms": 90_000},
        ).json()
    assert failed["ok"] is False
    assert failed["error"]["code"] == ReplayErrorCode.SEEK_FAILED.value


async def test_platform_unsupported_environment(settings) -> None:
    host = FakeReplayHost(supported=False)
    with _client(settings, host) as client:
        env = client.get("/gameplay/environment", headers=_AUTH).json()
        status = client.get(
            "/gameplay/status", headers=_AUTH, params={"match_id": _MATCH}
        ).json()
    assert env["native_replay_supported"] is False
    assert env["error"]["code"] == ReplayErrorCode.PLATFORM_UNSUPPORTED.value
    assert status["native_replay_supported"] is False
    assert status["sources"] == []
