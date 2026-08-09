from __future__ import annotations

import pytest
from riftlens.domain.clock_map import ClockConfidence, ClockMap, ClockMode
from riftlens.domain.gameplay_source import (
    NATIVE_REPLAY_CAPABILITIES,
    VIDEO_CAPABILITIES,
    GameplaySource,
    PlaybackState,
    SourceCapability,
    SourceKind,
)
from riftlens.domain.ports import GameplaySourcePort, LiveClientDataPort, PlaybackControl
from riftlens.domain.replay_errors import (
    ReplayError,
    ReplayErrorCode,
    ReplayErrorSeverity,
    replay_error_message,
    replay_error_severity,
)
from riftlens.domain.sync_map import (
    SEEK_LEAD_IN_MS,
    SyncMap,
    SyncQuality,
    SyncSegment,
    build_manual_sync,
    seek_target,
)


def _manual_sync() -> SyncMap:
    return build_manual_sync(
        [(12_000, 90_000)],
        video_duration_ms=600_000,
        match_id="NA1_x",
        media_asset_id="media1",
        match_duration_ms=1_800_000,
    )


def test_clock_identity_round_trip() -> None:
    clock = ClockMap.identity(duration_ms=1_902_000)
    for t_ms in (0, 1, 60_000, 300_000, 1_901_999):
        game_ms = clock.source_to_game(t_ms)
        assert game_ms == t_ms
        assert clock.game_to_source(game_ms) == t_ms


def test_clock_offset_round_trip_matches_h9_anchor() -> None:
    clock = ClockMap.offset(offset_ms=78_000, source_start_ms=0, source_end_ms=600_000)
    assert clock.source_to_game(12_000) == 90_000
    assert clock.game_to_source(90_000) == 12_000
    restored = ClockMap.from_dict(clock.to_dict())
    assert restored.source_to_game(12_000) == 90_000
    assert restored.mode is ClockMode.OFFSET
    assert restored.offset_ms == 78_000


def test_clock_dict_round_trip_identity() -> None:
    clock = ClockMap.identity(duration_ms=10_000, verified=True)
    restored = ClockMap.from_dict(clock.to_dict())
    assert restored == clock
    assert restored.confidence is ClockConfidence.EXACT


def test_clock_clamps_and_rejects_out_of_bounds() -> None:
    clock = ClockMap.offset(offset_ms=10_000, source_start_ms=0, source_end_ms=60_000)
    assert clock.source_to_game(-1) is None
    assert clock.source_to_game(60_000) is None
    assert clock.game_to_source(5_000) is None
    assert clock.clamp_source_ms(-50) == 0
    assert clock.clamp_source_ms(99_999) == 59_999
    assert clock.clamp_game_ms(0) == 10_000
    assert clock.clamp_game_ms(999_999) == 69_999
    assert clock.contains_source(0)
    assert not clock.contains_source(60_000)


def test_clock_unmapped_never_converts() -> None:
    clock = ClockMap.unmapped(duration_ms=120_000)
    assert clock.confidence is ClockConfidence.UNKNOWN
    assert clock.source_to_game(0) is None
    assert clock.game_to_source(0) is None
    assert clock.clamp_source_ms(-1) == 0


def test_clock_from_sync_map_preserves_h9_piecewise_behavior() -> None:
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
    clock = ClockMap.from_sync_map(sync)
    assert clock.mode is ClockMode.SYNC_MAP
    assert clock.confidence is ClockConfidence.DEGRADED
    assert clock.source_to_game(10_000) == sync.video_to_game(10_000) == 20_000
    assert clock.game_to_source(20_000) == sync.game_to_video(20_000) == 10_000
    assert clock.source_to_game(90_000) is None
    assert clock.game_to_source(200_000) == 280_000
    restored = ClockMap.from_dict(clock.to_dict())
    assert restored.source_to_game(10_000) == 20_000
    assert restored.sync_map is not None
    assert restored.sync_map.match_id == "match"


def test_clock_confidence_maps_sync_verdicts() -> None:
    base = _manual_sync()
    for verdict, expected in (
        ("EXCELLENT", ClockConfidence.EXACT),
        ("GOOD", ClockConfidence.GOOD),
        ("DEGRADED", ClockConfidence.DEGRADED),
        ("FAILED", ClockConfidence.FAILED),
    ):
        sync = SyncMap(
            segments=base.segments,
            pauses=base.pauses,
            quality=SyncQuality(
                method=base.quality.method,
                n_readings=base.quality.n_readings,
                n_inliers=base.quality.n_inliers,
                inlier_ratio=base.quality.inlier_ratio,
                residual_p50_ms=base.quality.residual_p50_ms,
                residual_p95_ms=base.quality.residual_p95_ms,
                coverage=base.quality.coverage,
                n_segments=base.quality.n_segments,
                verdict=verdict,  # type: ignore[arg-type]
            ),
            media_asset_id=base.media_asset_id,
            match_id=base.match_id,
            version=base.version,
            verified=True,
        )
        assert ClockMap.from_sync_map(sync).confidence is expected


