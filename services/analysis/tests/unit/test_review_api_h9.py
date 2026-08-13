from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from riftlens.domain.enums import EvidenceKind, IssueType, Role, Severity, Source
from riftlens.domain.evidence import Evidence
from riftlens.domain.finding import Finding
from riftlens.domain.review import CoachingItem, MetricSnapshot, Review
from riftlens.pipeline.assemble.review_presentation import (
    UNPAIRED_FIXTURE_WARNING,
    review_to_presentation,
    save_review_presentation,
)

_AUTH = {"Authorization": "Bearer test-token"}


def _finding() -> Finding:
    return Finding(
        id="01H9FINDING000000000000001",
        rule_id="R-001",
        rule_version=1,
        concept_id="RISK.DEATH_CAUSE",
        t_ms=140_000,
        severity=Severity.HIGH,
        confidence=0.8,
        title="Died on a pushed wave",
        evidence=(
            Evidence(
                kind=EvidenceKind.FACT,
                label="info_age_ms",
                value=59_000,
                source=Source.DERIVED,
                t_ms=140_000,
                confidence=0.7,
            ),
        ),
        explanation="Jungler unseen.",
        alternative="Hold wave.",
    )


def _review() -> Review:
    finding = _finding()
    item = CoachingItem(
        id="01H9ITEM000000000000000001",
        root_concept_id="RISK.DEATH_CAUSE",
        rank=1,
        is_focus=True,
        is_strength=False,
        issue_type=IssueType.TACTICAL,
        impact_score=12.0,
        gold_equivalent=900.0,
        occurrences=2,
        confidence=0.8,
        title="Know the jungler",
        body="Likely: you died on a pushed wave.",
        the_fix="Ward before pushing.",
        next_game_check="Die less on a crash.",
        exemplar_finding_id=finding.id,
        finding_ids=(finding.id,),
        evidence_timestamps_ms=(140_000,),
        grouping_reason="same concept",
        certainty="likely",
        cluster_id="c1",
        cost_summary="~900g",
    )
    return Review(
        id="01H9REVIEW0000000000000001",
        player_id="p1",
        match_id="NA1_fixture_b",
        participant_id=5,
        champion="Ahri",
        role=Role.MIDDLE,
        rank="SILVER",
        patch="15.16",
        duration_ms=1_800_000,
        result="LOSS",
        rule_pack_version="1",
        engine_version="0.1.0",
        llm_provider="null",
        status="COMPLETE",
        summary_text="Focus: Know the jungler.",
        findings=(finding,),
        clusters=(),
        grouping_log=(),
        focus_items=(item,),
        secondary_items=(),
        strengths=(),
        metrics=(
            MetricSnapshot(
                metric_id="M-01",
                value=6.1,
                unit="cs/min",
                phase="ALL",
                confidence=1.0,
                baseline_percentile=42.0,
            ),
        ),
        created_at=1,
        completed_at=1,
        unpaired_match_timeline=True,
    )


def test_reviews_require_bearer(client: TestClient) -> None:
    assert client.get("/reviews").status_code == 401


def test_list_reviews_empty(client: TestClient) -> None:
    response = client.get("/reviews", headers=_AUTH)
    assert response.status_code == 200
    assert response.json() == {"reviews": []}


def test_get_review_404(client: TestClient) -> None:
    response = client.get("/reviews/does-not-exist", headers=_AUTH)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_saved_presentation_round_trip(client: TestClient, settings: object) -> None:
    payload = review_to_presentation(_review(), fixture_id="NA1_fixture_b")
    save_review_presentation(settings.data_dir, payload)  # type: ignore[attr-defined]
    listed = client.get("/reviews", headers=_AUTH)
    assert listed.status_code == 200
    # Fixture trial reviews are hidden from the home list so Pyke trials stay gone.
    assert listed.json()["reviews"] == []
    fetched = client.get(f"/reviews/{payload['id']}", headers=_AUTH)
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["fixture_warning"] == UNPAIRED_FIXTURE_WARNING
    assert body["focus_items"][0]["evidence_timestamps_ms"] == [140_000]
    assert body["findings"][0]["evidence"][0]["confidence"] == 0.7
    assert body["findings"][0]["t_ms"] == 140_000
    assert body["metrics"][0]["metric_id"] == "M-01"


