from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from riftlens.domain.enums import Source
from riftlens.domain.fact import Provenance
from riftlens.domain.ids import is_ulid
from riftlens.domain.observation.camera import CameraProvenance
from riftlens.domain.observation.common import (
    mapping_or_error,
    optional_game_ms,
    require_confidence,
    require_game_ms,
    require_non_empty,
    require_schema_version,
    require_ulid,
)
from riftlens.domain.observation.entity import EntityObservation
from riftlens.domain.observation.enums import (
    FRAME_OBSERVATION_SCHEMA_VERSION,
    ObservationPayloadError,
    VisualClaimKind,
)
from riftlens.domain.observation.hud import HudObservation
from riftlens.domain.observation.spatial import SpatialObservation

_FRAME_KEYS = frozenset(
    {
        "observation_id",
        "match_id",
        "gameplay_source_id",
        "capture_interval_id",
        "media_artifact_id",
        "game_t_ms",
        "source_t_ms",
        "clock_map_id",
        "schema_version",
        "observation_type",
        "detector_id",
        "detector_version",
        "analyzer_id",
        "analyzer_version",
        "confidence",
        "claim_kind",
        "source",
        "camera",
        "entities",
        "hud",
        "spatial",
        "payload",
        "artifact_relative_path",
        "artifact_sha256",
        "extensions",
    }
)


