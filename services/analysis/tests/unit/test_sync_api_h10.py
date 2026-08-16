from __future__ import annotations

import json

from fastapi.testclient import TestClient
from riftlens.adapters.db.repositories import (
    SqlGameplayRepository,
    SqlMatchRepository,
    SqlMediaRepository,
    SqlSyncRepository,
)
from riftlens.domain.clock_store import SOURCE_STATUS_LINKED, SOURCE_TYPE_ROFL
from riftlens.domain.ids import new_ulid
from riftlens.domain.ports import GameplaySourceRecord, MatchRecord, MediaAssetRecord, SyncMapRecord
from riftlens.pipeline.sync.fitter import ALGO_VERSION

_AUTH = {"Authorization": "Bearer test-token"}


def _reading(t_video_ms: int, t_game_ms: int | None, confidence: float = 0.95) -> dict[str, object]:
    return {
        "t_video_ms": t_video_ms,
        "t_game_ms": t_game_ms,
        "confidence": confidence,
        "in_game": True,
    }


def _linear_payload(offset: int = 40_000, n: int = 40) -> list[dict[str, object]]:
    return [_reading(i * 1_000, i * 1_000 + offset) for i in range(n)]


async def _seed_match(client: TestClient, match_id: str) -> None:
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


async def _seed_media(client: TestClient, *, asset_id: str, content_hash: str, path: str) -> None:
    repo = SqlMediaRepository(client.app.state.session_factory)
    await repo.upsert_asset(
        MediaAssetRecord(
            id=asset_id,
            content_hash=content_hash,
            original_path=path,
            playable_path=None,
            proxy_path=None,
            thumbnail_sheet_path=None,
            container="mp4",
            codec="h264",
            pix_fmt="yuv420p",
            width=1920,
            height=1080,
            fps_num=30,
            fps_den=1,
            duration_ms=120_000,
            size_bytes=12,
            source_kind="PLAYER_POV",
            layout_profile_id=None,
            quality_score=None,
            imported_at=3,
            last_accessed_at=3,
        )
    )


def test_manual_sync_regression(client: TestClient) -> None:
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
    assert built.json()["quality"]["method"] == "manual"


