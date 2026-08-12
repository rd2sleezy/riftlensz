from __future__ import annotations

import json
from pathlib import Path

import pytest
from riftlens.domain.enums import Source, Team
from riftlens.domain.ids import new_ulid
from riftlens.domain.observation import (
    FRAME_OBSERVATION_SCHEMA_VERSION,
    CameraControl,
    CameraProvenance,
    ConfidenceBand,
    CorrelationMethod,
    EntityObservation,
    FrameObservation,
    HudObservation,
    HudValue,
    KnowledgeState,
    ObservationPayloadError,
    ObservationSequence,
    SampleGap,
    ScreenRect,
    SpatialObservation,
    UnsupportedObservationSchema,
    VisibilityState,
    VisualWindow,
    camera_from_capture,
    confidence_band,
    dumps,
    loads_frame,
    loads_sequence,
    never_increase_confidence,
)

_DETECTOR = "riftlens.observation.contract"
_DETECTOR_VERSION = "r11.1"


def _ids() -> dict[str, str]:
    return {
        "match_id": "NA1_5617764200",
        "gameplay_source_id": new_ulid(),
        "capture_interval_id": new_ulid(),
        "media_artifact_id": new_ulid(),
        "clock_map_id": new_ulid(),
    }


def _camera(**overrides: object) -> CameraProvenance:
    payload: dict[str, object] = {
        "control": CameraControl.UNKNOWN,
        "confidence": 0.0,
    }
    payload.update(overrides)
    if isinstance(payload["control"], CameraControl):
        return CameraProvenance(
            control=payload["control"],  # type: ignore[arg-type]
            confidence=float(payload["confidence"]),  # type: ignore[arg-type]
            target_participant_id=payload.get("target_participant_id"),  # type: ignore[arg-type]
            target_knowledge=payload.get("target_knowledge", KnowledgeState.UNKNOWN),  # type: ignore[arg-type]
            viewport_width=payload.get("viewport_width"),  # type: ignore[arg-type]
            viewport_height=payload.get("viewport_height"),  # type: ignore[arg-type]
            crop=payload.get("crop"),  # type: ignore[arg-type]
            mode=payload.get("mode"),  # type: ignore[arg-type]
        )
    raise AssertionError("control must be CameraControl")


def _frame(**overrides: object) -> FrameObservation:
    ids = _ids()
    kwargs: dict[str, object] = {
        "observation_id": new_ulid(),
        "match_id": ids["match_id"],
        "gameplay_source_id": ids["gameplay_source_id"],
        "capture_interval_id": ids["capture_interval_id"],
        "media_artifact_id": ids["media_artifact_id"],
        "game_t_ms": 1_110_000,
        "clock_map_id": ids["clock_map_id"],
        "observation_type": "frame",
        "confidence": 0.4,
        "detector_id": _DETECTOR,
        "detector_version": _DETECTOR_VERSION,
        "camera": _camera(),
        "source_t_ms": None,
    }
    kwargs.update(overrides)
    return FrameObservation(**kwargs)  # type: ignore[arg-type]


def test_frame_observation_construction() -> None:
    frame = _frame(game_t_ms=1_110_000, source_t_ms=12_000)
    assert frame.game_t_ms == 1_110_000
    assert frame.source_t_ms == 12_000
    assert frame.schema_version == FRAME_OBSERVATION_SCHEMA_VERSION
    assert frame.source is Source.VISUAL
    assert frame.analyzer_id == _DETECTOR
    assert "time" not in frame.to_dict()
    assert "timestamp" not in frame.to_dict()


def test_game_t_ms_must_be_non_negative_int() -> None:
    with pytest.raises(ObservationPayloadError, match="game_t_ms"):
        _frame(game_t_ms=-1)
    with pytest.raises(ObservationPayloadError, match="game_t_ms"):
        FrameObservation.from_dict({**_frame().to_dict(), "game_t_ms": 1.5})


def test_source_t_ms_is_optional() -> None:
    assert _frame(source_t_ms=None).source_t_ms is None
    assert _frame(source_t_ms=0).source_t_ms == 0
    with pytest.raises(ObservationPayloadError, match="source_t_ms"):
        _frame(source_t_ms=-5)


