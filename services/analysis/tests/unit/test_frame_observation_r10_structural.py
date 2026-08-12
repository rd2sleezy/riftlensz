from __future__ import annotations

import json
from pathlib import Path

from riftlens.domain.enums import Source
from riftlens.domain.ids import new_ulid
from riftlens.domain.observation import (
    CameraControl,
    EntityObservation,
    FrameObservation,
    HudObservation,
    KnowledgeState,
    ObservationSequence,
    SpatialObservation,
    VisibilityState,
    camera_from_capture,
    dumps,
    loads_frame,
    loads_sequence,
)

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "observation"
    / "r10_na1_5617764200_structural.json"
)


def test_real_r10_capture_unknown_observation_linkage() -> None:
    meta = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    camera = camera_from_capture(camera_controlled=bool(meta["camera_controlled"]))
    assert meta["camera_controlled"] is False
    assert camera.control is CameraControl.UNCONTROLLED
    observation = FrameObservation(
        observation_id=new_ulid(),
        match_id=meta["match_id"],
        gameplay_source_id=meta["gameplay_source_id"],
        capture_interval_id=meta["capture_interval_id"],
        media_artifact_id=meta["media_artifact_id"],
        game_t_ms=int(meta["game_t_ms"]),
        source_t_ms=meta["source_t_ms"],
        clock_map_id=meta["clock_map_id"],
        observation_type="frame",
        confidence=0.0,
        detector_id="riftlens.observation.contract",
        detector_version="r11.1",
        camera=camera,
        artifact_relative_path=meta["artifact_relative_path"],
        entities=(),
        hud=HudObservation(hud_visible=KnowledgeState.UNKNOWN),
        spatial=SpatialObservation(
            knowledge=KnowledgeState.UNKNOWN,
            minimap_visible=KnowledgeState.UNKNOWN,
        ),
        payload={},
    )
    assert observation.match_id == "NA1_5617764200"
    assert observation.capture_interval_id == "01KZQPZFMMZDR9DB4Y3NQ2ADSV"
    assert observation.media_artifact_id == "clip_g1110000.webm"
    assert observation.artifact_relative_path == "clip_g1110000.webm"
    assert observation.clock_map_id == "01KZMY2BN0GGHK7T6BCGH8Q6XS"
    assert observation.game_t_ms == 1_110_000
    assert observation.source_t_ms is None
    assert observation.camera.control is CameraControl.UNCONTROLLED
    assert observation.hud is not None
    assert observation.hud.get("health").knowledge is KnowledgeState.UNKNOWN
    assert observation.spatial is not None
    assert observation.spatial.turret_presence is KnowledgeState.UNKNOWN
    assert observation.entities == ()
    assert observation.source is Source.VISUAL
    restored = loads_frame(dumps(observation))
    assert dumps(restored) == dumps(observation)
    sequence = ObservationSequence(
        sequence_id=new_ulid(),
        capture_interval_id=observation.capture_interval_id,
        media_artifact_id=observation.media_artifact_id,
        match_id=observation.match_id,
        gameplay_source_id=observation.gameplay_source_id,
        start_game_ms=1_110_000,
        end_game_ms=1_135_000,
        frames=(observation,),
        detector_id=observation.detector_id,
        detector_version=observation.detector_version,
        clock_map_id=observation.clock_map_id,
        artifact_relative_path=observation.artifact_relative_path,
        expected_sample_count=1,
        sample_count=1,
    )
    assert loads_sequence(dumps(sequence)).capture_interval_id == observation.capture_interval_id
    assert not any(
        isinstance(item, EntityObservation) and item.visibility is VisibilityState.VISIBLE
        for item in observation.entities
    )