async def test_auto_sync_and_get(client: TestClient) -> None:
    with client:
        match_id = "NA1_h10_api"
        asset_id = new_ulid()
        digest = "c" * 64
        await _seed_match(client, match_id)
        await _seed_media(client, asset_id=asset_id, content_hash=digest, path="/tmp/h10.mp4")
        response = client.post(
            "/sync/auto",
            headers=_AUTH,
            json={
                "match_id": match_id,
                "media_asset_id": asset_id,
                "content_hash": digest,
                "video_duration_ms": 40_000,
                "match_duration_ms": 1_800_000,
                "readings": _linear_payload(),
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["sync_map"]["quality"]["method"] == "clock_ocr"
        assert body["algo_version"] == ALGO_VERSION
        assert abs(body["sync_map"]["segments"][0]["offset_ms"] - 40_000) <= 100
        sync_id = body["id"]
        fetched = client.get(f"/sync/{sync_id}", headers=_AUTH)
        assert fetched.status_code == 200
        assert fetched.json()["sync_map"]["match_id"] == match_id


async def test_auto_sync_cache_hit_and_version_miss(client: TestClient) -> None:
    with client:
        match_id = "NA1_h10_cache"
        asset_id = new_ulid()
        digest = "d" * 64
        await _seed_match(client, match_id)
        await _seed_media(client, asset_id=asset_id, content_hash=digest, path="/tmp/h10c.mp4")
        payload = {
            "match_id": match_id,
            "media_asset_id": asset_id,
            "content_hash": digest,
            "video_duration_ms": 40_000,
            "readings": _linear_payload(),
        }
        first = client.post("/sync/auto", headers=_AUTH, json=payload)
        assert first.status_code == 200 and first.json()["ok"] is True
        second = client.post("/sync/auto", headers=_AUTH, json=payload)
        assert second.json()["cached"] is True
        other_match = "NA1_h10_cache_other"
        await _seed_match(client, other_match)
        other = client.post(
            "/sync/auto",
            headers=_AUTH,
            json={**payload, "match_id": other_match},
        )
        assert other.json()["ok"] is True
        assert other.json()["cached"] is False
        syncs = SqlSyncRepository(client.app.state.session_factory)
        row = await syncs.get_by_media_and_match(asset_id, match_id)
        assert row is not None
        quality = json.loads(row.quality)
        quality["algo_version"] = "h10.clock_ocr.v0"
        await syncs.upsert(
            SyncMapRecord(
                id=row.id,
                media_asset_id=row.media_asset_id,
                match_id=row.match_id,
                method=row.method,
                segments=row.segments,
                pauses=row.pauses,
                quality=json.dumps(quality),
                verified=row.verified,
                created_at=row.created_at,
            )
        )
        refreshed = client.post("/sync/auto", headers=_AUTH, json=payload)
        assert refreshed.json()["cached"] is False
        assert ALGO_VERSION == "h10.clock_ocr.v1"


async def test_auto_sync_does_not_destroy_manual_on_failure(client: TestClient) -> None:
    with client:
        match_id = "NA1_h10_manual"
        asset_id = new_ulid()
        digest = "e" * 64
        await _seed_match(client, match_id)
        await _seed_media(client, asset_id=asset_id, content_hash=digest, path="/tmp/h10m.mp4")
        syncs = SqlSyncRepository(client.app.state.session_factory)
        manual_id = new_ulid()
        await syncs.upsert(
            SyncMapRecord(
                id=manual_id,
                media_asset_id=asset_id,
                match_id=match_id,
                method="manual",
                segments="[]",
                pauses="[]",
                quality="{}",
                verified=0,
                created_at=9,
            )
        )
        failed = client.post(
            "/sync/auto",
            headers=_AUTH,
            json={
                "match_id": match_id,
                "media_asset_id": asset_id,
                "content_hash": digest,
                "video_duration_ms": 40_000,
                "readings": [_reading(0, None, 0.0), _reading(1_000, 1_000, 0.2)],
            },
        )
        assert failed.status_code == 200
        assert failed.json()["ok"] is False
        assert failed.json()["code"] == "INSUFFICIENT_READINGS"
        kept = await syncs.get(manual_id)
        assert kept is not None
        assert kept.method == "manual"


async def test_auto_sync_rejects_rofl_source(client: TestClient, tmp_path) -> None:
    with client:
        match_id = "NA1_h10_rofl"
        await _seed_match(client, match_id)
        path = tmp_path / "NA1_h10_rofl.rofl"
        path.write_bytes(b"RIOT")
        gameplay = SqlGameplayRepository(client.app.state.session_factory)
        source_id = new_ulid()
        await gameplay.upsert_source(
            GameplaySourceRecord(
                id=source_id,
                match_id=match_id,
                source_type=SOURCE_TYPE_ROFL,
                source_uri=str(path),
                content_hash=None,
                display_name="NA1_h10_rofl.rofl",
                duration_ms=1_800_000,
                status=SOURCE_STATUS_LINKED,
                platform_scope="any",
                created_at=4,
                updated_at=4,
            )
        )
        response = client.post(
            "/sync/auto",
            headers=_AUTH,
            json={
                "match_id": match_id,
                "gameplay_source_id": source_id,
                "video_duration_ms": 40_000,
                "readings": _linear_payload(),
            },
        )
        assert response.status_code == 200
        assert response.json()["code"] == "UNSUPPORTED_SOURCE"


def test_auto_sync_multiple_games_payload(client: TestClient) -> None:
    game1 = [_reading(i * 1_000, i * 1_000) for i in range(600)]
    game2 = [_reading(600_000 + i * 1_000, i * 1_000) for i in range(600)]
    response = client.post(
        "/sync/auto",
        headers=_AUTH,
        json={
            "match_id": "NA1_h10_multi",
            "video_duration_ms": 1_200_000,
            "readings": game1 + game2,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["code"] == "MULTIPLE_GAMES"
    assert body["boundaries_video_ms"]


def test_get_sync_404(client: TestClient) -> None:
    with client:
        response = client.get("/sync/01H10MISSING000000000000000", headers=_AUTH)
        assert response.status_code == 404


def test_uncovered_seek_stays_null(client: TestClient) -> None:
    built = client.post(
        "/sync/auto",
        headers=_AUTH,
        json={
            "match_id": "NA1_h10_seek",
            "video_duration_ms": 30_000,
            "readings": _linear_payload(offset=600_000, n=30),
        },
    )
    assert built.json()["ok"] is True
    seek = client.post(
        "/sync/seek",
        headers=_AUTH,
        json={"t_game_ms": 0, "sync_map": built.json()["sync_map"]},
    )
    assert seek.status_code == 200
    assert seek.json()["covered"] is False
    assert seek.json()["t_video_ms"] is None
