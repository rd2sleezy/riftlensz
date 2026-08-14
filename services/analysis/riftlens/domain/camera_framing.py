"""Capture-time camera framing plans (pure). Replay API I/O lives in replay_host."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from riftlens.domain.enums import FactKind
from riftlens.domain.fact import SubjectRef
from riftlens.domain.geometry import Point
from riftlens.domain.timeline import GameStateTimeline

# Spike-validated default height for Summoner's Rift champion/fight framing.
DEFAULT_CAMERA_HEIGHT = 1910.0
DEFAULT_STABILIZE_S = 1.5
# Reject "no position facts" (0.0). Mid-gap interpolate bottoms at ~0.15.
MIN_POSITION_CONFIDENCE = 0.15
# Prefer an on-victim kill position within this window of the target.
KILL_POSITION_WINDOW_MS = 8_000
CAMERA_STRATEGY_PATH_GST = "path_gst_position"
CAMERA_MODE_PATH = "path"


class CameraFramingStatus(StrEnum):
    """Outcome of resolving/applying capture camera framing."""

    PLACED = "placed"
    SKIPPED_DISABLED = "skipped_disabled"
    SKIPPED_NO_POSITION = "skipped_no_position"
    SKIPPED_LOW_CONFIDENCE = "skipped_low_confidence"
    APPLY_FAILED = "apply_failed"
    RESTORED = "restored"
    RESTORE_FAILED = "restore_failed"


@dataclass(frozen=True)
class CameraWorldPosition:
    """Replay API ``cameraPosition`` triple (y = height)."""

    x: float
    y: float
    z: float

    def to_dict(self) -> dict[str, float]:
        """Return JSON-ready camera coordinates."""
        return {"x": float(self.x), "y": float(self.y), "z": float(self.z)}


@dataclass(frozen=True)
class GstCameraTarget:
    """GST-derived ground target used for capture framing."""

    participant_id: int
    target_game_t_ms: int
    source_game_t_ms: int
    position: Point
    confidence: float
    interpolated: bool
    basis: str

    def to_dict(self) -> dict[str, Any]:
        """Return metadata for capture manifests."""
        return {
            "participant_id": self.participant_id,
            "target_game_t_ms": self.target_game_t_ms,
            "source_game_t_ms": self.source_game_t_ms,
            "position": {"x": self.position.x, "y": self.position.y},
            "confidence": self.confidence,
            "interpolated": self.interpolated,
            "basis": self.basis,
        }


@dataclass(frozen=True)
class CameraFramingPlan:
    """Deterministic render patch for one capture. Built before any Replay API call."""

    strategy: str
    camera_mode: str
    camera_position: CameraWorldPosition
    target: GstCameraTarget
    stabilize_s: float
    camera_attached: bool = False
    field_of_view: float = 40.0
    camera_rotation: Mapping[str, float] | None = None

    def render_patch(self) -> dict[str, Any]:
        """Return the POST ``/replay/render`` body for path+GST framing."""
        rotation = (
            dict(self.camera_rotation)
            if self.camera_rotation is not None
            else {"x": 0.0, "y": 56.0, "z": 0.0}
        )
        return {
            "cameraMode": self.camera_mode,
            "cameraAttached": bool(self.camera_attached),
            "cameraPosition": self.camera_position.to_dict(),
            "cameraRotation": rotation,
            "fieldOfView": float(self.field_of_view),
        }

    def to_dict(self) -> dict[str, Any]:
        """Return plan fields for manifests / tests."""
        return {
            "strategy": self.strategy,
            "camera_mode": self.camera_mode,
            "camera_position": self.camera_position.to_dict(),
            "target": self.target.to_dict(),
            "stabilize_s": self.stabilize_s,
            "camera_attached": self.camera_attached,
            "field_of_view": self.field_of_view,
            "camera_rotation": (
                None if self.camera_rotation is None else dict(self.camera_rotation)
            ),
        }


@dataclass(frozen=True)
class CameraFramingMetadata:
    """Persisted capture-camera provenance (does not mutate GST)."""

    camera_controlled: bool
    camera_strategy: str | None
    status: CameraFramingStatus
    target_participant_id: int | None
    gst_target_t_ms: int | None
    gst_source_t_ms: int | None
    gst_position: Mapping[str, float] | None
    gst_confidence: float | None
    gst_interpolated: bool | None
    gst_basis: str | None
    replay_camera_position: Mapping[str, float] | None
    camera_mode: str | None
    stabilize_s: float | None
    restore_status: CameraFramingStatus | None
    placement_error: str | None = None
    restore_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return JSON for ``manifest.camera_framing``."""
        return {
            "camera_controlled": self.camera_controlled,
            "camera_strategy": self.camera_strategy,
            "status": self.status.value,
            "target_participant_id": self.target_participant_id,
            "gst_target_t_ms": self.gst_target_t_ms,
            "gst_source_t_ms": self.gst_source_t_ms,
            "gst_position": None if self.gst_position is None else dict(self.gst_position),
            "gst_confidence": self.gst_confidence,
            "gst_interpolated": self.gst_interpolated,
            "gst_basis": self.gst_basis,
            "replay_camera_position": (
                None
                if self.replay_camera_position is None
                else dict(self.replay_camera_position)
            ),
            "camera_mode": self.camera_mode,
            "stabilize_s": self.stabilize_s,
            "restore_status": None if self.restore_status is None else self.restore_status.value,
            "placement_error": self.placement_error,
            "restore_error": self.restore_error,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CameraFramingMetadata:
        """Parse metadata written by ``to_dict``."""
        restore_raw = payload.get("restore_status")
        return cls(
            camera_controlled=bool(payload.get("camera_controlled", False)),
            camera_strategy=_opt_str(payload.get("camera_strategy")),
            status=CameraFramingStatus(str(payload.get("status", "skipped_disabled"))),
            target_participant_id=_opt_int(payload.get("target_participant_id")),
            gst_target_t_ms=_opt_int(payload.get("gst_target_t_ms")),
            gst_source_t_ms=_opt_int(payload.get("gst_source_t_ms")),
            gst_position=_opt_float_map(payload.get("gst_position")),
            gst_confidence=_opt_float(payload.get("gst_confidence")),
            gst_interpolated=(
                None
                if payload.get("gst_interpolated") is None
                else bool(payload.get("gst_interpolated"))
            ),
            gst_basis=_opt_str(payload.get("gst_basis")),
            replay_camera_position=_opt_float_map(payload.get("replay_camera_position")),
            camera_mode=_opt_str(payload.get("camera_mode")),
            stabilize_s=_opt_float(payload.get("stabilize_s")),
            restore_status=(
                None if restore_raw is None else CameraFramingStatus(str(restore_raw))
            ),
            placement_error=_opt_str(payload.get("placement_error")),
            restore_error=_opt_str(payload.get("restore_error")),
        )


def riot_xy_to_camera_position(
    x: float,
    y: float,
    *,
    height: float = DEFAULT_CAMERA_HEIGHT,
) -> CameraWorldPosition:
    """Map Riot/GST ground ``(x, y)`` to Replay API ``cameraPosition`` (y=height, z=riot y)."""
    return CameraWorldPosition(x=float(x), y=float(height), z=float(y))


def camera_position_to_riot_xy(pos: Mapping[str, Any] | None) -> tuple[float, float] | None:
    """Inverse of ``riot_xy_to_camera_position`` when ``pos`` has x/z."""
    if not isinstance(pos, Mapping):
        return None
    try:
        return float(pos["x"]), float(pos["z"])
    except (KeyError, TypeError, ValueError):
        return None


def ground_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Euclidean distance on the Riot ground plane."""
    return float(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5)


def resolve_gst_camera_target(
    gst: GameStateTimeline,
    *,
    participant_id: int,
    target_game_t_ms: int,
    min_confidence: float = MIN_POSITION_CONFIDENCE,
    kill_window_ms: int = KILL_POSITION_WINDOW_MS,
) -> GstCameraTarget | None:
    """Resolve the best GST ground position at/before ``target_game_t_ms``.

    Prefers an on-victim ``CHAMPION_KILL`` position near the target, then
    ``interpolate_position``. Returns None when unavailable or below confidence.
    """
    if participant_id not in gst.participants:
        return None
    kill = _nearest_victim_kill_position(
        gst,
        participant_id=participant_id,
        target_game_t_ms=target_game_t_ms,
        window_ms=kill_window_ms,
    )
    if kill is not None:
        return kill
    estimate = gst.interpolate_position(participant_id, int(target_game_t_ms))
    if estimate.confidence < float(min_confidence):
        return None
    if "no position facts" in estimate.basis:
        return None
    interpolated = "interpolated" in estimate.basis or "before last" in estimate.basis
    source_t = int(target_game_t_ms)
    if "frames" in estimate.basis:
        # basis like "interpolated between frames A,B" or "participant frame at t=..."
        source_t = _source_t_from_basis(estimate.basis, fallback=target_game_t_ms)
    return GstCameraTarget(
        participant_id=int(participant_id),
        target_game_t_ms=int(target_game_t_ms),
        source_game_t_ms=source_t,
        position=estimate.value,
        confidence=float(estimate.confidence),
        interpolated=bool(interpolated),
        basis=estimate.basis,
    )


def build_path_gst_framing_plan(
    target: GstCameraTarget,
    *,
    height: float = DEFAULT_CAMERA_HEIGHT,
    stabilize_s: float = DEFAULT_STABILIZE_S,
) -> CameraFramingPlan:
    """Build the spike-proven ``path`` + GST world-position capture plan."""
    camera = riot_xy_to_camera_position(target.position.x, target.position.y, height=height)
    return CameraFramingPlan(
        strategy=CAMERA_STRATEGY_PATH_GST,
        camera_mode=CAMERA_MODE_PATH,
        camera_position=camera,
        target=target,
        stabilize_s=float(stabilize_s),
        camera_attached=False,
    )


def metadata_for_plan(
    plan: CameraFramingPlan,
    *,
    status: CameraFramingStatus,
    restore_status: CameraFramingStatus | None = None,
    placement_error: str | None = None,
    restore_error: str | None = None,
    actual_camera_position: Mapping[str, float] | None = None,
    actual_camera_mode: str | None = None,
) -> CameraFramingMetadata:
    """Build manifest metadata from a plan and apply/restore outcome."""
    controlled = status in {
        CameraFramingStatus.PLACED,
        CameraFramingStatus.RESTORED,
        CameraFramingStatus.RESTORE_FAILED,
    }
    return CameraFramingMetadata(
        camera_controlled=controlled,
        camera_strategy=plan.strategy,
        status=status,
        target_participant_id=plan.target.participant_id,
        gst_target_t_ms=plan.target.target_game_t_ms,
        gst_source_t_ms=plan.target.source_game_t_ms,
        gst_position={"x": plan.target.position.x, "y": plan.target.position.y},
        gst_confidence=plan.target.confidence,
        gst_interpolated=plan.target.interpolated,
        gst_basis=plan.target.basis,
        replay_camera_position=(
            dict(actual_camera_position)
            if actual_camera_position is not None
            else plan.camera_position.to_dict()
        ),
        camera_mode=actual_camera_mode or plan.camera_mode,
        stabilize_s=plan.stabilize_s,
        restore_status=restore_status,
        placement_error=placement_error,
        restore_error=restore_error,
    )


def metadata_skipped(
    *,
    status: CameraFramingStatus,
    participant_id: int | None = None,
    target_game_t_ms: int | None = None,
) -> CameraFramingMetadata:
    """Metadata when framing was not applied."""
    return CameraFramingMetadata(
        camera_controlled=False,
        camera_strategy=None,
        status=status,
        target_participant_id=participant_id,
        gst_target_t_ms=target_game_t_ms,
        gst_source_t_ms=None,
        gst_position=None,
        gst_confidence=None,
        gst_interpolated=None,
        gst_basis=None,
        replay_camera_position=None,
        camera_mode=None,
        stabilize_s=None,
        restore_status=None,
    )


def _nearest_victim_kill_position(
    gst: GameStateTimeline,
    *,
    participant_id: int,
    target_game_t_ms: int,
    window_ms: int,
) -> GstCameraTarget | None:
    subject = SubjectRef(kind="participant", id=participant_id)
    kills = gst.facts(kind=FactKind.CHAMPION_KILL, subject=subject)
    best: GstCameraTarget | None = None
    best_delta: int | None = None
    for fact in kills:
        delta = abs(int(fact.t_ms) - int(target_game_t_ms))
        if delta > int(window_ms):
            continue
        pos = fact.payload.get("position")
        if not isinstance(pos, Mapping):
            continue
        try:
            point = Point(float(pos["x"]), float(pos["y"]))
        except (KeyError, TypeError, ValueError):
            continue
        if best_delta is not None and delta >= best_delta:
            continue
        best_delta = delta
        best = GstCameraTarget(
            participant_id=int(participant_id),
            target_game_t_ms=int(target_game_t_ms),
            source_game_t_ms=int(fact.t_ms),
            position=point,
            confidence=1.0,
            interpolated=False,
            basis=f"champion_kill position at t={fact.t_ms}",
        )
    return best


def _source_t_from_basis(basis: str, *, fallback: int) -> int:
    if "participant frame at t=" in basis:
        try:
            return int(basis.rsplit("t=", 1)[-1])
        except ValueError:
            return int(fallback)
    if "between frames" in basis:
        try:
            raw = basis.rsplit("frames ", 1)[-1]
            left = int(raw.split(",", 1)[0])
            return left
        except (IndexError, ValueError):
            return int(fallback)
    return int(fallback)


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _opt_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _opt_float_map(value: Any) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return {str(k): float(v) for k, v in value.items()}
    except (TypeError, ValueError):
        return None
