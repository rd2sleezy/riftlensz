from __future__ import annotations

from riftlens.domain.clock_map import ClockConfidence, ClockMap
from riftlens.domain.clock_store import (
    CALIBRATION_METHOD_EVENT_ANCHOR_V1,
    SOURCE_STATUS_LINKED,
    SOURCE_TYPE_ROFL,
    SOURCE_TYPE_VIDEO,
)
from riftlens.domain.gameplay_source import SourceCapability
from riftlens.domain.ids import new_ulid
from riftlens.domain.ports import (
    ClockCalibrationRecord,
    GameplaySourceRecord,
    GameplaySourceSnapshot,
    RoflSourceDetailRecord,
)
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.gameplay.factory import GameplaySourceFactory
from riftlens.gameplay.status import (
    compose_gameplay_status,
    serialize_replay_error,
    suggested_action_for,
)
from riftlens.replay_host.session import ReplaySessionPhase, ReplaySessionSnapshot
from tests.fakes.fake_replay_host import FakeReplayHost


def _rofl_snapshot(
    *, verified: bool = False, confidence: ClockConfidence = ClockConfidence.GOOD
) -> GameplaySourceSnapshot:
    source_id = new_ulid()
    clock = None
    if verified or confidence is not ClockConfidence.UNKNOWN:
        mapped = ClockMap.offset(
            offset_ms=-670,
            source_start_ms=0,
            source_end_ms=1_800_000,
            confidence=confidence,
            verified=verified,
        )
        clock = ClockCalibrationRecord(
            id=new_ulid(),
            gameplay_source_id=source_id,
            kind="calibrated_replay",
            offset_ms=-670,
            rate=1.0,
            confidence="calibrated" if verified else "estimated",
            method=CALIBRATION_METHOD_EVENT_ANCHOR_V1,
            anchor_count=4,
            residual_ms=80,
            is_active=1,
            created_at=1,
            clock=mapped,
        )
    return GameplaySourceSnapshot(
        source=GameplaySourceRecord(
            id=source_id,
            match_id="NA1_5617764200",
            source_type=SOURCE_TYPE_ROFL,
            source_uri="C:/replays/NA1-5617764200.rofl",
            content_hash=None,
            display_name="NA1-5617764200.rofl",
            duration_ms=1_800_000,
            status=SOURCE_STATUS_LINKED,
            platform_scope="windows",
            created_at=1,
            updated_at=1,
        ),
        rofl=RoflSourceDetailRecord(
            gameplay_source_id=source_id,
            platform_id="NA1",
            game_id=5_617_764_200,
            declared_patch="16.15",
            declared_length_ms=1_800_000,
            identify_method="filename",
            header_parse_status="ok",
            file_size_bytes=100,
            magic="RIOT",
        ),
        clock=clock,
        file_present=True,
    )


def test_status_omits_source_type() -> None:
    host = FakeReplayHost()
    factory = GameplaySourceFactory(host)
    snap = _rofl_snapshot(verified=True)
    payload = compose_gameplay_status(
        match_id="NA1_5617764200",
        native_supported=True,
        snapshots=[snap],
        chosen=snap,
        resolved=factory.resolve(snap),
        session=ReplaySessionSnapshot(phase=ReplaySessionPhase.IDLE),
        factory=factory,
    )
    assert "source_type" not in payload
    assert SourceCapability.LIVE_CLIENT_DATA.value in payload["capabilities"]
    assert payload["session_reached_ready"] is False
    assert payload["clock_verified"] is True


def test_degraded_clock_is_not_verified() -> None:
    host = FakeReplayHost()
    factory = GameplaySourceFactory(host)
    snap = _rofl_snapshot(verified=False, confidence=ClockConfidence.DEGRADED)
    payload = compose_gameplay_status(
        match_id="NA1_5617764200",
        native_supported=True,
        snapshots=[snap],
        chosen=snap,
        resolved=factory.resolve(snap),
        session=ReplaySessionSnapshot(
            phase=ReplaySessionPhase.READY, reached_ready=True
        ),
        factory=factory,
    )
    assert payload["session_reached_ready"] is True
    assert payload["clock_verified"] is False
    assert payload["clock_confidence"] == ClockConfidence.DEGRADED.value


def test_every_replay_error_has_message_and_action() -> None:
    for code in ReplayErrorCode:
        error = serialize_replay_error(ReplayError(code))
        assert error is not None
        assert error["code"] == code.value
        assert error["message"]
        assert "something went wrong" not in error["message"].lower()
        assert suggested_action_for(code)
        assert error["suggested_action"]


def test_video_source_has_seek_without_live_client() -> None:
    host = FakeReplayHost()
    factory = GameplaySourceFactory(host)
    source_id = new_ulid()
    snap = GameplaySourceSnapshot(
        source=GameplaySourceRecord(
            id=source_id,
            match_id="NA1_5617764200",
            source_type=SOURCE_TYPE_VIDEO,
            source_uri="C:/vods/game.mp4",
            content_hash=None,
            display_name="game.mp4",
            duration_ms=1_800_000,
            status=SOURCE_STATUS_LINKED,
            platform_scope="any",
            created_at=1,
            updated_at=1,
            media_asset_id="media-1",
        ),
        rofl=None,
        clock=None,
        file_present=True,
    )
    payload = compose_gameplay_status(
        match_id="NA1_5617764200",
        native_supported=True,
        snapshots=[snap],
        chosen=snap,
        resolved=factory.resolve(snap),
        session=ReplaySessionSnapshot(phase=ReplaySessionPhase.IDLE),
        factory=factory,
    )
    assert SourceCapability.SEEK.value in payload["capabilities"]
    assert SourceCapability.LIVE_CLIENT_DATA.value not in payload["capabilities"]
    assert "source_type" not in payload
