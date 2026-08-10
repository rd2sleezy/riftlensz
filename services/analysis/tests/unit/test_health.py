from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient
from riftlens import __version__
from riftlens.config import Settings
from riftlens.main import create_app


def test_health_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"
    assert body["version"] == __version__
    py = sys.version_info
    assert body["python"] == f"{py.major}.{py.minor}.{py.micro}"
    assert body["db_path"].endswith("riftlens.db")
    assert isinstance(body["uptime_ms"], int)
    assert body["uptime_ms"] >= 0


def test_health_bypasses_auth(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    app = create_app(settings=settings, token="secret")
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200


def test_non_health_requires_bearer(client: TestClient) -> None:
    denied = client.get("/no-such-route")
    assert denied.status_code == 401
    allowed = client.get("/no-such-route", headers={"Authorization": "Bearer test-token"})
    assert allowed.status_code == 404
