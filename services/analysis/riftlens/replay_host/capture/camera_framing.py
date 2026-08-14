"""Apply/restore Replay API camera framing for automated captures only."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from riftlens.domain.camera_framing import (
    CameraFramingMetadata,
    CameraFramingPlan,
    CameraFramingStatus,
    metadata_for_plan,
)
from riftlens.domain.replay_errors import ReplayError
from riftlens.replay_host.api.models import ReplayPlayback, ReplayRecording, ReplayRender
from riftlens.replay_host.timing import SleepClock, WallClock

log = logging.getLogger("riftlens.capture.camera_framing")

_RESTORE_KEYS = (
    "cameraMode",
    "cameraAttached",
    "cameraPosition",
    "cameraRotation",
    "fieldOfView",
    "selectionName",
    "selectionOffset",
)


class RenderClient(Protocol):
    """Minimal Replay API surface for capture camera control."""

    def get_render(self) -> ReplayRender:
        """GET /replay/render."""

    def set_render(self, patch: Mapping[str, Any]) -> ReplayRender:
        """POST /replay/render."""


@dataclass(frozen=True)
class SavedRenderState:
    """Prior ``/replay/render`` fields restored after capture when possible."""

    patch: dict[str, Any]


@dataclass
class FramingSession:
    """Mutable apply/restore outcome for one capture."""

    plan: CameraFramingPlan
    saved: SavedRenderState | None = None
    metadata: CameraFramingMetadata | None = None
    applied: bool = False


def snapshot_render(client: RenderClient) -> SavedRenderState:
    """GET render and keep fields needed to restore user camera state."""
    raw = _render_dict(client.get_render())
    patch = {key: raw[key] for key in _RESTORE_KEYS if key in raw}
    return SavedRenderState(patch=patch)


def apply_framing(
    client: RenderClient,
    plan: CameraFramingPlan,
    *,
    clock: SleepClock | None = None,
) -> tuple[SavedRenderState, CameraFramingMetadata]:
    """Snapshot, POST path+GST framing, stabilize. Raises ReplayError on API failure."""
    waiter = clock if clock is not None else WallClock()
    saved = snapshot_render(client)
    client.set_render(plan.render_patch())
    waiter.sleep(max(0.0, float(plan.stabilize_s)))
    settled = _render_dict(client.get_render())
    meta = metadata_for_plan(
        plan,
        status=CameraFramingStatus.PLACED,
        actual_camera_position=_as_float_map(settled.get("cameraPosition")),
        actual_camera_mode=_as_str(settled.get("cameraMode")) or plan.camera_mode,
    )
    return saved, meta


def restore_framing(
    client: RenderClient,
    saved: SavedRenderState,
    *,
    plan: CameraFramingPlan,
    placed_meta: CameraFramingMetadata,
) -> CameraFramingMetadata:
    """Restore prior render state. Logs restore failures; does not raise."""
    try:
        client.set_render(saved.patch)
        return metadata_for_plan(
            plan,
            status=CameraFramingStatus.PLACED,
            restore_status=CameraFramingStatus.RESTORED,
            actual_camera_position=placed_meta.replay_camera_position,
            actual_camera_mode=placed_meta.camera_mode,
        )
    except ReplayError as exc:
        log.error(
            "capture_camera_restore_failed",
            extra={"error": str(exc), "details": dict(exc.details)},
        )
        return metadata_for_plan(
            plan,
            status=CameraFramingStatus.PLACED,
            restore_status=CameraFramingStatus.RESTORE_FAILED,
            restore_error=str(exc),
            actual_camera_position=placed_meta.replay_camera_position,
            actual_camera_mode=placed_meta.camera_mode,
        )


class FramingApiClient(Protocol):
    """Recording + render surface used by the sticky capture wrapper."""

    def get_recording(self) -> ReplayRecording:
        """GET /replay/recording."""

    def set_recording(self, patch: Mapping[str, Any]) -> ReplayRecording:
        """POST /replay/recording."""

    def get_playback(self) -> ReplayPlayback:
        """GET /replay/playback."""

    def set_playback(
        self,
        *,
        paused: bool | None = None,
        time: float | None = None,
        speed: float | None = None,
        readback: bool = True,
    ) -> ReplayPlayback | None:
        """POST /replay/playback."""

    def get_render(self) -> ReplayRender:
        """GET /replay/render."""

    def set_render(self, patch: Mapping[str, Any]) -> ReplayRender:
        """POST /replay/render."""


class FramingStickyClient:
    """Re-apply framing after capture seek so encode does not keep Directed/top."""

    def __init__(self, inner: FramingApiClient, plan: CameraFramingPlan) -> None:
        self._inner = inner
        self._patch = plan.render_patch()

    def get_recording(self) -> ReplayRecording:
        return self._inner.get_recording()

    def set_recording(self, patch: Mapping[str, Any]) -> ReplayRecording:
        try:
            self._inner.set_render(self._patch)
        except ReplayError:
            log.warning("capture_camera_reapply_before_recording_failed")
        return self._inner.set_recording(patch)

    def get_playback(self) -> ReplayPlayback:
        return self._inner.get_playback()

    def set_playback(
        self,
        *,
        paused: bool | None = None,
        time: float | None = None,
        speed: float | None = None,
        readback: bool = True,
    ) -> ReplayPlayback | None:
        result = self._inner.set_playback(
            paused=paused, time=time, speed=speed, readback=readback
        )
        if time is not None:
            try:
                self._inner.set_render(self._patch)
            except ReplayError:
                log.warning("capture_camera_reapply_after_seek_failed")
        return result

    def get_render(self) -> ReplayRender:
        return self._inner.get_render()

    def set_render(self, patch: Mapping[str, Any]) -> ReplayRender:
        return self._inner.set_render(patch)


def _render_dict(render: Any) -> dict[str, Any]:
    if hasattr(render, "model_dump"):
        return dict(render.model_dump())
    return dict(render)


def _as_float_map(value: Any) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return {str(k): float(v) for k, v in value.items()}
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
