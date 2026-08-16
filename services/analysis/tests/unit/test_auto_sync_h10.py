from __future__ import annotations

import time

import pytest
from riftlens.domain.clock_reading import ClockReading
from riftlens.pipeline.sync.errors import AutoSyncError, InsufficientReadings, MultipleGamesDetected
from riftlens.pipeline.sync.filter import CONFIDENCE_GATE, AcceptedPoint, filter_readings
from riftlens.pipeline.sync.fitter import constrained_ransac, fit_auto_sync
from riftlens.pipeline.sync.segments import detect_pauses, split_linear_groups
from riftlens.pipeline.sync.verify import split_fit_and_holdout, verify_sync


def _r(
    t_video_ms: int,
    t_game_ms: int | None,
    confidence: float = 0.95,
    *,
    in_game: bool = True,
) -> ClockReading:
    return ClockReading(
        t_video_ms=t_video_ms,
        t_game_ms=t_game_ms,
        confidence=confidence,
        in_game=in_game,
    )


def _linear(
    *,
    video_start: int,
    video_end: int,
    offset: int,
    step: int = 1_000,
    confidence: float = 0.95,
) -> list[ClockReading]:
    rows: list[ClockReading] = []
    t_video = video_start
    while t_video < video_end:
        rows.append(_r(t_video, t_video + offset, confidence))
        t_video += step
    return rows