def test_confidence_bounds_and_band() -> None:
    assert confidence_band(_frame(confidence=0.9).confidence) is ConfidenceBand.HIGH
    assert confidence_band(0.5) is ConfidenceBand.MEDIUM
    assert confidence_band(0.2) is ConfidenceBand.LOW
    assert confidence_band(0.0) is ConfidenceBand.NONE
    with pytest.raises(ObservationPayloadError, match="0..1"):
        _frame(confidence=1.2)
    with pytest.raises(ObservationPayloadError, match="0..1"):
        _frame(confidence=-0.01)
    with pytest.raises(ObservationPayloadError, match="cannot increase"):
        never_increase_confidence(0.4, 0.5)
    assert never_increase_confidence(0.4, 0.2) == 0.2


def test_observation_id_must_be_ulid() -> None:
    with pytest.raises(ObservationPayloadError, match="ULID"):
        _frame(observation_id="not-a-ulid")


def test_camera_uncontrolled_from_r10_flag() -> None:
    camera = camera_from_capture(camera_controlled=False)
    assert camera.control is CameraControl.UNCONTROLLED
    assert camera.confidence == 1.0
    assert camera.target_knowledge is KnowledgeState.UNKNOWN
    assert camera.target_participant_id is None


def test_camera_unknown_and_controlled_unspecified() -> None:
    unknown = camera_from_capture(camera_controlled=None)
    assert unknown.control is CameraControl.UNKNOWN
    locked = camera_from_capture(camera_controlled=True)
    assert locked.control is CameraControl.UNKNOWN
    assert locked.mode == "controlled"
    subject = _camera(
        control=CameraControl.CONTROLLED_SUBJECT,
        confidence=0.8,
        target_participant_id=9,
        target_knowledge=KnowledgeState.KNOWN,
        viewport_width=1920,
        viewport_height=1080,
        crop=ScreenRect(0, 0, 1920, 1080),
    )
    assert subject.control is CameraControl.CONTROLLED_SUBJECT
    other = _camera(control=CameraControl.CONTROLLED_OTHER, confidence=0.7, target_participant_id=3)
    assert other.control is CameraControl.CONTROLLED_OTHER
    with pytest.raises(ObservationPayloadError, match="uncontrolled"):
        CameraProvenance(
            control=CameraControl.UNCONTROLLED,
            confidence=1.0,
            target_participant_id=9,
            target_knowledge=KnowledgeState.KNOWN,
        )


def test_entity_known_participant_and_champion() -> None:
    entity = EntityObservation(
        entity_observation_id=new_ulid(),
        visibility=VisibilityState.VISIBLE,
        confidence=0.7,
        participant_id=9,
        champion_id="Kaisa",
        team=Team.BLUE,
        screen_region=ScreenRect(10, 20, 80, 120),
        occluded=False,
        correlation_method=CorrelationMethod.DETECTOR,
    )
    assert entity.participant_knowledge is KnowledgeState.KNOWN
    assert entity.identity_knowledge is KnowledgeState.KNOWN
    assert entity.participant_id == 9
    assert entity.champion_id == "Kaisa"


def test_entity_unknown_participant_known_champion() -> None:
    entity = EntityObservation(
        entity_observation_id=new_ulid(),
        visibility=VisibilityState.VISIBLE,
        confidence=0.55,
        champion_id="Kaisa",
        correlation_method=CorrelationMethod.NONE,
    )
    assert entity.participant_id is None
    assert entity.participant_knowledge is KnowledgeState.UNKNOWN
    assert entity.champion_id == "Kaisa"
    assert entity.identity_knowledge is KnowledgeState.KNOWN


def test_entity_unknown_champion_visible() -> None:
    entity = EntityObservation(
        entity_observation_id=new_ulid(),
        visibility=VisibilityState.VISIBLE,
        confidence=0.4,
    )
    assert entity.champion_id is None
    assert entity.identity_knowledge is KnowledgeState.UNKNOWN
    assert entity.visibility is VisibilityState.VISIBLE


def test_entity_partial_and_occluded() -> None:
    partial = EntityObservation(
        entity_observation_id=new_ulid(),
        visibility=VisibilityState.PARTIAL,
        confidence=0.5,
        occluded=True,
    )
    assert partial.visibility is VisibilityState.PARTIAL
    assert partial.occluded is True
    occluded = EntityObservation(
        entity_observation_id=new_ulid(),
        visibility=VisibilityState.OCCLUDED,
        confidence=0.3,
        occluded=True,
    )
    assert occluded.visibility is VisibilityState.OCCLUDED


