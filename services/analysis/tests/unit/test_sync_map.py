from __future__ import annotations

import pytest
from riftlens.domain.sync_map import (
    SEEK_LEAD_IN_MS,
    SyncAnchorInconsistent,
    SyncMap,
    SyncQuality,
    SyncSegment,
    build_manual_sync,
    seek_target,
)


def test_manual_one_anchor_maps_both_directions() -> None:
    sync = build_manual_sync(
        [(12_000, 90_000)],
        video_duration_ms=600_000,
        match_id="NA1_x",
        media_asset_id="media1",
        match_duration_ms=1_800_000,
    )
    assert sync.quality.method == "manual"
    assert sync.quality.verdict == "DEGRADED"
    assert sync.verified is False
    assert sync.game_to_video(90_000) == 12_000
    assert sync.video_to_game(12_000) == 90_000
    assert sync.covers_game(90_000)
    assert not sync.covers_game(5_000)


def test_manual_two_anchors_consistent_offset() -> None:
    sync = build_manual_sync(
        [(10_000, 70_000), (130_000, 190_000)],
        video_duration_ms=400_000,
        match_id="NA1_x",
        match_duration_ms=400_000,
    )
    assert sync.segments[0].offset_ms == 60_000
    assert sync.game_to_video(190_000) == 130_000
    assert sync.quality.verdict in {"GOOD", "DEGRADED"}
    assert sync.quality.n_readings == 2


def test_manual_inconsistent_slope_raises() -> None:
    with pytest.raises(SyncAnchorInconsistent, match="slope"):
        build_manual_sync(
            [(0, 0), (60_000, 120_000)],
            video_duration_ms=180_000,
            match_id="NA1_x",
        )


def test_empty_anchors_and_bad_duration_raise() -> None:
    with pytest.raises(ValueError, match="anchor"):
        build_manual_sync([], video_duration_ms=10_000, match_id="x")
    with pytest.raises(ValueError, match="positive"):
        build_manual_sync([(0, 0)], video_duration_ms=0, match_id="x")


def test_round_trip_dict() -> None:
    sync = build_manual_sync(
        [(5_000, 20_000), (65_000, 80_050)],
        video_duration_ms=120_000,
        match_id="m",
        media_asset_id="a",
    )
    restored = SyncMap.from_dict(sync.to_dict())
    assert restored.game_to_video(20_000) == sync.game_to_video(20_000)
    assert restored.match_id == "m"
    assert restored.quality.verdict == sync.quality.verdict


def test_seek_target_does_not_invent_times_without_sync() -> None:
    target = seek_target(None, 140_000)
    assert target.t_video_ms is None
    assert target.seek_video_ms is None
    assert target.covered is False
    assert target.uncertain is True
    assert target.reason is not None


def test_seek_target_uncovered_game_time() -> None:
    sync = build_manual_sync(
        [(30_000, 120_000)],
        video_duration_ms=60_000,
        match_id="m",
        match_duration_ms=1_800_000,
    )
    target = seek_target(sync, 10_000)
    assert target.covered is False
    assert target.t_video_ms is None


def test_seek_target_applies_lead_in() -> None:
    sync = build_manual_sync(
        [(20_000, 80_000)],
        video_duration_ms=300_000,
        match_id="m",
    )
    target = seek_target(sync, 80_000)
    assert target.covered is True
    assert target.t_video_ms == 20_000
    assert target.seek_video_ms == 20_000 - SEEK_LEAD_IN_MS
    assert target.uncertain is True


def test_seek_target_lead_in_clamps_at_zero() -> None:
    sync = build_manual_sync(
        [(3_000, 50_000)],
        video_duration_ms=60_000,
        match_id="m",
    )
    target = seek_target(sync, 50_000, lead_in_ms=8_000)
    assert target.seek_video_ms == 0


def test_piecewise_segments_pause_gap() -> None:
    sync = SyncMap(
        segments=(
            SyncSegment(0, 60_000, offset_ms=10_000, n_anchors=2, residual_p95_ms=20.0),
            SyncSegment(150_000, 300_000, offset_ms=-80_000, n_anchors=2, residual_p95_ms=30.0),
        ),
        pauses=(),
        quality=SyncQuality(
            method="manual",
            n_readings=4,
            n_inliers=4,
            inlier_ratio=1.0,
            residual_p50_ms=10.0,
            residual_p95_ms=30.0,
            coverage=0.8,
            n_segments=2,
            verdict="DEGRADED",
        ),
        media_asset_id="m",
        match_id="match",
        version=1,
    )
    assert sync.video_to_game(10_000) == 20_000
    assert sync.game_to_video(20_000) == 10_000
    assert sync.video_to_game(90_000) is None
    assert sync.game_to_video(200_000) == 280_000
