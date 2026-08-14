"""Deterministic tests for capture-time camera framing (path + GST)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from riftlens.domain.camera_framing import (
    CAMERA_MODE_PATH,
    CAMERA_STRATEGY_PATH_GST,
    DEFAULT_CAMERA_HEIGHT,
    DEFAULT_STABILIZE_S,
    CameraFramingStatus,
    build_path_gst_framing_plan,
    camera_position_to_riot_xy,
    ground_distance,
    metadata_skipped,
    resolve_gst_camera_target,
    riot_xy_to_camera_position,
)
from riftlens.domain.capture import CaptureMode, CaptureRequest, CaptureStatus
from riftlens.domain.clock_map import ClockMap
from riftlens.domain.enums import FactKind
from riftlens.domain.ids import new_ulid
from riftlens.domain.replay_errors import ReplayError, ReplayErrorCode
from riftlens.replay_host.api.replay_client import ReplayApiClient
from riftlens.replay_host.capture.camera_framing import (
    FramingStickyClient,
    apply_framing,
    restore_framing,
    snapshot_render,
)
from riftlens.replay_host.capture.recording import run_capture
from riftlens.replay_host.mac.host import MacReplayHost
from tests.fakes.fake_replay_host import FakeReplayHost
from tests.fakes.fake_replay_runtime import FakeClock
from tests.fakes.fake_replay_server import FakeReplayApiServer, FakeReplayBehavior
from tests.helpers.synthetic import fact, make_gst, roster


def _clock() -> ClockMap:
    return ClockMap.identity(duration_ms=1_800_000)


def _client(server: FakeReplayApiServer) -> ReplayApiClient:
    return ReplayApiClient(
        server.origin,
        ca_file=str(server.ca_file),
        timeout_s=2.0,
        connect_timeout_s=1.0,
        max_retries=0,
    )


def test_riot_xy_maps_to_camera_x_height_z() -> None:
    cam = riot_xy_to_camera_position(1591.0, 9726.0, height=1910.0)
    assert cam.to_dict() == {"x": 1591.0, "y": 1910.0, "z": 9726.0}
    assert camera_position_to_riot_xy(cam.to_dict()) == (1591.0, 9726.0)
    assert ground_distance((1591.0, 9726.0), (1591.0, 9726.0)) == 0.0


def test_exact_kill_position_builds_path_plan() -> None:
    gst = make_gst(
        [
            fact(
                839_881,
                FactKind.CHAMPION_KILL,
                6,
                {"killerId": 1, "victimId": 6, "position": {"x": 1591, "y": 9726}},
            )
        ],
        match_id="NA1_test",
        participants=roster(),
    )
    target = resolve_gst_camera_target(gst, participant_id=6, target_game_t_ms=839_881)
    assert target is not None
    assert target.interpolated is False
    assert target.confidence == 1.0
    assert target.position.x == 1591.0
    assert target.position.y == 9726.0
    assert target.source_game_t_ms == 839_881
    plan = build_path_gst_framing_plan(target, stabilize_s=1.25)
    assert plan.strategy == CAMERA_STRATEGY_PATH_GST
    assert plan.camera_mode == CAMERA_MODE_PATH
    assert plan.camera_position.y == DEFAULT_CAMERA_HEIGHT
    assert plan.stabilize_s == 1.25
    assert plan.render_patch()["cameraMode"] == "path"
    assert plan.render_patch()["cameraPosition"] == {"x": 1591.0, "y": 1910.0, "z": 9726.0}


def test_interpolated_position_builds_plan() -> None:
    gst = make_gst(
        [
            fact(780_000, FactKind.POSITION, 6, {"x": 1000.0, "y": 9000.0}),
            fact(840_000, FactKind.POSITION, 6, {"x": 2000.0, "y": 10000.0}),
        ],
        match_id="NA1_interp",
        participants=roster(),
    )
    target = resolve_gst_camera_target(gst, participant_id=6, target_game_t_ms=810_000)
    assert target is not None
    assert target.interpolated is True
    assert target.confidence >= 0.15
    assert target.basis.startswith("interpolated")
    plan = build_path_gst_framing_plan(target)
    assert plan.camera_position.x == pytest.approx(1500.0)
    assert plan.camera_position.z == pytest.approx(9500.0)


def test_missing_and_stale_position_degrade_honestly() -> None:
    empty = make_gst([], match_id="NA1_empty", participants=roster())
    assert resolve_gst_camera_target(empty, participant_id=6, target_game_t_ms=1000) is None
    assert (
        resolve_gst_camera_target(empty, participant_id=99, target_game_t_ms=1000) is None
    )
    skipped = metadata_skipped(
        status=CameraFramingStatus.SKIPPED_NO_POSITION,
        participant_id=6,
        target_game_t_ms=1000,
    )
    assert skipped.camera_controlled is False
    assert skipped.status is CameraFramingStatus.SKIPPED_NO_POSITION

    far = make_gst(
        [
            fact(
                100_000,
                FactKind.CHAMPION_KILL,
                6,
                {"position": {"x": 1, "y": 1}, "victimId": 6},
            )
        ],
        match_id="NA1_stale",
        participants=roster(),
    )
    # Kill outside window and no POSITION facts → None (no invent).
    assert resolve_gst_camera_target(far, participant_id=6, target_game_t_ms=839_881) is None


def test_apply_stabilize_capture_restore_and_metadata(tmp_path: Path) -> None:
    behavior = FakeReplayBehavior(
        recording_instant=True,
        render={
            "fogOfWar": True,
            "cameraMode": "top",
            "cameraAttached": False,
            "cameraPosition": {"x": 100.0, "y": 1910.0, "z": 200.0},
            "cameraRotation": {"x": 0.0, "y": 40.0, "z": 0.0},
            "fieldOfView": 50.0,
            "selectionName": "",
        },
    )
    gst = make_gst(
        [
            fact(
                1_120_000,
                FactKind.CHAMPION_KILL,
                1,
                {"position": {"x": 1591, "y": 9726}, "victimId": 1},
            )
        ],
        match_id="NA1_cam",
        participants=roster(),
    )
    target = resolve_gst_camera_target(gst, participant_id=1, target_game_t_ms=1_120_000)
    assert target is not None
    plan = build_path_gst_framing_plan(target, stabilize_s=0.75)
    clock = FakeClock()
    with FakeReplayApiServer(behavior) as server:
        client = _client(server)
        saved, placed = apply_framing(client, plan, clock=clock)
        assert 0.75 in clock.sleeps
        assert placed.camera_controlled is True
        assert placed.status is CameraFramingStatus.PLACED
        assert placed.camera_mode == "path"
        assert placed.replay_camera_position == {
            "x": 1591.0,
            "y": DEFAULT_CAMERA_HEIGHT,
            "z": 9726.0,
        }
        assert behavior.render["cameraMode"] == "path"
        assert saved.patch["cameraMode"] == "top"

        result = run_capture(
            client=FramingStickyClient(client, plan),
            clock=_clock(),
            capture_id="cap_framing",
            start_game_ms=1_110_000,
            end_game_ms=1_135_000,
            directory=tmp_path / "out",
            mode=CaptureMode.CLIP,
            sleep_clock=clock,
            camera_framing=None,
        )
        assert result.ok is True

        final = restore_framing(client, saved, plan=plan, placed_meta=placed)
        assert final.restore_status is CameraFramingStatus.RESTORED
        assert behavior.render["cameraMode"] == "top"
        assert behavior.render["cameraPosition"] == {"x": 100.0, "y": 1910.0, "z": 200.0}


def test_run_capture_with_framing_end_to_end(tmp_path: Path) -> None:
    behavior = FakeReplayBehavior(
        recording_instant=True,
        render={
            "cameraMode": "top",
            "cameraPosition": {"x": 10.0, "y": 1910.0, "z": 20.0},
            "cameraAttached": False,
            "cameraRotation": {"x": 0.0, "y": 40.0, "z": 0.0},
            "fieldOfView": 50.0,
        },
    )
    target = resolve_gst_camera_target(
        make_gst(
            [
                fact(
                    1_120_000,
                    FactKind.CHAMPION_KILL,
                    1,
                    {"position": {"x": 4000, "y": 5000}, "victimId": 1},
                )
            ],
            match_id="NA1_e2e",
            participants=roster(),
        ),
        participant_id=1,
        target_game_t_ms=1_120_000,
    )
    assert target is not None
    plan = build_path_gst_framing_plan(target, stabilize_s=0.5)
    clock = FakeClock()
    with FakeReplayApiServer(behavior) as server:
        result = run_capture(
            client=_client(server),
            clock=_clock(),
            capture_id=new_ulid(),
            start_game_ms=1_110_000,
            end_game_ms=1_135_000,
            directory=tmp_path / "clip",
            mode=CaptureMode.CLIP,
            sleep_clock=clock,
            camera_framing=plan,
        )
    assert result.ok is True
    assert result.camera_framing is not None
    assert result.camera_framing.camera_controlled is True
    assert result.camera_framing.camera_strategy == CAMERA_STRATEGY_PATH_GST
    assert result.camera_framing.stabilize_s == 0.5
    assert result.camera_framing.restore_status is CameraFramingStatus.RESTORED
    assert 0.5 in clock.sleeps
    assert behavior.render["cameraMode"] == "top"


def test_restore_failure_logged_but_capture_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    behavior = FakeReplayBehavior(
        recording_instant=True,
        render={
            "cameraMode": "fps",
            "cameraPosition": {"x": 1.0, "y": 1910.0, "z": 2.0},
            "cameraAttached": False,
            "fieldOfView": 40.0,
        },
    )
    target = resolve_gst_camera_target(
        make_gst(
            [
                fact(
                    1_120_000,
                    FactKind.CHAMPION_KILL,
                    1,
                    {"position": {"x": 100, "y": 200}, "victimId": 1},
                )
            ],
            match_id="NA1_restore_fail",
            participants=roster(),
        ),
        participant_id=1,
        target_game_t_ms=1_120_000,
    )
    assert target is not None
    plan = build_path_gst_framing_plan(target)
    with FakeReplayApiServer(behavior) as server:
        client = _client(server)

        def boom(patch: Any) -> Any:
            raise ReplayError(
                ReplayErrorCode.REPLAY_API_UNAVAILABLE, details={"reason": "restore_boom"}
            )

        saved, placed = apply_framing(client, plan, clock=FakeClock())
        monkeypatch.setattr(client, "set_render", boom)
        meta = restore_framing(client, saved, plan=plan, placed_meta=placed)
        assert placed.camera_controlled is True
        assert meta.restore_status is CameraFramingStatus.RESTORE_FAILED
        assert meta.camera_controlled is True
        assert meta.restore_error is not None


def test_disabled_framing_leaves_render_untouched(tmp_path: Path) -> None:
    behavior = FakeReplayBehavior(
        recording_instant=True,
        render={"cameraMode": "top", "cameraPosition": {"x": 7.0, "y": 1.0, "z": 8.0}},
    )
    before = dict(behavior.render)
    with FakeReplayApiServer(behavior) as server:
        result = run_capture(
            client=_client(server),
            clock=_clock(),
            capture_id="no_frame",
            start_game_ms=1_110_000,
            end_game_ms=1_135_000,
            directory=tmp_path / "plain",
            mode=CaptureMode.CLIP,
            sleep_clock=FakeClock(),
            camera_framing=None,
        )
    assert result.ok is True
    assert result.camera_framing is None
    assert behavior.render == before


def test_capture_request_defaults_disable_framing() -> None:
    req = CaptureRequest(
        source_id="src",
        start_game_ms=0,
        end_game_ms=1000,
        mode=CaptureMode.CLIP,
    )
    assert req.camera_framing is None
    assert req.allow_capture_without_framing is True


def test_fake_host_reveal_never_starts_capture() -> None:
    host = FakeReplayHost(sleep_clock=FakeClock())
    outcome = host.reveal(100_000, _clock())
    assert host.capture_count == 0
    assert outcome.ok is False


def test_mac_reveal_source_has_no_camera_framing_calls() -> None:
    import inspect

    source = inspect.getsource(MacReplayHost.reveal)
    assert "camera_framing" not in source
    assert "set_render" not in source
    assert "apply_framing" not in source


def test_snapshot_render_keeps_restore_keys() -> None:
    behavior = FakeReplayBehavior(
        render={
            "cameraMode": "path",
            "cameraAttached": True,
            "cameraPosition": {"x": 1, "y": 2, "z": 3},
            "cameraRotation": {"x": 0, "y": 1, "z": 0},
            "fieldOfView": 42.0,
            "selectionName": "Vladimir",
            "selectionOffset": {"x": 0, "y": 0, "z": 0},
            "fogOfWar": False,
        }
    )
    with FakeReplayApiServer(behavior) as server:
        saved = snapshot_render(_client(server))
    assert "fogOfWar" not in saved.patch
    assert saved.patch["selectionName"] == "Vladimir"
    assert saved.patch["cameraMode"] == "path"


def test_apply_failed_refuses_when_unframed_disallowed(tmp_path: Path) -> None:
    class BrokenClient:
        def get_recording(self) -> Any:
            raise AssertionError("should not record")

        def set_recording(self, patch: Any) -> Any:
            raise AssertionError("should not record")

        def get_playback(self) -> Any:
            raise AssertionError("should not record")

        def set_playback(self, **kwargs: Any) -> Any:
            raise AssertionError("should not record")

        def get_render(self) -> Any:
            raise ReplayError(
                ReplayErrorCode.REPLAY_API_UNAVAILABLE, details={"reason": "no_render"}
            )

        def set_render(self, patch: Any) -> Any:
            raise ReplayError(
                ReplayErrorCode.REPLAY_API_UNAVAILABLE, details={"reason": "no_render"}
            )

    target = resolve_gst_camera_target(
        make_gst(
            [
                fact(
                    1000,
                    FactKind.CHAMPION_KILL,
                    1,
                    {"position": {"x": 1, "y": 2}, "victimId": 1},
                )
            ],
            match_id="NA1_fail",
            participants=roster(),
        ),
        participant_id=1,
        target_game_t_ms=1000,
    )
    assert target is not None
    plan = build_path_gst_framing_plan(target)
    result = run_capture(
        client=BrokenClient(),  # type: ignore[arg-type]
        clock=_clock(),
        capture_id="fail",
        start_game_ms=0,
        end_game_ms=1000,
        directory=tmp_path / "fail",
        mode=CaptureMode.CLIP,
        sleep_clock=FakeClock(),
        camera_framing=plan,
        allow_capture_without_framing=False,
    )
    assert result.ok is False
    assert result.status is CaptureStatus.FAILED
    assert result.camera_framing is not None
    assert result.camera_framing.status is CameraFramingStatus.APPLY_FAILED


def test_default_stabilize_constant() -> None:
    assert DEFAULT_STABILIZE_S == 1.5