def test_unknown_vs_known_absent_entity() -> None:
    unknown = EntityObservation(
        entity_observation_id=new_ulid(),
        visibility=VisibilityState.UNKNOWN,
        confidence=0.0,
        identity_knowledge=KnowledgeState.UNKNOWN,
    )
    absent = EntityObservation(
        entity_observation_id=new_ulid(),
        visibility=VisibilityState.NOT_VISIBLE,
        confidence=0.8,
        identity_knowledge=KnowledgeState.ABSENT,
        champion_id=None,
    )
    assert unknown.visibility is not VisibilityState.NOT_VISIBLE
    assert absent.identity_knowledge is KnowledgeState.ABSENT
    assert unknown.identity_knowledge is not KnowledgeState.ABSENT


def test_hud_known_missing_unknown_and_confidence() -> None:
    hud = HudObservation(
        hud_visible=KnowledgeState.KNOWN,
        fields={
            "health": HudValue(knowledge=KnowledgeState.KNOWN, value=0.42, confidence=0.6),
            "gold": HudValue(knowledge=KnowledgeState.UNKNOWN),
            "cs": HudValue(knowledge=KnowledgeState.ABSENT),
        },
    )
    assert hud.get("health").value == 0.42
    assert hud.get("health").confidence == 0.6
    assert hud.get("gold").knowledge is KnowledgeState.UNKNOWN
    assert hud.get("gold").value is None
    assert hud.get("cs").knowledge is KnowledgeState.ABSENT
    assert hud.get("level").knowledge is KnowledgeState.UNKNOWN
    unobservable = HudObservation(hud_visible=KnowledgeState.UNOBSERVABLE)
    assert unobservable.get("health").knowledge is KnowledgeState.UNOBSERVABLE
    with pytest.raises(ObservationPayloadError):
        HudValue(knowledge=KnowledgeState.UNKNOWN, value=12)
    with pytest.raises(ObservationPayloadError):
        HudValue(knowledge=KnowledgeState.KNOWN, value=None)


def test_spatial_valid_and_unknown() -> None:
    known = SpatialObservation(
        knowledge=KnowledgeState.KNOWN,
        relative_screen_position=(0.5, 0.4),
        turret_presence=KnowledgeState.KNOWN,
        minimap_visible=KnowledgeState.UNOBSERVABLE,
        labels=("enemy_turret_in_viewport",),
    )
    assert known.relative_screen_position == (0.5, 0.4)
    unknown = SpatialObservation()
    assert unknown.knowledge is KnowledgeState.UNKNOWN
    assert unknown.turret_presence is KnowledgeState.UNKNOWN
    with pytest.raises(ObservationPayloadError, match="coaching"):
        SpatialObservation(labels=("bad positioning",))


def test_sequence_orders_frames_and_validates_window() -> None:
    ids = _ids()
    late = _frame(
        observation_id=new_ulid(),
        game_t_ms=1_130_000,
        **{k: ids[k] for k in ids},
    )
    early = _frame(
        observation_id=new_ulid(),
        game_t_ms=1_110_000,
        **{k: ids[k] for k in ids},
    )
    mid = _frame(
        observation_id=new_ulid(),
        game_t_ms=1_120_000,
        **{k: ids[k] for k in ids},
    )
    sequence = ObservationSequence(
        sequence_id=new_ulid(),
        capture_interval_id=ids["capture_interval_id"],
        media_artifact_id=ids["media_artifact_id"],
        match_id=ids["match_id"],
        gameplay_source_id=ids["gameplay_source_id"],
        start_game_ms=1_110_000,
        end_game_ms=1_135_000,
        frames=(late, early, mid),
        detector_id=_DETECTOR,
        detector_version=_DETECTOR_VERSION,
        clock_map_id=ids["clock_map_id"],
        sampling_interval_ms=10_000,
        expected_sample_count=4,
        gaps=(SampleGap(after_game_t_ms=1_120_000, gap_ms=10_000, reason="unsampled"),),
    )
    assert [frame.game_t_ms for frame in sequence.frames] == [1_110_000, 1_120_000, 1_130_000]
    assert sequence.sample_count == 3
    assert sequence.expected_sample_count == 4
    assert len(sequence.gaps) == 1
    assert VisualWindow is ObservationSequence
    with pytest.raises(ObservationPayloadError, match="outside"):
        ObservationSequence(
            sequence_id=new_ulid(),
            capture_interval_id=ids["capture_interval_id"],
            media_artifact_id=ids["media_artifact_id"],
            match_id=ids["match_id"],
            gameplay_source_id=ids["gameplay_source_id"],
            start_game_ms=1_200_000,
            end_game_ms=1_300_000,
            frames=(early,),
            detector_id=_DETECTOR,
            detector_version=_DETECTOR_VERSION,
        )