def test_video_source_delegates_seek_to_h9_seek_target() -> None:
    sync = _manual_sync()
    source = GameplaySource.for_video(
        source_id="src-video",
        match_id="NA1_x",
        media_asset_id="media1",
        duration_ms=600_000,
        sync_map=sync,
    )
    assert source.kind is SourceKind.VIDEO
    assert source.capabilities == VIDEO_CAPABILITIES
    expected = seek_target(sync, 90_000)
    actual = source.seek_for_game(90_000)
    assert actual == expected
    assert actual.t_video_ms == 12_000
    assert actual.seek_video_ms == 12_000 - SEEK_LEAD_IN_MS
    assert actual.uncertain is True


def test_video_source_without_sync_matches_h9_none_sync() -> None:
    source = GameplaySource.for_video(
        source_id="src-video",
        match_id="NA1_x",
        media_asset_id="media1",
        duration_ms=600_000,
        sync_map=None,
    )
    assert source.seek_for_game(140_000) == seek_target(None, 140_000)
    assert not source.supports(SourceCapability.LIVE_CLIENT_DATA)
    assert not source.supports(SourceCapability.ACTIVE_PLAYER)


def test_native_replay_identity_seek_and_capabilities() -> None:
    source = GameplaySource.for_native_replay(
        source_id="src-rofl",
        match_id="NA1-5617764200",
        duration_ms=1_902_973,
    )
    assert source.kind is SourceKind.NATIVE_REPLAY
    assert source.capabilities == NATIVE_REPLAY_CAPABILITIES
    assert source.supports(SourceCapability.LIVE_CLIENT_DATA)
    assert not source.supports(SourceCapability.ACTIVE_PLAYER)
    target = source.seek_for_game(300_000)
    assert target.covered is True
    assert target.t_video_ms == 300_000
    assert target.seek_video_ms == 300_000 - SEEK_LEAD_IN_MS
    assert target.uncertain is False
    early = source.seek_for_game(3_000)
    assert early.seek_video_ms == 0


def test_native_replay_rejects_out_of_range_game_time() -> None:
    source = GameplaySource.for_native_replay(
        source_id="src-rofl",
        match_id="NA1_x",
        duration_ms=60_000,
    )
    target = source.seek_for_game(90_000)
    assert target.covered is False
    assert target.t_video_ms is None
    assert target.uncertain is True


def test_require_capability_raises_typed_error() -> None:
    source = GameplaySource.for_video(
        source_id="v",
        match_id="m",
        media_asset_id="a",
        duration_ms=1_000,
        sync_map=None,
    )
    with pytest.raises(ReplayError) as exc_info:
        source.require(SourceCapability.LIVE_CLIENT_DATA)
    assert exc_info.value.code is ReplayErrorCode.CAPABILITY_UNSUPPORTED
    assert exc_info.value.is_fatal()


def test_playback_state_binds_clock_without_inventing_time() -> None:
    clock = ClockMap.identity(duration_ms=10_000)
    state = PlaybackState(
        t_source_ms=2_261,
        length_ms=10_000,
        paused=False,
        seeking=False,
        speed_milli=1000,
    ).bind_clock(clock)
    assert state.t_game_ms == 2_261
    unmapped = PlaybackState(
        t_source_ms=50,
        length_ms=10_000,
        paused=True,
        seeking=False,
    ).bind_clock(ClockMap.unmapped(duration_ms=10_000))
    assert unmapped.t_game_ms is None


def test_replay_error_taxonomy_is_complete() -> None:
    codes = set(ReplayErrorCode)
    assert codes, "taxonomy must not be empty"
    severities: set[ReplayErrorSeverity] = set()
    for code in ReplayErrorCode:
        message = replay_error_message(code)
        assert message
        severity = replay_error_severity(code)
        severities.add(severity)
        err = ReplayError(code)
        assert err.code is code
        assert str(err) == message
        assert err.severity == severity
        assert err.is_fatal() == (severity == "fatal")
        assert err.is_retryable() == (severity == "retryable")
        assert err.is_informational() == (severity == "informational")
    assert severities == {"fatal", "retryable", "informational"}
    assert ReplayErrorCode.LIVE_CLIENT_DATA_UNAVAILABLE in codes
    assert ReplayErrorCode.ACTIVE_PLAYER_UNAVAILABLE in codes
    lcd = ReplayError(ReplayErrorCode.LIVE_CLIENT_DATA_UNAVAILABLE)
    active = ReplayError(ReplayErrorCode.ACTIVE_PLAYER_UNAVAILABLE)
    assert lcd.is_informational() and not lcd.is_fatal()
    assert active.is_informational() and not active.is_fatal()


