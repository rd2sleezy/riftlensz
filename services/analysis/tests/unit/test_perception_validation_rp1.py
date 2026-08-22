"""RP.1 real-replay validation workflow tests (no real screenshots / ROFL)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from riftlens.domain.capture import (
    CAPTURE_MANIFEST_NAME,
    CaptureArtifactSpec,
    CaptureManifest,
    CaptureMode,
    CaptureStatus,
    RetentionClass,
)
from riftlens.perception.assemble import assemble_rich_state
from riftlens.perception.baseline import VLADIMIR_BASELINE_MANIFEST
from riftlens.perception.capture import frame_from_pixels
from riftlens.perception.debug import (
    annotate_observation_frame,
    assert_debug_path_safe,
    default_debug_root,
    write_debug_bundle,
)
from riftlens.perception.fixtures import frame_with_champion_bar, frame_with_player_hud
from riftlens.perception.validation import (
    DEFAULT_BASELINE_HALF_WINDOW_MS,
    baseline_stamps,
    baseline_timestamp_ms_list,
    find_covering_capture,
    load_complete_captures,
    plan_baseline_windows,
    render_baseline_human_check,
    validate_capture_dir,
)

_ANALYSIS = Path(__file__).resolve().parents[2]
_EXPECTED_TS = (
    427_000,
    840_000,
    1_440_000,
    1_446_000,
    1_468_000,
    1_556_000,
    1_687_000,
    1_884_000,
    2_121_000,
)


def _write_complete_capture(
    root: Path,
    *,
    match_id: str,
    capture_id: str,
    start_ms: int,
    end_ms: int,
) -> Path:
    folder = root / match_id / capture_id
    folder.mkdir(parents=True, exist_ok=True)
    manifest = CaptureManifest(
        capture_id=capture_id,
        source_id="src_test",
        match_id=match_id,
        clock_map_id=None,
        mode=CaptureMode.CLIP,
        codec="webm",
        fps=2.0,
        requested_start_game_ms=start_ms,
        requested_end_game_ms=end_ms,
        start_source_ms=start_ms,
        end_source_ms=end_ms,
        retention=RetentionClass.EPHEMERAL,
        status=CaptureStatus.COMPLETE,
        created_at_ms=1,
        clock_confidence="high",
        clock_verified=True,
        artifacts=(
            CaptureArtifactSpec(
                id="art1",
                kind="clip",
                relative_path="clip.webm",
                game_t_ms=start_ms,
                sha256="abc",
                bytes=12,
            ),
        ),
    )
    (folder / CAPTURE_MANIFEST_NAME).write_text(
        json.dumps(manifest.to_dict()),
        encoding="utf-8",
    )
    (folder / "clip.webm").write_bytes(b"not-a-real-clip")
    return folder


def test_rp1_val_01_baseline_timestamp_manifest() -> None:
    assert VLADIMIR_BASELINE_MANIFEST["match_id"] == "NA1_5620410094"
    assert VLADIMIR_BASELINE_MANIFEST["participant_id"] == 6
    assert VLADIMIR_BASELINE_MANIFEST["champion"] == "Vladimir"
    stamps = baseline_stamps()
    assert len(stamps) == 9
    assert baseline_timestamp_ms_list() == _EXPECTED_TS
    assert DEFAULT_BASELINE_HALF_WINDOW_MS == 2_500


def test_rp1_val_02_capture_dir_validation(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        validate_capture_dir(tmp_path / "missing")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        validate_capture_dir(empty)
    folder = _write_complete_capture(
        tmp_path,
        match_id="NA1_TEST",
        capture_id="cap1",
        start_ms=1000,
        end_ms=5000,
    )
    manifest = validate_capture_dir(folder)
    assert manifest.capture_id == "cap1"
    assert manifest.status is CaptureStatus.COMPLETE


def test_rp1_val_03_coverage_discovery(tmp_path: Path) -> None:
    match_id = "NA1_5620410094"
    _write_complete_capture(
        tmp_path,
        match_id=match_id,
        capture_id="near_14m",
        start_ms=830_000,
        end_ms=850_000,
    )
    captures = load_complete_captures(match_id, captures_root=tmp_path)
    assert len(captures) == 1
    hit = find_covering_capture(
        captures,
        window_start_ms=837_500,
        window_end_ms=842_500,
        require_media_span=False,
    )
    assert hit is not None
    assert hit.capture_id == "near_14m"
    miss = find_covering_capture(
        captures,
        window_start_ms=420_000,
        window_end_ms=434_000,
        require_media_span=False,
    )
    assert miss is None


def test_rp1_val_04_plan_baseline_windows(tmp_path: Path) -> None:
    match_id = "NA1_5620410094"
    _write_complete_capture(
        tmp_path,
        match_id=match_id,
        capture_id="near_14m",
        start_ms=830_000,
        end_ms=850_000,
    )
    plans = plan_baseline_windows(
        match_id=match_id,
        captures_root=tmp_path,
        half_window_ms=2_500,
        require_media_span=False,
    )
    assert len(plans) == 9
    covered = [plan for plan in plans if plan.covered]
    assert len(covered) == 1
    assert covered[0].stamp.t_ms == 840_000
    assert covered[0].window_start_ms == 837_500
    assert covered[0].window_end_ms == 842_500


def test_rp1_val_05_batch_inspect_determinism() -> None:
    pixels = frame_with_champion_bar()
    captured = frame_from_pixels(pixels, requested_game_t_ms=840_000)
    a = assemble_rich_state((captured, captured), requested_game_t_ms=840_000)
    b = assemble_rich_state((captured, captured), requested_game_t_ms=840_000)
    assert a.to_dict() == b.to_dict()
    text_a = render_baseline_human_check(a, clock="14:00", subject="clean_lane")
    text_b = render_baseline_human_check(b, clock="14:00", subject="clean_lane")
    assert text_a == text_b
    assert "timing error" in text_a
    assert "champion candidates" in text_a
    assert "minion candidates" in text_a
    assert "minimap" in text_a
    assert "Vladimir" not in text_a
    assert "puuid" not in text_a.lower()


def test_rp1_val_06_timing_metadata_retained() -> None:
    captured = frame_from_pixels(
        frame_with_player_hud(),
        requested_game_t_ms=1_468_000,
        actual_game_t_ms=1_468_250,
    )
    state = assemble_rich_state((captured,), requested_game_t_ms=1_468_000)
    report = render_baseline_human_check(state, clock="24:28")
    assert "requested t: 1468000" in report
    assert "actual t:    1468250" in report
    assert "timing error: 250 ms" in report
    assert state.frames[0].frame.timing_error_ms == 250


def test_rp1_val_07_debug_outputs_local_only(tmp_path: Path) -> None:
    root = default_debug_root()
    assert str(root).endswith("rp/perception") or root.as_posix().endswith("rp/perception")
    with pytest.raises(ValueError):
        assert_debug_path_safe(_ANALYSIS / "out", repo_root=_ANALYSIS)
    captured = frame_from_pixels(frame_with_champion_bar(), requested_game_t_ms=427_000)
    state = assemble_rich_state((captured,), requested_game_t_ms=427_000)
    dest = write_debug_bundle(
        state,
        (captured,),
        out_dir=tmp_path / "rp_debug",
        repo_root=_ANALYSIS,
        label="baseline_707",
    )
    assert dest.is_dir()
    assert (dest / "rich_replay_state.json").is_file()
    assert list(dest.glob("frame_*.png"))
    annotated = annotate_observation_frame(
        captured.pixels.copy(),
        state.frames[0],
        tracks=state.tracks,
    )
    assert annotated.shape == captured.pixels.shape


def test_rp1_val_08_privacy_no_identity_in_debug_json(tmp_path: Path) -> None:
    captured = frame_from_pixels(frame_with_champion_bar(), requested_game_t_ms=427_000)
    state = assemble_rich_state((captured,), requested_game_t_ms=427_000)
    dest = write_debug_bundle(
        state,
        (captured,),
        out_dir=tmp_path / "safe",
        repo_root=_ANALYSIS,
        label="t427000",
    )
    payload = (dest / "rich_replay_state.json").read_text(encoding="utf-8").lower()
    assert "puuid" not in payload
    assert "summoner_name" not in payload
    assert "vladimir" not in payload
    for path in dest.rglob("*"):
        name = path.name.lower()
        assert "puuid" not in name
        assert "summoner_name" not in name
        assert "vladimir" not in name
