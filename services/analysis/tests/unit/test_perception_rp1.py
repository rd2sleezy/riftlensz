"""RP.1 rich replay perception tests — synthetic fixtures only, no Riot network."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from riftlens.coaching.evaluation import EVALUATION_SCHEMA_VERSION
from riftlens.coaching.parity import PARITY_SCHEMA_VERSION, all_capabilities
from riftlens.domain.enums import Source
from riftlens.perception.assemble import assemble_rich_state, observe_frame
from riftlens.perception.capture import frame_from_pixels
from riftlens.perception.debug import assert_debug_path_safe, default_debug_root
from riftlens.perception.detect import detect_champion_candidates, detect_minion_candidates
from riftlens.perception.fixtures import (
    blank_frame,
    frame_with_champion_bar,
    frame_with_minimap_pip,
    frame_with_minion_bars,
    frame_with_player_hud,
)
from riftlens.perception.geometry import LayoutSupport, ScreenGeometry
from riftlens.perception.hud import extract_player_hud
from riftlens.perception.minimap import extract_minimap
from riftlens.perception.models import (
    PERCEPTION_SCHEMA_VERSION,
    CandidateKind,
    ObservationStatus,
)
from riftlens.perception.track import track_candidates_across_frames

_ANALYSIS = Path(__file__).resolve().parents[2]
_RIFTLENS = _ANALYSIS / "riftlens"
_PRODUCTION_ROOTS = (
    _RIFTLENS / "api",
    _RIFTLENS / "pipeline",
    _RIFTLENS / "analysis",
    _RIFTLENS / "orchestration",
    _RIFTLENS / "coaching",
    _RIFTLENS / "visual",
)


def test_rp1_01_pixel_normalized_roundtrip() -> None:
    geo = ScreenGeometry.from_frame(1920, 1080)
    point = geo.normalize_point(960, 540)
    assert point.x == pytest.approx(0.5)
    assert point.y == pytest.approx(0.5)
    x, y = geo.denormalize_point(point)
    assert (x, y) == (960, 540)
    assert geo.normalize_point(960, 540) == geo.normalize_point(960, 540)


def test_rp1_02_roi_scaling() -> None:
    small = ScreenGeometry.from_frame(640, 360)
    large = ScreenGeometry.from_frame(1920, 1080)
    a = small.roi("minimap")
    b = large.roi("minimap")
    assert a is not None and b is not None
    assert small.normalize_rect(a).x == pytest.approx(large.normalize_rect(b).x, abs=1e-3)
    assert small.normalize_rect(a).width == pytest.approx(
        large.normalize_rect(b).width, abs=1e-3
    )


def test_rp1_03_unsupported_layout() -> None:
    geo = ScreenGeometry.from_frame(64, 48)
    assert geo.layout_support is LayoutSupport.UNSUPPORTED
    assert geo.roi("minimap") is None
    assert geo.all_rois() == {}
    captured = frame_from_pixels(blank_frame(64, 48), requested_game_t_ms=1000)
    obs = observe_frame(captured)
    assert any(gap.startswith("unsupported_layout") for gap in obs.gaps)
    assert obs.player_hud.hp_fraction.status in {
        ObservationStatus.UNKNOWN,
        ObservationStatus.UNAVAILABLE,
    }


def test_rp1_04_minion_candidate_detected() -> None:
    pixels = frame_with_minion_bars(count=3)
    geo = ScreenGeometry.from_frame(640, 360)
    found = detect_minion_candidates(pixels, geo)
    assert found
    assert all(item.kind is CandidateKind.MINION_CANDIDATE for item in found)
    assert all(item.participant_id is None for item in found)


def test_rp1_05_ambiguous_not_overclassified() -> None:
    # Tiny noise speck should not become a minion.
    image = blank_frame()
    image[100:102, 100:104] = (40, 220, 50)
    geo = ScreenGeometry.from_frame(640, 360)
    found = detect_minion_candidates(image, geo)
    assert found == ()


def test_rp1_06_champion_without_identity() -> None:
    pixels = frame_with_champion_bar()
    geo = ScreenGeometry.from_frame(640, 360)
    found = detect_champion_candidates(pixels, geo)
    assert found
    for item in found:
        assert item.participant_id is None
        assert item.champion_id is None
        assert item.kind is CandidateKind.CHAMPION_CANDIDATE


def test_rp1_07_hp_fraction_deterministic() -> None:
    pixels = frame_with_player_hud(hp_fill=0.8, resource_fill=None)
    geo = ScreenGeometry.from_frame(640, 360)
    hud = extract_player_hud(pixels, geo)
    assert hud.hp_fraction.status is ObservationStatus.OBSERVED
    assert isinstance(hud.hp_fraction.value, float)
    again = extract_player_hud(pixels, geo)
    assert again.hp_fraction.value == hud.hp_fraction.value


def test_rp1_08_resource_unknown_not_zero() -> None:
    pixels = frame_with_player_hud(hp_fill=0.7, resource_fill=None)
    geo = ScreenGeometry.from_frame(640, 360)
    hud = extract_player_hud(pixels, geo)
    assert hud.resource_fraction.status is ObservationStatus.UNKNOWN
    assert hud.resource_fraction.value is None
    assert hud.resource_fraction.value != 0


def test_rp1_09_minimap_roi() -> None:
    pixels = frame_with_minimap_pip()
    geo = ScreenGeometry.from_frame(640, 360)
    mm = extract_minimap(pixels, geo)
    assert mm.extracted is True
    assert mm.roi.width > 0
    assert "fog" not in mm.notes.lower() or "No" in mm.notes
    assert "identity" in mm.notes.lower()


def test_rp1_10_temporal_track_stable() -> None:
    geo = ScreenGeometry.from_frame(640, 360)
    frames = []
    for offset in (0, 100, 200):
        pixels = frame_with_champion_bar(x=200 + offset // 50, y=120)
        cand = detect_champion_candidates(pixels, geo)
        frames.append((1_000_000 + offset, cand))
    tracks = track_candidates_across_frames(frames)
    assert tracks
    assert any(item.observation_count >= 2 for item in tracks)
    assert all(item.participant_id is None for item in tracks)


def test_rp1_11_ambiguous_association_no_forced_identity() -> None:
    geo = ScreenGeometry.from_frame(640, 360)
    # Two nearby bars then swap-like positions → may AMBIGUOUS, never participant id.
    a = detect_champion_candidates(frame_with_champion_bar(x=180, y=120), geo)
    b = detect_champion_candidates(frame_with_champion_bar(x=200, y=120), geo)
    c = detect_champion_candidates(frame_with_champion_bar(x=160, y=120), geo)
    tracks = track_candidates_across_frames(((100, a), (200, b + c)))
    assert all(item.participant_id is None for item in tracks)


def test_rp1_12_rich_state_deterministic() -> None:
    pixels = frame_with_champion_bar()
    captured = frame_from_pixels(pixels, requested_game_t_ms=1_446_000)
    state_a = assemble_rich_state((captured,), requested_game_t_ms=1_446_000)
    state_b = assemble_rich_state((captured,), requested_game_t_ms=1_446_000)
    assert state_a.to_dict() == state_b.to_dict()
    assert state_a.schema_version == PERCEPTION_SCHEMA_VERSION


def test_rp1_13_provenance_and_confidence() -> None:
    captured = frame_from_pixels(
        frame_with_champion_bar(),
        requested_game_t_ms=1000,
        actual_game_t_ms=1050,
    )
    obs = observe_frame(captured)
    assert captured.meta.timing_error_ms == 50
    for cand in obs.champion_candidates:
        assert cand.source is Source.VISUAL
        assert 0.0 <= cand.confidence <= 1.0
        assert cand.health_fraction.source is Source.VISUAL


def test_rp1_14_not_gst_fact() -> None:
    captured = frame_from_pixels(frame_with_minion_bars(), requested_game_t_ms=500)
    state = assemble_rich_state((captured,), requested_game_t_ms=500)
    payload = state.to_dict()
    assert payload["gst_fact"] is False
    for frame in payload["frames"]:
        assert frame["gst_fact"] is False


def test_rp1_15_privacy_safe_debug_paths() -> None:
    root = default_debug_root()
    assert ".riftlens" in str(root)
    safe = assert_debug_path_safe(Path("/tmp/riftlens_rp1_test"))
    assert safe.is_absolute()
    with pytest.raises(ValueError):
        assert_debug_path_safe(_ANALYSIS / "artifacts" / "debug", repo_root=_ANALYSIS)
    with pytest.raises(ValueError):
        assert_debug_path_safe(Path("/tmp/leak_puuid_dump"), repo_root=None)


def test_rp1_16_no_real_replay_in_fixtures() -> None:
    fixture_root = _ANALYSIS / "tests" / "fixtures"
    if fixture_root.is_dir():
        for path in fixture_root.rglob("*"):
            if path.suffix.lower() in {".rofl", ".webm", ".mp4"}:
                # vod_corpus media is gitignored; anything tracked would fail this.
                rel = str(path.relative_to(_ANALYSIS))
                assert "vod_corpus/media" in rel or path.name.startswith(".")


def test_rp1_17_rp0_registry_valid() -> None:
    assert PARITY_SCHEMA_VERSION == "rp.0"
    caps = all_capabilities()
    assert any(item.capability_id == "RP-CAP-WAVE-STATE" for item in caps)
    wave = next(item for item in caps if item.capability_id == "RP-CAP-WAVE-STATE")
    # RP.1 must not falsely mark wave-state READY.
    assert wave.riftlens_status.value == "BLOCKED"


def test_rp1_18_c7_unchanged() -> None:
    assert EVALUATION_SCHEMA_VERSION == "c7.0"


def test_rp1_19_visual_package_untouched_by_perception_import() -> None:
    # visual must not import perception (direction is perception → visual).
    for path in (_RIFTLENS / "visual").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "riftlens.perception" not in text


def test_rp1_20_no_production_dependency() -> None:
    hits: list[str] = []
    for root in _PRODUCTION_ROOTS:
        if not root.exists():
            continue
        paths = [root] if root.is_file() else list(root.rglob("*.py"))
        for path in paths:
            if "perception" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            if "riftlens.perception" in source:
                hits.append(str(path.relative_to(_ANALYSIS)))
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if "perception" in node.module and node.module.startswith(
                        "riftlens.perception"
                    ):
                        hits.append(str(path.relative_to(_ANALYSIS)))
    assert hits == []


def test_observe_combined_frame_json_stable() -> None:
    pixels = frame_with_player_hud()
    # Overlay a champion bar in gameplay.
    pixels[120:126, 200:264] = (40, 220, 50)
    captured = frame_from_pixels(pixels, requested_game_t_ms=427_000)
    state = assemble_rich_state((captured, captured), requested_game_t_ms=427_000)
    text = json.dumps(state.to_dict(), sort_keys=True)
    assert "Vladimir" not in text
    assert "puuid" not in text.lower()