def test_capability_modeling_video_vs_native() -> None:
    video = VIDEO_CAPABILITIES
    native = NATIVE_REPLAY_CAPABILITIES
    shared = {
        SourceCapability.READ_TIME,
        SourceCapability.PAUSE,
        SourceCapability.RESUME,
        SourceCapability.SEEK,
        SourceCapability.SET_SPEED,
    }
    assert shared <= video
    assert shared <= native
    assert SourceCapability.LIVE_CLIENT_DATA in native
    assert SourceCapability.LIVE_CLIENT_DATA not in video
    assert SourceCapability.ACTIVE_PLAYER not in video
    assert SourceCapability.ACTIVE_PLAYER not in native
    assert set(SourceCapability) == video | native | {SourceCapability.ACTIVE_PLAYER}


class _FakePlayback:
    def __init__(self, source: GameplaySource) -> None:
        self._source = source
        self._state = PlaybackState(
            t_source_ms=0,
            length_ms=source.duration_ms,
            paused=True,
            seeking=False,
        ).bind_clock(source.clock)

    def read_state(self) -> PlaybackState:
        return self._state

    def pause(self) -> PlaybackState:
        self._source.require(SourceCapability.PAUSE)
        self._state = PlaybackState(
            t_source_ms=self._state.t_source_ms,
            length_ms=self._state.length_ms,
            paused=True,
            seeking=False,
            speed_milli=self._state.speed_milli,
            t_game_ms=self._state.t_game_ms,
        )
        return self._state

    def resume(self) -> PlaybackState:
        self._source.require(SourceCapability.RESUME)
        self._state = PlaybackState(
            t_source_ms=self._state.t_source_ms,
            length_ms=self._state.length_ms,
            paused=False,
            seeking=False,
            speed_milli=self._state.speed_milli,
            t_game_ms=self._state.t_game_ms,
        )
        return self._state

    def seek_to_game_ms(self, t_game_ms: int) -> PlaybackState:
        self._source.require(SourceCapability.SEEK)
        target = self._source.seek_for_game(t_game_ms, lead_in_ms=0)
        if not target.covered or target.t_video_ms is None:
            raise ReplayError(ReplayErrorCode.CLOCK_UNMAPPED)
        self._state = PlaybackState(
            t_source_ms=target.t_video_ms,
            length_ms=self._state.length_ms,
            paused=True,
            seeking=False,
        ).bind_clock(self._source.clock)
        return self._state


class _FakeSourcePort:
    def __init__(self, source: GameplaySource) -> None:
        self._source = source

    def current_source(self) -> GameplaySource:
        return self._source

    def capabilities(self) -> frozenset[SourceCapability]:
        return self._source.capabilities


class _FakeLiveClient:
    def __init__(self, *, available: bool, active_player: bool) -> None:
        self._available = available
        self._active_player = active_player

    def is_available(self) -> bool:
        return self._available

    def active_player_available(self) -> bool:
        return self._active_player


def test_domain_ports_are_satisfied_by_in_memory_fakes() -> None:
    source = GameplaySource.for_native_replay(
        source_id="src",
        match_id="NA1_x",
        duration_ms=400_000,
    )
    playback: PlaybackControl = _FakePlayback(source)
    provider: GameplaySourcePort = _FakeSourcePort(source)
    live: LiveClientDataPort = _FakeLiveClient(available=True, active_player=False)
    assert provider.current_source().kind is SourceKind.NATIVE_REPLAY
    assert SourceCapability.PAUSE in provider.capabilities()
    resumed = playback.resume()
    assert resumed.paused is False
    sought = playback.seek_to_game_ms(180_000)
    assert sought.t_source_ms == 180_000
    assert sought.t_game_ms == 180_000
    assert live.is_available()
    assert not live.active_player_available()


def test_invalid_clock_and_source_construction() -> None:
    with pytest.raises(ValueError, match="source_end_ms"):
        ClockMap.offset(offset_ms=0, source_start_ms=10, source_end_ms=5)
    with pytest.raises(ValueError, match="duration_ms"):
        ClockMap.identity(duration_ms=-1)
    with pytest.raises(ValueError, match="media_asset_id"):
        GameplaySource(
            id="x",
            kind=SourceKind.VIDEO,
            match_id="m",
            capabilities=VIDEO_CAPABILITIES,
            clock=ClockMap.unmapped(duration_ms=1),
            duration_ms=1,
            media_asset_id=None,
        )
    with pytest.raises(ValueError, match="NATIVE_REPLAY"):
        GameplaySource(
            id="x",
            kind=SourceKind.NATIVE_REPLAY,
            match_id="m",
            capabilities=NATIVE_REPLAY_CAPABILITIES,
            clock=ClockMap.identity(duration_ms=1),
            duration_ms=1,
            media_asset_id="nope",
        )
