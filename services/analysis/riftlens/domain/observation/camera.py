from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from riftlens.domain.observation.common import (
    ScreenRect,
    optional_rect,
    require_confidence,
    require_non_empty,
)
from riftlens.domain.observation.enums import CameraControl, KnowledgeState, ObservationPayloadError


@dataclass(frozen=True)
class CameraProvenance:
    """Camera lock/target state for one sampled frame.

    Capture ownership (a clip taken for a Kaisa finding) does not imply the
    reviewed champion is visible or that the camera was locked to them.
    ``camera_controlled=false`` from R.10 maps to UNCONTROLLED, not UNKNOWN.
    ``camera_controlled=true`` only means the camera was locked; subject vs
    other remains UNKNOWN unless a future analyzer establishes the target.
    """

    control: CameraControl
    confidence: float
    target_participant_id: int | None = None
    target_knowledge: KnowledgeState = KnowledgeState.UNKNOWN
    viewport_width: int | None = None
    viewport_height: int | None = None
    crop: ScreenRect | None = None
    mode: str | None = None

    def __post_init__(self) -> None:
        require_confidence("camera.confidence", self.confidence)
        if self.target_participant_id is not None:
            if isinstance(self.target_participant_id, bool) or not isinstance(
                self.target_participant_id, int
            ):
                raise ObservationPayloadError("camera.target_participant_id must be an int")
            if self.target_participant_id < 1:
                raise ObservationPayloadError("camera.target_participant_id must be >= 1")
        if self.viewport_width is not None and (
            isinstance(self.viewport_width, bool)
            or not isinstance(self.viewport_width, int)
            or self.viewport_width <= 0
        ):
            raise ObservationPayloadError("camera.viewport_width must be a positive int")
        if self.viewport_height is not None and (
            isinstance(self.viewport_height, bool)
            or not isinstance(self.viewport_height, int)
            or self.viewport_height <= 0
        ):
            raise ObservationPayloadError("camera.viewport_height must be a positive int")
        if self.mode is not None:
            object.__setattr__(self, "mode", require_non_empty("camera.mode", self.mode))
        if (
            self.control is CameraControl.UNCONTROLLED
            and self.target_knowledge is KnowledgeState.KNOWN
        ):
            raise ObservationPayloadError("uncontrolled camera cannot have a known target")

    def to_dict(self) -> dict[str, Any]:
        return {
            "control": self.control.value,
            "confidence": self.confidence,
            "target_participant_id": self.target_participant_id,
            "target_knowledge": self.target_knowledge.value,
            "viewport_width": self.viewport_width,
            "viewport_height": self.viewport_height,
            "crop": None if self.crop is None else self.crop.to_dict(),
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CameraProvenance:
        try:
            control = CameraControl(str(payload["control"]))
            target_knowledge = KnowledgeState(
                str(payload.get("target_knowledge", KnowledgeState.UNKNOWN.value))
            )
        except (KeyError, ValueError) as exc:
            raise ObservationPayloadError("camera payload is malformed") from exc
        return cls(
            control=control,
            confidence=require_confidence("camera.confidence", payload.get("confidence")),
            target_participant_id=_optional_pid(payload.get("target_participant_id")),
            target_knowledge=target_knowledge,
            viewport_width=_optional_positive_int(payload.get("viewport_width")),
            viewport_height=_optional_positive_int(payload.get("viewport_height")),
            crop=optional_rect(payload.get("crop")),
            mode=None if payload.get("mode") is None else str(payload["mode"]),
        )


def camera_from_capture(*, camera_controlled: bool | None) -> CameraProvenance:
    """Map R.10 ``camera_controlled`` onto camera provenance without inferring the subject.

    False → UNCONTROLLED (established). True → UNKNOWN control-target (locked, but
    subject vs other is not proven by the capture flag). None → UNKNOWN.
    """
    if camera_controlled is False:
        return CameraProvenance(
            control=CameraControl.UNCONTROLLED,
            confidence=1.0,
            target_knowledge=KnowledgeState.UNKNOWN,
            mode="user",
        )
    if camera_controlled is True:
        return CameraProvenance(
            control=CameraControl.UNKNOWN,
            confidence=0.0,
            target_knowledge=KnowledgeState.UNKNOWN,
            mode="controlled",
        )
    return CameraProvenance(
        control=CameraControl.UNKNOWN,
        confidence=0.0,
        target_knowledge=KnowledgeState.UNKNOWN,
    )


def _optional_pid(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ObservationPayloadError("camera.target_participant_id must be an int")
    return value


def _optional_positive_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ObservationPayloadError("viewport dimension must be an int")
    return value