def test_sequence_rejects_mismatched_artifact() -> None:
    ids = _ids()
    frame = _frame(**{k: ids[k] for k in ids})
    with pytest.raises(ObservationPayloadError, match="media_artifact_id"):
        ObservationSequence(
            sequence_id=new_ulid(),
            capture_interval_id=ids["capture_interval_id"],
            media_artifact_id=new_ulid(),
            match_id=ids["match_id"],
            gameplay_source_id=ids["gameplay_source_id"],
            start_game_ms=1_110_000,
            end_game_ms=1_135_000,
            frames=(frame,),
            detector_id=_DETECTOR,
            detector_version=_DETECTOR_VERSION,
        )


def test_deterministic_json_round_trip() -> None:
    frame = _frame(
        camera=camera_from_capture(camera_controlled=False),
        entities=(
            EntityObservation(
                entity_observation_id=new_ulid(),
                visibility=VisibilityState.UNKNOWN,
                confidence=0.0,
            ),
        ),
        hud=HudObservation(hud_visible=KnowledgeState.UNKNOWN),
        spatial=SpatialObservation(),
        artifact_relative_path="clip_g1110000.webm",
        artifact_sha256="a" * 64,
    )
    encoded = dumps(frame)
    assert encoded == dumps(loads_frame(encoded))
    assert json.loads(encoded)["schema_version"] == FRAME_OBSERVATION_SCHEMA_VERSION
    assert json.loads(encoded)["analyzer_version"] == _DETECTOR_VERSION
    keys = list(json.loads(encoded).keys())
    assert keys == sorted(keys)


def test_malformed_and_unsupported_schema() -> None:
    with pytest.raises(ObservationPayloadError, match="JSON"):
        loads_frame("{not-json")
    with pytest.raises(UnsupportedObservationSchema, match="r99.0"):
        loads_frame(json.dumps({**_frame().to_dict(), "schema_version": "r99.0"}))
    with pytest.raises(ObservationPayloadError, match="required"):
        FrameObservation.from_dict({"schema_version": FRAME_OBSERVATION_SCHEMA_VERSION})
    with pytest.raises(ObservationPayloadError, match="Riot"):
        FrameObservation.from_dict({**_frame().to_dict(), "source": "RIOT_TIMELINE"})
    with pytest.raises(ObservationPayloadError, match="time/timestamp"):
        _frame(payload={"time": 1})


def test_sequence_round_trip() -> None:
    ids = _ids()
    frames = tuple(
        _frame(game_t_ms=t, observation_id=new_ulid(), **{k: ids[k] for k in ids})
        for t in (1_110_000, 1_120_000, 1_130_000)
    )
    sequence = ObservationSequence(
        sequence_id=new_ulid(),
        capture_interval_id=ids["capture_interval_id"],
        media_artifact_id=ids["media_artifact_id"],
        match_id=ids["match_id"],
        gameplay_source_id=ids["gameplay_source_id"],
        start_game_ms=1_110_000,
        end_game_ms=1_135_000,
        frames=frames,
        detector_id=_DETECTOR,
        detector_version=_DETECTOR_VERSION,
        clock_map_id=ids["clock_map_id"],
        gaps=(SampleGap(after_game_t_ms=1_130_000, gap_ms=5_000, reason="clip_end"),),
    )
    encoded = dumps(sequence)
    restored = loads_sequence(encoded)
    assert dumps(restored) == encoded
    assert restored.frames[0].game_t_ms == 1_110_000


def test_future_extension_field_is_preserved() -> None:
    raw = _frame().to_dict()
    raw["future_hint"] = {"ok": True}
    restored = loads_frame(raw)
    assert restored.extensions["future_hint"] == {"ok": True}


def test_fixture_unknown_champion_file() -> None:
    path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "observation" / "unknown_champion.json"
    )
    loaded = loads_frame(path.read_text(encoding="utf-8"))
    assert loaded.entities[0].champion_id is None
    assert loaded.entities[0].participant_id is None
    assert loaded.entities[0].visibility is VisibilityState.VISIBLE
    assert loaded.entities[0].identity_knowledge is KnowledgeState.UNKNOWN
