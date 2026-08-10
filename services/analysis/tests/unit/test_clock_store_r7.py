from __future__ import annotations

from pathlib import Path

from riftlens.domain.clock_map import ClockConfidence, ClockMap
from riftlens.domain.clock_store import (
    CALIBRATION_METHOD_EVENT_ANCHOR_V1,
    CALIBRATION_METHOD_MANUAL,
    CLOCK_KIND_CALIBRATED_REPLAY,
    CLOCK_KIND_LINEAR_OFFSET,
    STORE_CONFIDENCE_CALIBRATED,
    STORE_CONFIDENCE_ESTIMATED,
    STORE_CONFIDENCE_MANUAL,
    amendment_clock_confidence,
    amendment_clock_kind,
    decode_clock_payload,
    encode_clock_payload,
    local_display_name,
    source_file_present,
)


def test_local_display_name_is_basename_only() -> None:
    assert local_display_name(r"C:\Users\someone\Documents\League\NA1_1.rofl") == "NA1_1.rofl"
    assert local_display_name("/home/user/Videos/game.mp4") == "game.mp4"


def test_source_file_present_false_for_missing(tmp_path: Path) -> None:
    assert source_file_present(str(tmp_path / "gone.rofl")) is False


def test_verified_offset_payload_round_trips() -> None:
    clock = ClockMap.offset(
        offset_ms=-670,
        source_start_ms=0,
        source_end_ms=1_800_000,
        confidence=ClockConfidence.GOOD,
        verified=True,
    )
    raw = encode_clock_payload(clock, stdev_ms=306.08, warning=None)
    loaded, stdev_ms, warning, media_id = decode_clock_payload(raw)
    assert loaded == clock
    assert stdev_ms == 306.08
    assert warning is None
    assert media_id is None
    assert amendment_clock_kind(clock) == CLOCK_KIND_CALIBRATED_REPLAY
    assert (
        amendment_clock_confidence(clock, CALIBRATION_METHOD_EVENT_ANCHOR_V1)
        == STORE_CONFIDENCE_CALIBRATED
    )


def test_estimated_map_is_not_calibrated_kind() -> None:
    clock = ClockMap.offset(
        offset_ms=-1200,
        source_start_ms=0,
        source_end_ms=1_800_000,
        confidence=ClockConfidence.DEGRADED,
        verified=False,
    )
    assert amendment_clock_kind(clock) == CLOCK_KIND_LINEAR_OFFSET
    assert amendment_clock_confidence(clock, "duration_heuristic") == STORE_CONFIDENCE_ESTIMATED
    assert amendment_clock_confidence(clock, CALIBRATION_METHOD_MANUAL) == STORE_CONFIDENCE_MANUAL
    loaded, _, _, _ = decode_clock_payload(encode_clock_payload(clock))
    assert loaded.verified is False
    assert loaded.confidence is ClockConfidence.DEGRADED
