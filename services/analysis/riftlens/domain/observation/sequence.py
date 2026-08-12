from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from riftlens.domain.observation.common import (
    mapping_or_error,
    optional_confidence,
    require_confidence,
    require_game_ms,
    require_non_empty,
    require_schema_version,
    require_ulid,
)
from riftlens.domain.observation.enums import (
    FRAME_OBSERVATION_SCHEMA_VERSION,
    ObservationPayloadError,
)
from riftlens.domain.observation.frame_observation import FrameObservation


@dataclass(frozen=True)
class SampleGap:
    """Explicit unsampled or missing span inside a visual window. Not inferred."""

    after_game_t_ms: int
    gap_ms: int
    reason: str

    def __post_init__(self) -> None:
        require_game_ms("after_game_t_ms", self.after_game_t_ms)
        if isinstance(self.gap_ms, bool) or not isinstance(self.gap_ms, int) or self.gap_ms <= 0:
            raise ObservationPayloadError("gap_ms must be a positive int")
        object.__setattr__(self, "reason", require_non_empty("gap.reason", self.reason))

    def to_dict(self) -> dict[str, Any]:
        return {
            "after_game_t_ms": self.after_game_t_ms,
            "gap_ms": self.gap_ms,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SampleGap:
        data = mapping_or_error(payload, what="SampleGap")
        return cls(
            after_game_t_ms=require_game_ms("after_game_t_ms", data.get("after_game_t_ms")),
            gap_ms=int(data.get("gap_ms", 0)),
            reason=str(data.get("reason", "")),
        )


@dataclass(frozen=True)
class ObservationSequence:
    """Ordered FrameObservations over a capture interval (a visual window).

    Ordering is deterministic: ``(game_t_ms, observation_id)``. Gaps are stored
    explicitly; this type does not infer rotations, fights, or coaching.
    """

    sequence_id: str
    capture_interval_id: str
    media_artifact_id: str
    match_id: str
    gameplay_source_id: str
    start_game_ms: int
    end_game_ms: int
    frames: tuple[FrameObservation, ...]
    detector_id: str
    detector_version: str
    schema_version: str = FRAME_OBSERVATION_SCHEMA_VERSION
    sample_count: int | None = None
    expected_sample_count: int | None = None
    gaps: tuple[SampleGap, ...] = ()
    sampling_interval_ms: int | None = None
    clock_map_id: str | None = None
    confidence: float | None = None
    artifact_relative_path: str | None = None
    artifact_sha256: str | None = None

    def __post_init__(self) -> None:
        require_ulid("sequence_id", self.sequence_id)
        object.__setattr__(self, "match_id", require_non_empty("match_id", self.match_id))
        object.__setattr__(
            self,
            "capture_interval_id",
            require_non_empty("capture_interval_id", self.capture_interval_id),
        )
        object.__setattr__(
            self,
            "media_artifact_id",
            require_non_empty("media_artifact_id", self.media_artifact_id),
        )
        object.__setattr__(
            self,
            "gameplay_source_id",
            require_non_empty("gameplay_source_id", self.gameplay_source_id),
        )
        require_game_ms("start_game_ms", self.start_game_ms)
        require_game_ms("end_game_ms", self.end_game_ms)
        if self.end_game_ms < self.start_game_ms:
            raise ObservationPayloadError("end_game_ms must be >= start_game_ms")
        object.__setattr__(self, "detector_id", require_non_empty("detector_id", self.detector_id))
        object.__setattr__(
            self, "detector_version", require_non_empty("detector_version", self.detector_version)
        )
        require_schema_version(self.schema_version)
        if self.confidence is not None:
            require_confidence("sequence.confidence", self.confidence)
        if self.sampling_interval_ms is not None and (
            isinstance(self.sampling_interval_ms, bool)
            or not isinstance(self.sampling_interval_ms, int)
            or self.sampling_interval_ms <= 0
        ):
            raise ObservationPayloadError("sampling_interval_ms must be a positive int")
        if self.expected_sample_count is not None and (
            isinstance(self.expected_sample_count, bool)
            or not isinstance(self.expected_sample_count, int)
            or self.expected_sample_count < 0
        ):
            raise ObservationPayloadError("expected_sample_count must be >= 0")
        ordered = tuple(sorted(self.frames, key=lambda item: (item.game_t_ms, item.observation_id)))
        object.__setattr__(self, "frames", ordered)
        count = len(ordered) if self.sample_count is None else self.sample_count
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ObservationPayloadError("sample_count must be >= 0")
        if count < len(ordered):
            raise ObservationPayloadError("sample_count cannot be less than the number of frames")
        object.__setattr__(self, "sample_count", count)
        for frame in ordered:
            if frame.match_id != self.match_id:
                raise ObservationPayloadError("frame match_id does not match sequence")
            if frame.capture_interval_id != self.capture_interval_id:
                raise ObservationPayloadError("frame capture_interval_id does not match sequence")
            if frame.media_artifact_id != self.media_artifact_id:
                raise ObservationPayloadError("frame media_artifact_id does not match sequence")
            if frame.gameplay_source_id != self.gameplay_source_id:
                raise ObservationPayloadError("frame gameplay_source_id does not match sequence")
            if frame.game_t_ms < self.start_game_ms or frame.game_t_ms > self.end_game_ms:
                raise ObservationPayloadError("frame game_t_ms is outside the sequence window")
            if self.clock_map_id and frame.clock_map_id and frame.clock_map_id != self.clock_map_id:
                raise ObservationPayloadError("frame clock_map_id does not match sequence")
        for gap in self.gaps:
            if gap.after_game_t_ms < self.start_game_ms or gap.after_game_t_ms > self.end_game_ms:
                raise ObservationPayloadError("gap after_game_t_ms is outside the sequence window")

    @property
    def analyzer_id(self) -> str:
        return self.detector_id

    @property
    def analyzer_version(self) -> str:
        return self.detector_version

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence_id": self.sequence_id,
            "capture_interval_id": self.capture_interval_id,
            "media_artifact_id": self.media_artifact_id,
            "match_id": self.match_id,
            "gameplay_source_id": self.gameplay_source_id,
            "start_game_ms": self.start_game_ms,
            "end_game_ms": self.end_game_ms,
            "frames": [item.to_dict() for item in self.frames],
            "detector_id": self.detector_id,
            "detector_version": self.detector_version,
            "analyzer_id": self.detector_id,
            "analyzer_version": self.detector_version,
            "schema_version": self.schema_version,
            "sample_count": self.sample_count,
            "expected_sample_count": self.expected_sample_count,
            "gaps": [item.to_dict() for item in self.gaps],
            "sampling_interval_ms": self.sampling_interval_ms,
            "clock_map_id": self.clock_map_id,
            "confidence": self.confidence,
            "artifact_relative_path": self.artifact_relative_path,
            "artifact_sha256": self.artifact_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ObservationSequence:
        data = mapping_or_error(payload, what="ObservationSequence")
        require_schema_version(data.get("schema_version"))
        frames_raw = data.get("frames", [])
        if not isinstance(frames_raw, Sequence) or isinstance(frames_raw, (str, bytes)):
            raise ObservationPayloadError("frames must be an array")
        gaps_raw = data.get("gaps", [])
        if gaps_raw is None:
            gaps_raw = []
        if not isinstance(gaps_raw, Sequence) or isinstance(gaps_raw, (str, bytes)):
            raise ObservationPayloadError("gaps must be an array")
        detector_id = data.get("detector_id", data.get("analyzer_id"))
        detector_version = data.get("detector_version", data.get("analyzer_version"))
        return cls(
            sequence_id=str(data.get("sequence_id", "")),
            capture_interval_id=str(data.get("capture_interval_id", "")),
            media_artifact_id=str(data.get("media_artifact_id", "")),
            match_id=str(data.get("match_id", "")),
            gameplay_source_id=str(data.get("gameplay_source_id", "")),
            start_game_ms=require_game_ms("start_game_ms", data.get("start_game_ms")),
            end_game_ms=require_game_ms("end_game_ms", data.get("end_game_ms")),
            frames=tuple(FrameObservation.from_dict(item) for item in frames_raw),
            detector_id=str(detector_id or ""),
            detector_version=str(detector_version or ""),
            schema_version=str(data.get("schema_version", "")),
            sample_count=None if data.get("sample_count") is None else int(data["sample_count"]),
            expected_sample_count=(
                None
                if data.get("expected_sample_count") is None
                else int(data["expected_sample_count"])
            ),
            gaps=tuple(SampleGap.from_dict(item) for item in gaps_raw),
            sampling_interval_ms=(
                None
                if data.get("sampling_interval_ms") is None
                else int(data["sampling_interval_ms"])
            ),
            clock_map_id=None
            if data.get("clock_map_id") in (None, "")
            else str(data["clock_map_id"]),
            confidence=optional_confidence("sequence.confidence", data.get("confidence")),
            artifact_relative_path=(
                None
                if data.get("artifact_relative_path") in (None, "")
                else str(data["artifact_relative_path"])
            ),
            artifact_sha256=(
                None if data.get("artifact_sha256") in (None, "") else str(data["artifact_sha256"])
            ),
        )


VisualWindow = ObservationSequence