@dataclass(frozen=True)
class FrameObservation:
    """One sampled-frame visual observation. Parallel to GST; never a Riot fact.

    Architecture §8.1 fields are first-class. Typed camera/entity/HUD/spatial
    payloads live beside the free ``payload`` bag for detector-specific data.
    GAME time (``game_t_ms``) is the canonical coaching-domain timestamp.
    """

    observation_id: str
    match_id: str
    gameplay_source_id: str
    capture_interval_id: str
    media_artifact_id: str
    game_t_ms: int
    clock_map_id: str | None
    observation_type: str
    confidence: float
    detector_id: str
    detector_version: str
    camera: CameraProvenance
    schema_version: str = FRAME_OBSERVATION_SCHEMA_VERSION
    claim_kind: VisualClaimKind = VisualClaimKind.OBSERVED
    source_t_ms: int | None = None
    artifact_relative_path: str | None = None
    artifact_sha256: str | None = None
    entities: tuple[EntityObservation, ...] = ()
    hud: HudObservation | None = None
    spatial: SpatialObservation | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_ulid("observation_id", self.observation_id)
        object.__setattr__(self, "match_id", require_non_empty("match_id", self.match_id))
        object.__setattr__(
            self, "gameplay_source_id", _id_or_ulid("gameplay_source_id", self.gameplay_source_id)
        )
        object.__setattr__(
            self,
            "capture_interval_id",
            _id_or_ulid("capture_interval_id", self.capture_interval_id),
        )
        object.__setattr__(
            self,
            "media_artifact_id",
            require_non_empty("media_artifact_id", self.media_artifact_id),
        )
        require_game_ms("game_t_ms", self.game_t_ms)
        optional_game_ms("source_t_ms", self.source_t_ms)
        if self.clock_map_id is not None:
            object.__setattr__(
                self, "clock_map_id", require_non_empty("clock_map_id", self.clock_map_id)
            )
        object.__setattr__(
            self, "observation_type", require_non_empty("observation_type", self.observation_type)
        )
        object.__setattr__(self, "detector_id", require_non_empty("detector_id", self.detector_id))
        object.__setattr__(
            self, "detector_version", require_non_empty("detector_version", self.detector_version)
        )
        require_confidence("confidence", self.confidence)
        require_schema_version(self.schema_version)
        if self.artifact_relative_path is not None:
            object.__setattr__(
                self,
                "artifact_relative_path",
                require_non_empty("artifact_relative_path", self.artifact_relative_path),
            )
        if self.artifact_sha256 is not None:
            digest = require_non_empty("artifact_sha256", self.artifact_sha256).lower()
            if any(char not in "0123456789abcdef" for char in digest) or len(digest) != 64:
                raise ObservationPayloadError("artifact_sha256 must be a 64-char hex digest")
            object.__setattr__(self, "artifact_sha256", digest)
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "extensions", MappingProxyType(dict(self.extensions)))
        if any(key in {"time", "timestamp"} for key in self.payload):
            raise ObservationPayloadError(
                "payload must not use ambiguous time/timestamp keys; use game_t_ms/source_t_ms"
            )

    @property
    def source(self) -> Source:
        """Return VISUAL or VISUAL_INFERRED. Never a Riot/GST source."""
        if self.claim_kind is VisualClaimKind.INFERRED:
            return Source.VISUAL_INFERRED
        return Source.VISUAL

    @property
    def analyzer_id(self) -> str:
        return self.detector_id

    @property
    def analyzer_version(self) -> str:
        return self.detector_version

    def as_provenance(self) -> Provenance:
        """Return H.6 Provenance linking this observation to its R.10 source material."""
        upstream = [
            f"observation:{self.observation_id}",
            f"artifact:{self.media_artifact_id}",
            f"capture:{self.capture_interval_id}",
            f"detector:{self.detector_id}@{self.detector_version}",
        ]
        if self.clock_map_id:
            upstream.append(f"clock_map:{self.clock_map_id}")
        if self.artifact_sha256:
            upstream.append(f"sha256:{self.artifact_sha256}")
        return Provenance(
            producer=self.detector_id,
            producer_version=11,
            upstream=tuple(upstream),
        )

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "observation_id": self.observation_id,
            "match_id": self.match_id,
            "gameplay_source_id": self.gameplay_source_id,
            "capture_interval_id": self.capture_interval_id,
            "media_artifact_id": self.media_artifact_id,
            "game_t_ms": self.game_t_ms,
            "source_t_ms": self.source_t_ms,
            "clock_map_id": self.clock_map_id,
            "schema_version": self.schema_version,
            "observation_type": self.observation_type,
            "detector_id": self.detector_id,
            "detector_version": self.detector_version,
            "analyzer_id": self.detector_id,
            "analyzer_version": self.detector_version,
            "confidence": self.confidence,
            "claim_kind": self.claim_kind.value,
            "source": self.source.value,
            "camera": self.camera.to_dict(),
            "entities": [item.to_dict() for item in self.entities],
            "hud": None if self.hud is None else self.hud.to_dict(),
            "spatial": None if self.spatial is None else self.spatial.to_dict(),
            "payload": dict(self.payload),
            "artifact_relative_path": self.artifact_relative_path,
            "artifact_sha256": self.artifact_sha256,
        }
        if self.extensions:
            body["extensions"] = dict(self.extensions)
        return body

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> FrameObservation:
        data = mapping_or_error(payload, what="FrameObservation")
        require_schema_version(data.get("schema_version"))
        try:
            claim = VisualClaimKind(str(data.get("claim_kind", VisualClaimKind.OBSERVED.value)))
        except ValueError as exc:
            raise ObservationPayloadError("claim_kind is malformed") from exc
        source_raw = data.get("source")
        if source_raw is not None:
            try:
                declared = Source(str(source_raw))
            except ValueError as exc:
                raise ObservationPayloadError("source is malformed") from exc
            if declared in {Source.RIOT_TIMELINE, Source.RIOT_MATCH, Source.DERIVED, Source.USER}:
                raise ObservationPayloadError("visual observation cannot declare a Riot/GST source")
            if declared is Source.VISUAL_INFERRED:
                claim = VisualClaimKind.INFERRED
            elif declared is Source.VISUAL:
                if claim is VisualClaimKind.INFERRED:
                    raise ObservationPayloadError(
                        "source VISUAL conflicts with INFERRED claim_kind"
                    )
            elif declared is Source.CV:
                raise ObservationPayloadError("R.11 observations must use VISUAL, not CV")
        camera_raw = data.get("camera")
        if not isinstance(camera_raw, Mapping):
            raise ObservationPayloadError("camera is required")
        entities_raw = data.get("entities", [])
        if entities_raw is None:
            entities_raw = []
        if not isinstance(entities_raw, Sequence) or isinstance(entities_raw, (str, bytes)):
            raise ObservationPayloadError("entities must be an array")
        hud_raw = data.get("hud")
        spatial_raw = data.get("spatial")
        extra = {key: data[key] for key in data if key not in _FRAME_KEYS}
        extensions = dict(data.get("extensions") or {})
        extensions.update(extra)
        detector_id = data.get("detector_id", data.get("analyzer_id"))
        detector_version = data.get("detector_version", data.get("analyzer_version"))
        payload_bag = data.get("payload", {})
        if payload_bag is None:
            payload_bag = {}
        if not isinstance(payload_bag, Mapping):
            raise ObservationPayloadError("payload must be an object")
        return cls(
            observation_id=str(data.get("observation_id", "")),
            match_id=str(data.get("match_id", "")),
            gameplay_source_id=str(data.get("gameplay_source_id", "")),
            capture_interval_id=str(data.get("capture_interval_id", "")),
            media_artifact_id=str(data.get("media_artifact_id", "")),
            game_t_ms=require_game_ms("game_t_ms", data.get("game_t_ms")),
            clock_map_id=None
            if data.get("clock_map_id") in (None, "")
            else str(data["clock_map_id"]),
            observation_type=str(data.get("observation_type", "frame")),
            confidence=require_confidence("confidence", data.get("confidence")),
            detector_id=str(detector_id or ""),
            detector_version=str(detector_version or ""),
            camera=CameraProvenance.from_dict(camera_raw),
            schema_version=str(data.get("schema_version", "")),
            claim_kind=claim,
            source_t_ms=optional_game_ms("source_t_ms", data.get("source_t_ms")),
            artifact_relative_path=(
                None
                if data.get("artifact_relative_path") in (None, "")
                else str(data["artifact_relative_path"])
            ),
            artifact_sha256=(
                None if data.get("artifact_sha256") in (None, "") else str(data["artifact_sha256"])
            ),
            entities=tuple(EntityObservation.from_dict(item) for item in entities_raw),
            hud=None
            if hud_raw is None
            else HudObservation.from_dict(mapping_or_error(hud_raw, what="hud")),
            spatial=(
                None
                if spatial_raw is None
                else SpatialObservation.from_dict(mapping_or_error(spatial_raw, what="spatial"))
            ),
            payload=dict(payload_bag),
            extensions=extensions,
        )


def _id_or_ulid(name: str, value: str) -> str:
    text = require_non_empty(name, value)
    if len(text) == 26 and not is_ulid(text):
        raise ObservationPayloadError(f"{name} looks like a ULID but is not Crockford-base32")
    return text
