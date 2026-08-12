from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from riftlens.domain.capture import (
    CAPTURE_MANIFEST_NAME,
    CaptureArtifactSpec,
    CaptureManifest,
    CaptureMode,
    CaptureStatus,
    RetentionClass,
)
from riftlens.domain.enums import EvidenceKind, Source
from riftlens.domain.ids import is_ulid
from riftlens.domain.observation import (
    FRAME_OBSERVATION_SCHEMA_VERSION,
    KnowledgeState,
    VisibilityState,
    dumps,
    loads_sequence,
)
from riftlens.visual.analyze import ANALYZER_ID, ANALYZER_VERSION, analyze_capture_dir
from riftlens.visual.detect import detect_champion_like_bars, viewport_is_informative
from riftlens.visual.errors import ArtifactMissing, EmptyClip, MalformedVideo
from riftlens.visual.report import (
    StructuredClaim,
    VisualRuleDiagnostic,
    classify_against_claim,
    format_timeline,
)
from riftlens.visual.sampling import (
    expected_sample_count,
    game_time_for_offset,
    sample_times_ms,
    source_time_for_offset,
)

_MATCH = "NA1_5617764200"
_CAPTURE = "01JZ000000V0CAP00000000001"
_SOURCE = "01JZ000000V0SRC00000000001"
_ARTIFACT = "01JZ000000V0ART00000000001"
_CLOCK = "01JZ000000V0CLK00000000001"


def _ids() -> Iterator[str]:
    n = 0
    while True:
        n += 1
        yield f"01JZ000000V0AB{n:012d}"


def _id_factory() -> object:
    stream = _ids()
    return lambda: next(stream)


def _green_bar_frame(*, count: int = 1, width: int = 320, height: int = 180) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :] = (18, 22, 28)
    image[40:140, 40:280] = (40, 50, 60)
    for index in range(count):
        y = 70 + index * 18
        x = 90
        image[y : y + 5, x : x + 48] = (40, 220, 50)
    return image