def _scenario_a(
    *, outlier_frac: float = 0.15, seed: int = 7
) -> tuple[list[ClockReading], dict[str, int]]:
    """Outliers + 90s pause + 40s cut. Ground-truth offsets are 60_000, -30_000, 10_000."""
    phase1 = _linear(video_start=0, video_end=120_000, offset=60_000)
    pause = [_r(t, 180_000) for t in range(120_000, 210_000, 1_000)]
    phase2 = _linear(video_start=210_000, video_end=250_000, offset=-30_000)
    phase3 = _linear(video_start=250_000, video_end=400_000, offset=10_000)
    rows = phase1 + pause + phase2 + phase3
    linear_idx = [
        i
        for i, item in enumerate(rows)
        if item.t_game_ms != 180_000 or item.t_video_ms < 120_000
    ]
    n_out = max(1, int(round(outlier_frac * len(linear_idx))))
    # Deterministic every-kth linear sample becomes a +5 min outlier.
    stride = max(1, len(linear_idx) // n_out)
    mutated: list[ClockReading] = list(rows)
    for index in linear_idx[::stride][:n_out]:
        item = mutated[index]
        assert item.t_game_ms is not None
        mutated[index] = _r(item.t_video_ms, item.t_game_ms + 300_000, 0.92)
    truth = {"phase1": 60_000, "phase2": -30_000, "phase3": 10_000}
    return mutated, truth


def test_confidence_filter_discards_none_and_low_conf() -> None:
    readings = [
        _r(0, None, 0.99),
        _r(1_000, 61_000, 0.5),
        _r(2_000, 62_000, 0.8),
        _r(3_000, 63_000, 0.9),
        _r(4_000, 91 * 60 * 1000, 0.99),
        _r(-1, 10, 0.99),
    ]
    accepted, report = filter_readings(readings)
    assert [item.t_game_ms for item in accepted] == [62_000, 63_000]
    assert report.reason_counts["missing_game"] == 1
    assert report.reason_counts["low_confidence"] == 1
    assert report.reason_counts["over_90_min"] == 1
    assert report.reason_counts["negative_time"] == 1
    assert CONFIDENCE_GATE == 0.8


def test_filter_keeps_repeated_game_times() -> None:
    readings = [_r(t, 90_000) for t in range(0, 5_000, 1_000)]
    accepted, report = filter_readings(readings)
    assert report.accepted == 5
    assert len({item.t_game_ms for item in accepted}) == 1


def test_ransac_is_deterministic_and_respects_slope() -> None:
    points = [
        AcceptedPoint(t_video_ms=i * 1_000, t_game_ms=i * 1_000 + 40_000, confidence=0.9)
        for i in range(40)
    ]
    points[3] = AcceptedPoint(3_000, 3_000 + 40_000 + 50_000, 0.9)
    rng_a = __import__("random").Random(10)
    rng_b = __import__("random").Random(10)
    first = constrained_ransac(points, rng=rng_a)
    second = constrained_ransac(points, rng=rng_b)
    assert [item.t_video_ms for item in first] == [item.t_video_ms for item in second]
    assert all(abs((item.t_game_ms - item.t_video_ms) - 40_000) <= 400 for item in first)


def test_pause_detection_requires_three_repeats() -> None:
    points = [
        AcceptedPoint(0, 10_000, 0.9),
        AcceptedPoint(1_000, 11_000, 0.9),
        AcceptedPoint(2_000, 12_000, 0.9),
        AcceptedPoint(3_000, 12_000, 0.9),
        AcceptedPoint(4_000, 12_000, 0.9),
        AcceptedPoint(5_000, 12_000, 0.9),
        AcceptedPoint(6_000, 13_000, 0.9),
    ]
    pauses = detect_pauses(points)
    assert len(pauses) == 1
    assert pauses[0].t_game_ms == 12_000
    assert pauses[0].video_end_ms - pauses[0].video_start_ms >= 2_000


def test_cut_splits_offset_groups() -> None:
    left = [AcceptedPoint(i * 1_000, i * 1_000 + 10_000, 0.9) for i in range(20)]
    right = [AcceptedPoint(20_000 + i * 1_000, 20_000 + i * 1_000 + 50_000, 0.9) for i in range(20)]
    groups = split_linear_groups(left + right)
    assert len(groups) == 2


def test_scenario_a_outliers_pause_cut() -> None:
    readings, truth = _scenario_a()
    result = fit_auto_sync(
        readings,
        match_id="NA1_h10_a",
        video_duration_ms=400_000,
        match_duration_ms=1_800_000,
    )
    sync = result.sync_map
    assert sync.quality.method == "clock_ocr"
    assert sync.quality.verdict in {"EXCELLENT", "GOOD", "DEGRADED"}
    assert len(sync.pauses) == 1
    assert abs((sync.pauses[0].video_end_ms - sync.pauses[0].video_start_ms) - 90_000) <= 2_000
    assert len(sync.segments) == 3
    for segment in sync.segments:
        # Final pieces are slope 1.0 by construction: t_game = t_video + offset.
        assert segment.video_end_ms > segment.video_start_ms
    offsets = [item.offset_ms for item in sync.segments]
    assert abs(offsets[0] - truth["phase1"]) <= 100
    assert abs(offsets[1] - truth["phase2"]) <= 100
    assert abs(offsets[2] - truth["phase3"]) <= 100
    assert sync.video_to_game(10_000) == 10_000 + offsets[0]
    assert sync.video_to_game(230_000) == 230_000 + offsets[1]
    assert sync.video_to_game(300_000) == 300_000 + offsets[2]
    # Pause video is uncovered so the mapping cannot drift through the freeze.
    assert sync.video_to_game(150_000) is None


def test_scenario_b_two_games() -> None:
    game1 = _linear(video_start=0, video_end=600_000, offset=0)
    game2 = _linear(video_start=600_000, video_end=1_200_000, offset=-600_000)
    with pytest.raises(MultipleGamesDetected) as exc:
        fit_auto_sync(
            game1 + game2,
            match_id="NA1_h10_b",
            video_duration_ms=1_200_000,
        )
    assert exc.value.code == "MULTIPLE_GAMES"
    assert exc.value.boundaries_video_ms
    assert abs(exc.value.boundaries_video_ms[0] - 600_000) <= 2_000


def test_scenario_c_mid_game_start_does_not_invent_precoverage() -> None:
    readings = _linear(video_start=0, video_end=300_000, offset=600_000)
    result = fit_auto_sync(
        readings,
        match_id="NA1_h10_c",
        video_duration_ms=300_000,
        match_duration_ms=1_800_000,
    )
    sync = result.sync_map
    assert abs(sync.segments[0].offset_ms - 600_000) <= 100
    assert sync.game_to_video(600_000) is not None
    assert sync.game_to_video(0) is None
    assert sync.covers_game(0) is False


def test_scenario_d_sparse_succeeds_or_degrades_honestly() -> None:
    dense = _linear(video_start=0, video_end=120_000, offset=20_000)
    mixed: list[ClockReading] = []
    for index, item in enumerate(dense):
        if index % 8 == 0:
            mixed.append(item)
        elif index % 8 == 1:
            mixed.append(_r(item.t_video_ms, item.t_game_ms, 0.4))
        else:
            mixed.append(_r(item.t_video_ms, None, 0.0, in_game=False))
    result = fit_auto_sync(
        mixed,
        match_id="NA1_h10_d",
        video_duration_ms=120_000,
    )
    assert result.sync_map.quality.verdict in {"GOOD", "DEGRADED"}
    assert abs(result.sync_map.segments[0].offset_ms - 20_000) <= 100


def test_scenario_d_too_sparse_fails() -> None:
    readings = [_r(0, 10_000), _r(60_000, 70_000)]
    with pytest.raises(InsufficientReadings):
        fit_auto_sync(readings, match_id="NA1_h10_d2", video_duration_ms=120_000)


def test_unrealistic_slope_is_rejected() -> None:
    # Game clock runs at 2x video — forbidden by |a-1|<=0.02.
    readings = [_r(i * 1_000, i * 2_000) for i in range(40)]
    with pytest.raises(AutoSyncError) as exc:
        fit_auto_sync(readings, match_id="NA1_slope", video_duration_ms=40_000)
    assert exc.value.code in {
        "NO_STABLE_MODEL",
        "INSUFFICIENT_COVERAGE",
        "VERIFICATION_FAILED",
        "INSUFFICIENT_READINGS",
    }


def test_verification_is_not_a_second_fit() -> None:
    readings, _ = _scenario_a()
    result = fit_auto_sync(readings, match_id="NA1_v", video_duration_ms=400_000)
    holdout = [
        AcceptedPoint(item.t_video_ms, item.t_game_ms, item.confidence)
        for item in filter_readings(readings)[0][10:20]
        if item.t_game_ms != 180_000
    ]
    verify = verify_sync(result.sync_map, holdout, pauses=result.sync_map.pauses)
    assert verify.ok is True
    # Hold-out uses the already-fitted map; it must not require a second RANSAC.
    assert result.verify.ok is True


def test_gst_pause_crosscheck_marks_verified_pause() -> None:
    readings, _ = _scenario_a()
    result = fit_auto_sync(
        readings,
        match_id="NA1_pause_gst",
        video_duration_ms=400_000,
        pause_end_game_ms=(180_000,),
    )
    assert result.verify.pause_gst_crosschecked is True


def test_holdout_split_is_deterministic() -> None:
    points = [AcceptedPoint(i * 1_000, i * 1_000 + 5_000, 0.9) for i in range(20)]
    fit_a, hold_a = split_fit_and_holdout(points)
    fit_b, hold_b = split_fit_and_holdout(points)
    assert [item.t_video_ms for item in hold_a] == [item.t_video_ms for item in hold_b]
    assert [item.t_video_ms for item in fit_a] == [item.t_video_ms for item in fit_b]


def test_fit_runtime_on_40min_1hz_is_cheap() -> None:
    readings = _linear(video_start=0, video_end=2_400_000, offset=15_000)
    started = time.perf_counter()
    result = fit_auto_sync(
        readings, match_id="NA1_perf", video_duration_ms=2_400_000, match_duration_ms=2_400_000
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert result.sync_map.quality.n_inliers >= 1900
    assert elapsed_ms < 5_000
    assert result.fit_ms < 5_000


def test_clock_map_wraps_sync_map() -> None:
    readings = _linear(video_start=0, video_end=30_000, offset=8_000)
    result = fit_auto_sync(readings, match_id="NA1_wrap", video_duration_ms=30_000)
    assert result.clock_map.source_to_game(2_000) == result.sync_map.video_to_game(2_000)
    assert result.clock_map.sync_map is not None