def test_unknown_fixture_rejected(client: TestClient) -> None:
    response = client.post(
        "/reviews/from-fixture",
        headers=_AUTH,
        json={"fixture_id": "NA1_not_real", "participant_id": 5},
    )
    assert response.status_code == 400


def test_from_fixture_builds_h8_review(client: TestClient) -> None:
    response = client.post(
        "/reviews/from-fixture",
        headers=_AUTH,
        json={"fixture_id": "NA1_fixture_b", "participant_id": 5, "rank": "SILVER"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["participant_id"] == 5
    assert body["unpaired_match_timeline"] is True
    assert body["fixture_warning"]
    assert len(body["focus_items"]) <= 3
    assert body["findings"]
    assert all(item["evidence"] for item in body["findings"])
    fetched = client.get(f"/reviews/{body['id']}", headers=_AUTH)
    assert fetched.status_code == 200
    listed = client.get("/reviews", headers=_AUTH)
    assert listed.status_code == 200
    assert not any(card["id"] == body["id"] for card in listed.json()["reviews"])


def test_manual_sync_and_seek_endpoints(client: TestClient) -> None:
    built = client.post(
        "/sync/manual",
        headers=_AUTH,
        json={
            "match_id": "NA1_x",
            "video_duration_ms": 300_000,
            "match_duration_ms": 1_800_000,
            "anchors": [{"t_video_ms": 15_000, "t_game_ms": 90_000}],
        },
    )
    assert built.status_code == 200, built.text
    sync = built.json()
    assert sync["quality"]["verdict"] == "DEGRADED"
    seek = client.post(
        "/sync/seek",
        headers=_AUTH,
        json={"t_game_ms": 90_000, "sync_map": sync},
    )
    assert seek.status_code == 200
    payload = seek.json()
    assert payload["t_video_ms"] == 15_000
    assert payload["seek_video_ms"] == 7_000
    assert payload["uncertain"] is True


def test_manual_sync_rejects_bad_slope(client: TestClient) -> None:
    response = client.post(
        "/sync/manual",
        headers=_AUTH,
        json={
            "match_id": "NA1_x",
            "video_duration_ms": 300_000,
            "anchors": [
                {"t_video_ms": 0, "t_game_ms": 0},
                {"t_video_ms": 60_000, "t_game_ms": 180_000},
            ],
        },
    )
    assert response.status_code == 400


def test_media_probe_missing_file(client: TestClient, tmp_path: Path) -> None:
    response = client.post(
        "/media/probe",
        headers=_AUTH,
        json={"path": str(tmp_path / "nope.mp4")},
    )
    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()


def test_presentation_quarantines_gold_per_second() -> None:
    finding = Finding(
        id="01H9FINDING000000000000002",
        rule_id="R-002",
        rule_version=1,
        concept_id="ECONOMY.SPEND",
        t_ms=10_000,
        severity=Severity.MEDIUM,
        confidence=0.6,
        title="Unspent",
        evidence=(
            Evidence(
                kind=EvidenceKind.FACT,
                label="frame goldPerSecond",
                value={"goldPerSecond": 2.04},
                source=Source.RIOT_TIMELINE,
                t_ms=10_000,
                confidence=0.4,
            ),
        ),
    )
    review = _review()
    dirty = Review(
        **{
            **review.__dict__,
            "findings": (finding,),
            "metrics": (
                MetricSnapshot(
                    metric_id="M-99",
                    value=1.0,
                    unit="x",
                    phase=None,
                    confidence=0.2,
                    detail={"healthRegen": 1.2},
                ),
            ),
        }
    )
    payload = review_to_presentation(dirty)
    assert payload["findings"][0]["evidence"][0]["quarantined"] is True
    assert payload["metrics"][0]["quarantined"] is True


def test_presentation_file_written_by_builder(tmp_path: Path) -> None:
    from riftlens.config import Settings
    from riftlens.pipeline.assemble.review_builder import build_review_from_dtos
    from tests.helpers.gst import load_fixture_pair

    settings = Settings(data_dir=tmp_path)
    match, timeline = load_fixture_pair("NA1_fixture_a")
    built = build_review_from_dtos(
        match, timeline, 5, persist=True, settings=settings, rank="UNRANKED"
    )
    saved = tmp_path / "reviews" / f"{built.review.id}.json"
    assert saved.is_file()
    body = json.loads(saved.read_text(encoding="utf-8"))
    assert body["id"] == built.review.id
    assert body["findings"]
