from __future__ import annotations

import time

from fastapi.testclient import TestClient
from riftlens.config import Settings
from riftlens.main import create_app

_AUTH = {"Authorization": "Bearer test-token"}
FIXTURE = "NA1_fixture_b"


def _wait(client: TestClient, job_id: str, timeout_s: float = 120.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout_s
    payload: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/jobs/{job_id}", headers=_AUTH)
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
            return payload
        time.sleep(0.15)
    raise AssertionError(f"job {job_id} did not finish: {payload}")


def test_ac2_null_provider_full_review(client: TestClient) -> None:
    created = client.post(
        "/jobs/analyze",
        headers=_AUTH,
        json={"match_id": FIXTURE, "participant_id": 5, "llm_provider": "null"},
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]
    payload = _wait(client, job_id)
    assert payload["status"] == "COMPLETED"
    review_id = payload["review_id"]
    assert isinstance(review_id, str) and review_id
    review = client.get(f"/reviews/{review_id}", headers=_AUTH)
    assert review.status_code == 200
    body = review.json()
    items = body["focus_items"] + body["secondary_items"] + body["strengths"]
    assert items
    assert all(str(item["body"]).strip() for item in items)
    assert body["llm_provider"] == "null"


def test_ac5_diagnostics_timings(client: TestClient) -> None:
    created = client.post(
        "/jobs/analyze",
        headers=_AUTH,
        json={"match_id": FIXTURE, "participant_id": 5, "llm_provider": "null"},
    )
    job_id = created.json()["job_id"]
    payload = _wait(client, job_id)
    assert payload["status"] == "COMPLETED"
    diag = client.get("/diagnostics/last-job", headers=_AUTH)
    assert diag.status_code == 200
    body = diag.json()
    wall = int(body["wall_ms"] or 0)
    summed = int(body["stage_timing_sum_ms"])
    assert wall > 0
    assert abs(summed - wall) / wall <= 0.05 or abs(summed - wall) <= 250


def test_ac4_cancel_during_ingest_video(settings: Settings) -> None:
    settings.ingest_video_hold_ms = 8_000
    app = create_app(settings=settings, token="test-token")
    with TestClient(app) as client:
        created = client.post(
            "/jobs/analyze",
            headers=_AUTH,
            json={
                "match_id": FIXTURE,
                "participant_id": 5,
                "media_asset_id": "01H11MEDIAHOLD000000000001",
                "llm_provider": "null",
            },
        )
        job_id = created.json()["job_id"]
        stage = ""
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            snapshot = client.get(f"/jobs/{job_id}", headers=_AUTH).json()
            stage = str(snapshot.get("current_stage") or "")
            if stage == "ingest_video":
                break
            time.sleep(0.05)
        started = time.monotonic()
        cancelled = client.delete(f"/jobs/{job_id}", headers=_AUTH)
        assert cancelled.status_code == 200
        payload = _wait(client, job_id, timeout_s=6.0)
        elapsed = time.monotonic() - started
        assert payload["status"] == "CANCELLED"
        assert elapsed < 3.0


def test_finding_feedback_and_series(client: TestClient) -> None:
    created = client.post(
        "/jobs/analyze",
        headers=_AUTH,
        json={"match_id": FIXTURE, "participant_id": 5, "llm_provider": "null"},
    )
    payload = _wait(client, created.json()["job_id"])
    review = client.get(f"/reviews/{payload['review_id']}", headers=_AUTH).json()
    finding_id = review["findings"][0]["id"]
    feedback = client.post(
        f"/findings/{finding_id}/feedback",
        headers=_AUTH,
        json={"verdict": "helpful", "note": "good catch"},
    )
    assert feedback.status_code == 200
    series = client.get(
        f"/reviews/{payload['review_id']}/series",
        headers=_AUTH,
        params={"kinds": "gold,cs", "stride": 120000},
    )
    assert series.status_code == 200
    body = series.json()
    assert "gold" in body["series"]
    assert body["stride_ms"] == 120000
