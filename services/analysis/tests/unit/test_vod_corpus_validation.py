"""Deterministic tests for REAL VIDEO corpus inventory, labels, and H.10 eval tooling."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from riftlens.domain.clock_reading import ClockReading
from riftlens.pipeline.ingest_video.reader import decode_at
from riftlens.validation.vod_corpus.bench import blocked_30min, is_suitable_30min
from riftlens.validation.vod_corpus.checkpoints import (
    Checkpoint,
    checkpoint_set_from_mapping,
    error_stats,
    errors_against_map,
    extract_checkpoint_stub,
    load_checkpoints,
)
from riftlens.validation.vod_corpus.h10_eval import classify_failure, evaluate_readings_only
from riftlens.validation.vod_corpus.inventory import guess_kind
from riftlens.validation.vod_corpus.kinds import CoverageKind, FailureClass, MediaKind
from riftlens.validation.vod_corpus.manifest import (
    VodEntry,
    default_corpus_root,
    load_corpus,
    validate_committed_portable,
)
from riftlens.validation.vod_corpus.ocr_eval import atlas_role_for_sample, clock_corpus_diversity
from riftlens.validation.vod_corpus.resolve import is_portable_ref, resolve_media_ref
from riftlens.validation.vod_corpus.verdicts import compute_verdicts, h9_1_verdict, h10_verdict


def _entry(**kwargs: object) -> VodEntry:
    payload: dict[str, object] = {
        "id": "real_01",
        "kind": MediaKind.REAL,
        "media_ref": "vod://game.mp4",
        "match_id": "NA1_TEST",
        "coverage": CoverageKind.FULL_GAME,
        "duration_ms": 30 * 60 * 1000,
    }
    payload.update(kwargs)
    return VodEntry(**payload)  # type: ignore[arg-type]


def _reading(t_video_ms: int, t_game_ms: int | None, confidence: float = 0.95) -> ClockReading:
    return ClockReading(
        t_video_ms=t_video_ms,
        t_game_ms=t_game_ms,
        confidence=confidence,
        in_game=t_game_ms is not None,
    )


def _write_color_video(path: Path, *, frames: int = 8, width: int = 64, height: int = 64) -> None:
    import av

    container = av.open(str(path), mode="w")
    stream = container.add_stream("mpeg4", rate=8)
    stream.width = width
    stream.height = height
    stream.pix_fmt = "yuv420p"
    for index in range(frames):
        frame = av.VideoFrame.from_ndarray(
            np.full((height, width, 3), index * 20, dtype=np.uint8), format="bgr24"
        )
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()


def test_committed_manifest_is_portable() -> None:
    corpus = load_corpus(overlay=False)
    assert corpus.entries
    errors = validate_committed_portable(corpus)
    assert errors == []
    assert all(is_portable_ref(item.media_ref) for item in corpus.entries)
    assert all(not item.counts_toward_h10_acceptance for item in corpus.entries)
    assert corpus.real_entries() == ()


def test_kinds_do_not_count_r10_or_synthetic() -> None:
    r10 = _entry(id="clip", kind=MediaKind.R10_CLIP, media_ref="r10://m/c/a.webm")
    synth = _entry(id="syn", kind=MediaKind.SYNTHETIC, media_ref="vod://s.mp4")
    replay = _entry(id="rep", kind=MediaKind.REPLAY_GENERATED, media_ref="vod://r.mp4")
    real = _entry()
    assert r10.counts_toward_h10_acceptance is False
    assert synth.counts_toward_h10_acceptance is False
    assert replay.counts_toward_h10_acceptance is False
    assert real.counts_toward_h10_acceptance is True


def test_absolute_ref_rejected_in_committed_resolve() -> None:
    with pytest.raises(ValueError, match="absolute"):
        resolve_media_ref("/tmp/secret.mp4")
    path = resolve_media_ref("/tmp/secret.mp4", allow_absolute=True)
    assert path == Path("/tmp/secret.mp4")


def test_r10_ref_resolves_under_captures(tmp_path: Path) -> None:
    path = resolve_media_ref("r10://NA1_1/cap/clip.webm", r10_root=tmp_path)
    assert path == tmp_path / "NA1_1" / "cap" / "clip.webm"


def test_guess_kind_classifies_r10_and_unrelated() -> None:
    kind, league, notes = guess_kind(Path.home() / ".riftlens/captures/NA1_1/c/clip.webm")
    assert kind is MediaKind.R10_CLIP
    assert league is True
    assert "r10" in notes
    kind2, league2, _ = guess_kind(Path("/Users/x/Downloads/854238-hd_1280_720_30fps.mp4"))
    assert kind2 is None
    assert league2 is False


def test_checkpoint_rejects_h10_as_label() -> None:
    with pytest.raises(ValueError, match="H.10"):
        checkpoint_set_from_mapping(
            {
                "corpus_id": "x",
                "label_basis": "h10_syncmap",
                "checkpoints": [{"video_t_ms": 0, "visible_clock": "1:00"}],
            }
        )


def test_checkpoint_parses_clock_and_errors() -> None:
    labels = load_checkpoints(
        default_corpus_root() / "checkpoints" / "r10_na1_5620410094_mid_17s.yaml"
    )
    assert labels.checkpoints[0].game_t_ms == 830_000
    by_video = {item.video_t_ms: item.game_t_ms for item in labels.checkpoints}
    rows = errors_against_map(labels.checkpoints, video_to_game=by_video.get)
    stats = error_stats(rows)
    assert stats["n_uncovered"] == 0
    assert stats["p95_ms"] == 0.0


def test_wrong_sync_classified_when_checkpoint_p95_high() -> None:
    failure = classify_failure(
        sync_ok=True,
        sync_error_code=None,
        checkpoint_p95_ms=1200.0,
        checkpoint_n_covered=4,
        checkpoint_n=4,
    )
    assert failure is FailureClass.WRONG_SYNC
    abstain = classify_failure(
        sync_ok=False,
        sync_error_code="INSUFFICIENT_READINGS",
        checkpoint_p95_ms=None,
        checkpoint_n_covered=0,
        checkpoint_n=4,
    )
    assert abstain is FailureClass.OCR_INSUFFICIENT


def test_h10_eval_on_synthetic_readings_matches_independent_checkpoints() -> None:
    entry = _entry(id="syn_linear", kind=MediaKind.SYNTHETIC, duration_ms=20_000)
    readings = [_reading(t, t + 60_000) for t in range(0, 15_000, 1_000)]
    checkpoints = [
        Checkpoint(video_t_ms=0, visible_clock="1:00", game_t_ms=60_000),
        Checkpoint(video_t_ms=10_000, visible_clock="1:10", game_t_ms=70_000),
    ]
    result = evaluate_readings_only(entry, readings, checkpoints, video_duration_ms=20_000)
    assert result.sync_ok is True
    assert result.counts_toward_acceptance is False
    assert result.checkpoint_p95_ms is not None
    assert result.checkpoint_p95_ms <= 500
    assert result.failure_class is None


def test_verdicts_blocked_without_real_vods() -> None:
    h9, _ = h9_1_verdict(
        n_real_clean=41,
        n_held_out_clean=0,
        n_matches=1,
        n_resolutions=1,
        has_early=False,
        has_late=False,
        confident_wrong=0,
        held_out_accuracy=None,
    )
    assert h9 == "PARTIAL"
    h10, engineering, _ = h10_verdict([])
    assert h10 == "BLOCKED_INSUFFICIENT_CORPUS"
    assert engineering is False
    verdicts = compute_verdicts(
        entries=load_corpus(overlay=False).entries,
        h10_results=[],
        n_real_clean=41,
        n_held_out_clean=0,
        n_matches=1,
        n_resolutions=1,
        has_early=False,
        has_late=False,
        confident_wrong=0,
        held_out_accuracy=None,
        has_30min=False,
        bench_passed=None,
    )
    assert verdicts.h9_1_real_corpus == "PARTIAL"
    assert verdicts.h10_real_vod_acceptance == "BLOCKED_INSUFFICIENT_CORPUS"
    assert verdicts.h12_video_readiness == "BLOCKED"
    assert verdicts.h12_1_runnable is False
    assert verdicts.h12_5_runnable is False
    assert verdicts.h12_6_runnable is False


def test_h10_pass_requires_ten_real_successes() -> None:
    rows = []
    for index in range(10):
        entry = _entry(id=f"real_{index}")
        readings = [_reading(t, t + 8_000) for t in range(0, 40_000, 1_000)]
        checkpoints = [
            Checkpoint(video_t_ms=0, visible_clock="0:08", game_t_ms=8_000),
            Checkpoint(video_t_ms=20_000, visible_clock="0:28", game_t_ms=28_000),
        ]
        rows.append(evaluate_readings_only(entry, readings, checkpoints, video_duration_ms=45_000))
    status, engineering, _ = h10_verdict(rows)
    assert status == "PASS"
    assert engineering is True


def test_atlas_role_same_match_is_not_held_out() -> None:
    role = atlas_role_for_sample({"source_type": "REAL", "source_match_id": "NA1_5620410094"})
    assert role == "atlas_match"
    held = atlas_role_for_sample({"source_type": "REAL", "source_match_id": "NA1_OTHER"})
    assert held == "held_out"
    diversity = clock_corpus_diversity()
    assert diversity["n_matches"] == 1
    assert diversity["has_early"] is False
    assert diversity["has_late"] is False


def test_30min_gate_rejects_r10_and_short_real() -> None:
    clip = _entry(id="c", kind=MediaKind.R10_CLIP, duration_ms=17_000)
    assert is_suitable_30min(clip, duration_ms=17_000) is False
    short = _entry(duration_ms=17_000)
    assert is_suitable_30min(short, duration_ms=17_000) is False
    long = _entry(duration_ms=30 * 60 * 1000)
    assert is_suitable_30min(long, duration_ms=30 * 60 * 1000) is True
    blocked = blocked_30min("no REAL ~30-minute VOD")
    assert blocked.runnable is False
    assert blocked.under_90s is None


def test_decode_at_and_checkpoint_stub(tmp_path: Path) -> None:
    video = tmp_path / "tiny.mp4"
    _write_color_video(video)
    frame = decode_at(video, 0)
    assert frame is not None
    assert frame.t_video_ms >= 0
    stub = extract_checkpoint_stub(video, [0, 250], tmp_path / "stubs", corpus_id="tiny")
    assert stub.is_file()
    text = stub.read_text(encoding="utf-8")
    assert "visible_clock" in text
    assert "h10" not in text.lower() or "must not" in text.lower()