def _write_webm(path: Path, frames: list[np.ndarray], *, fps: int = 10) -> None:
    import av

    container = av.open(str(path), mode="w")
    stream = container.add_stream("libvpx", rate=fps)
    stream.width = int(frames[0].shape[1])
    stream.height = int(frames[0].shape[0])
    stream.pix_fmt = "yuv420p"
    try:
        stream.bit_rate = 250_000
    except Exception:
        pass
    for image in frames:
        video_frame = av.VideoFrame.from_ndarray(image, format="rgb24")
        for packet in stream.encode(video_frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()


def _manifest(
    *, start: int = 1_110_000, end: int = 1_112_000, relative: str = "clip.webm"
) -> dict[str, object]:
    spec = CaptureArtifactSpec(
        id=_ARTIFACT,
        kind="clip",
        relative_path=relative,
        game_t_ms=start,
        sha256="a" * 64,
        bytes=100,
        source_t_ms=start + 623,
    )
    manifest = CaptureManifest(
        capture_id=_CAPTURE,
        source_id=_SOURCE,
        match_id=_MATCH,
        clock_map_id=_CLOCK,
        mode=CaptureMode.CLIP,
        codec="webm",
        fps=30.0,
        requested_start_game_ms=start,
        requested_end_game_ms=end,
        start_source_ms=start + 623,
        end_source_ms=end + 623,
        retention=RetentionClass.EPHEMERAL,
        status=CaptureStatus.COMPLETE,
        created_at_ms=1,
        clock_confidence="GOOD",
        clock_verified=True,
        camera_controlled=False,
        artifacts=(spec,),
    )
    return manifest.to_dict()


def _capture_dir(
    tmp_path: Path, frames: list[np.ndarray], *, fps: int = 10, end: int = 1_112_000
) -> Path:
    folder = tmp_path / "cap"
    folder.mkdir()
    _write_webm(folder / "clip.webm", frames, fps=fps)
    (folder / CAPTURE_MANIFEST_NAME).write_text(json.dumps(_manifest(end=end)), encoding="utf-8")
    return folder


def test_game_and_source_timestamp_mapping() -> None:
    assert game_time_for_offset(start_game_ms=1_110_000, offset_ms=500) == 1_110_500
    assert source_time_for_offset(start_source_ms=1_110_623, offset_ms=500) == 1_111_123
    assert source_time_for_offset(start_source_ms=None, offset_ms=500) is None
    with pytest.raises(Exception, match=">="):
        game_time_for_offset(start_game_ms=-1, offset_ms=0)


def test_deterministic_sample_times() -> None:
    times = sample_times_ms(duration_ms=2000, fps=2.0)
    assert times == (0, 500, 1000, 1500, 2000)
    assert expected_sample_count(duration_ms=2000, fps=2.0) == 5
    assert sample_times_ms(duration_ms=2000, fps=2.0) == times


def test_noisy_overcount_is_not_claimed_as_champions(tmp_path: Path) -> None:
    image = np.zeros((360, 640, 3), dtype=np.uint8)
    image[:, :] = (18, 22, 28)
    image[40:300, 40:600] = (40, 50, 60)
    for index in range(12):
        y = 60 + index * 16
        image[y : y + 5, 120:168] = (40, 220, 50)
    folder = _capture_dir(tmp_path, [image] * 8, fps=10, end=1_111_000)
    result = analyze_capture_dir(folder, fps=5.0, id_factory=_id_factory())  # type: ignore[arg-type]
    first = result.sequence.frames[0]
    assert first.payload.get("detector_noisy") is True
    assert first.entities == ()
    assert first.payload.get("count_knowledge") == KnowledgeState.UNKNOWN.value
    assert first.payload.get("raw_bar_count", 0) > 10


def test_detects_known_green_bars_and_empty_unknown() -> None:
    one = detect_champion_like_bars(_green_bar_frame(count=1))
    two = detect_champion_like_bars(_green_bar_frame(count=2))
    empty = detect_champion_like_bars(np.zeros((180, 320, 3), dtype=np.uint8))
    assert len(one) == 1
    assert one[0].ally_like is True
    assert 0.0 <= one[0].confidence <= 1.0
    assert len(two) == 2
    assert empty == ()
    assert viewport_is_informative(_green_bar_frame(count=1)) is True
    assert viewport_is_informative(np.zeros((180, 320, 3), dtype=np.uint8)) is False


def test_missing_artifact(tmp_path: Path) -> None:
    folder = tmp_path / "missing"
    folder.mkdir()
    (folder / CAPTURE_MANIFEST_NAME).write_text(json.dumps(_manifest()), encoding="utf-8")
    with pytest.raises(ArtifactMissing):
        analyze_capture_dir(folder)


def test_empty_clip(tmp_path: Path) -> None:
    folder = tmp_path / "empty"
    folder.mkdir()
    (folder / "clip.webm").write_bytes(b"")
    (folder / CAPTURE_MANIFEST_NAME).write_text(json.dumps(_manifest()), encoding="utf-8")
    with pytest.raises(EmptyClip):
        analyze_capture_dir(folder)


def test_malformed_video(tmp_path: Path) -> None:
    folder = tmp_path / "bad"
    folder.mkdir()
    (folder / "clip.webm").write_bytes(b"not a video")
    (folder / CAPTURE_MANIFEST_NAME).write_text(json.dumps(_manifest()), encoding="utf-8")
    with pytest.raises(MalformedVideo):
        analyze_capture_dir(folder)


def test_analyze_emits_r11_sequence(tmp_path: Path) -> None:
    frames = [_green_bar_frame(count=1) for _ in range(12)]
    frames[6:] = [_green_bar_frame(count=2) for _ in range(6)]
    folder = _capture_dir(tmp_path, frames, fps=10, end=1_111_200)
    result = analyze_capture_dir(folder, fps=5.0, id_factory=_id_factory())  # type: ignore[arg-type]
    sequence = result.sequence
    assert sequence.detector_id == ANALYZER_ID
    assert sequence.detector_version == ANALYZER_VERSION
    assert sequence.schema_version == FRAME_OBSERVATION_SCHEMA_VERSION
    assert sequence.match_id == _MATCH
    assert sequence.capture_interval_id == _CAPTURE
    assert sequence.media_artifact_id == _ARTIFACT
    assert sequence.gameplay_source_id == _SOURCE
    assert sequence.clock_map_id == _CLOCK
    assert sequence.frames
    times = [frame.game_t_ms for frame in sequence.frames]
    assert times == sorted(times)
    first = sequence.frames[0]
    assert first.source is Source.VISUAL
    assert first.claim_kind.value == "OBSERVED"
    assert first.game_t_ms >= 1_110_000
    assert first.source_t_ms is not None
    assert first.camera.control.value == "UNCONTROLLED"
    assert 0.0 <= first.confidence <= 1.0
    assert first.hud is not None
    assert first.hud.get("health").knowledge is KnowledgeState.UNKNOWN
    for entity in first.entities:
        assert entity.champion_id is None
        assert entity.participant_id is None
        assert entity.visibility is VisibilityState.VISIBLE
        assert is_ulid(entity.entity_observation_id)
    encoded = dumps(sequence)
    assert dumps(loads_sequence(encoded)) == encoded
    assert result.subject_visibility is KnowledgeState.UNKNOWN
    timeline = format_timeline(result)
    assert "champion-like=" in timeline
    assert "bad fight" not in timeline
    assert "overextended" not in timeline


def test_unknown_handling_and_provenance(tmp_path: Path) -> None:
    blank = [np.zeros((180, 320, 3), dtype=np.uint8) for _ in range(8)]
    folder = _capture_dir(tmp_path, blank, fps=10, end=1_111_000)
    result = analyze_capture_dir(folder, fps=5.0, id_factory=_id_factory())  # type: ignore[arg-type]
    assert result.peak_entity_count == 0
    assert result.subject_visibility is KnowledgeState.UNKNOWN
    for frame in result.sequence.frames:
        assert frame.source is Source.VISUAL
        assert frame.source is not Source.RIOT_TIMELINE
        assert frame.hud is not None
        assert frame.hud.get("gold").knowledge is KnowledgeState.UNKNOWN


def test_diagnostic_enum_is_research_only() -> None:
    assert VisualRuleDiagnostic.SUPPORTED.value == "SUPPORTED"
    assert VisualRuleDiagnostic.CONTRADICTED.value == "CONTRADICTED"
    assert VisualRuleDiagnostic.INSUFFICIENT_VISUAL_EVIDENCE.value == "INSUFFICIENT_VISUAL_EVIDENCE"
    assert VisualRuleDiagnostic.PARTIALLY_SUPPORTED.value == "PARTIALLY_SUPPORTED"


def test_classify_partial_when_counts_rise(tmp_path: Path) -> None:
    frames = [_green_bar_frame(count=1) for _ in range(6)] + [
        _green_bar_frame(count=2) for _ in range(6)
    ]
    folder = _capture_dir(tmp_path, frames, fps=10, end=1_111_200)
    result = analyze_capture_dir(folder, fps=5.0, id_factory=_id_factory())  # type: ignore[arg-type]
    claim = StructuredClaim(
        rule_id="R-012",
        t_ms=1_110_400,
        summary="Fought into unaccounted-for enemies",
    )
    diagnostic = classify_against_claim(result, claim)
    assert diagnostic in {
        VisualRuleDiagnostic.PARTIALLY_SUPPORTED,
        VisualRuleDiagnostic.INSUFFICIENT_VISUAL_EVIDENCE,
    }
    far = StructuredClaim(rule_id="R-012", t_ms=9_000_000, summary="other fight")
    assert classify_against_claim(result, far) is VisualRuleDiagnostic.INSUFFICIENT_VISUAL_EVIDENCE


def test_v0_does_not_mutate_coaching() -> None:
    from riftlens.analysis.rules.engine import RuleEngine
    from riftlens.analysis.rules.loader import load_rule_pack
    from tests.helpers.gst import bundled_patch, load_gst

    gst = load_gst("NA1_fixture_a")
    pack = load_rule_pack()
    patch = bundled_patch(gst.patch)
    before = [
        (item.rule_id, item.t_ms, item.title, item.severity.value)
        for item in RuleEngine(pack, patch=patch).run(gst, 5)
    ]
    import riftlens.visual as visual_spike

    assert visual_spike.ANALYZER_ID == ANALYZER_ID
    after = [
        (item.rule_id, item.t_ms, item.title, item.severity.value)
        for item in RuleEngine(pack, patch=patch).run(gst, 5)
    ]
    assert before == after
    assert not any(
        item.kind is EvidenceKind.FRAME
        for finding in RuleEngine(pack, patch=patch).run(gst, 5)
        for item in finding.evidence
    )


def test_visual_module_is_not_imported_by_rule_engine() -> None:
    import riftlens.analysis.rules.engine as engine

    assert "riftlens.visual" not in getattr(engine, "__dict__", {})
    source = Path(engine.__file__).read_text(encoding="utf-8")
    assert "riftlens.visual" not in source
    assert "FrameObservation" not in source
