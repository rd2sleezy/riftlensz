"""Regression tests for the labelled real League clock OCR corpus (H.9.1)."""

from __future__ import annotations

from pathlib import Path

import cv2
import pytest
from riftlens.vision.detectors.clock import parse_clock_text
from riftlens.vision.ocr.atlas import choose_atlas, default_glyphs_root, load_atlas
from riftlens.vision.ocr.digits import GLYPH_MATCH_FLOOR, read_digits
from riftlens.vision.ocr.validate_corpus import corpus_root, evaluate_corpus, load_manifest

CORPUS = corpus_root()


@pytest.fixture(scope="module")
def manifest() -> list[dict[str, object]]:
    return load_manifest(CORPUS)


def test_corpus_manifest_exists_and_labels_real(manifest: list[dict[str, object]]) -> None:
    assert (CORPUS / "manifest.json").is_file()
    assert manifest
    real = [s for s in manifest if s["source_type"] == "REAL"]
    synthetic = [s for s in manifest if s["source_type"] == "SYNTHETIC"]
    assert real
    assert synthetic
    assert all(Path(CORPUS / str(s["file"])).is_file() for s in manifest)


def test_league_atlas_preferred_and_documented() -> None:
    atlas = choose_atlas(20)
    assert atlas.available()
    assert "LEAGUE" in atlas.source.upper()
    league = load_atlas(24, root=default_glyphs_root() / "league")
    assert league.available()
    source = (default_glyphs_root() / "league" / "24px" / "SOURCE.txt").read_text(
        encoding="utf-8"
    )
    assert "LEAGUE_CROP" in source
    assert "not H.9.1 OCR" in source or "not OCR-as-GT" in source


def test_synthetic_atlas_still_available() -> None:
    synthetic = load_atlas(24, root=default_glyphs_root())
    assert synthetic.available()
    assert "SYNTHETIC" in synthetic.source.upper()


def test_real_clean_samples_mostly_correct() -> None:
    """Honest gate: high accuracy on labelled real crops; zero confident wrongs."""
    report = evaluate_corpus(CORPUS)
    clean = report["real_clean_in_game"]
    non_clock = report["real_non_clock"]
    assert clean["total"] >= 20
    assert clean["confident_wrong"] == 0
    assert non_clock["confident_wrong"] == 0
    assert clean["wrong"] == 0
    # Aspirational product gate is ≥99%; this small mid-game corpus targets ≥90%.
    assert clean["accuracy"] is not None and float(clean["accuracy"]) >= 0.90
    assert non_clock["total"] >= 3
    assert non_clock["rejection_rate"] is not None
    assert float(non_clock["rejection_rate"]) >= 0.95


def test_known_real_timestamps_roundtrip() -> None:
    cases = {
        "clean_002_1350.png": "13:50",
        "clean_030_1404.png": "14:04",
        "clean_036_1732.png": "17:32",
    }
    for filename, expected in cases.items():
        path = CORPUS / "real" / filename
        assert path.is_file(), filename
        estimate = read_digits(cv2.imread(str(path)))
        assert estimate.value == expected, (filename, estimate)
        assert estimate.confidence > 0.0


def test_real_negative_kill_score_not_confident_clock() -> None:
    path = CORPUS / "real_negative" / "kill_score.png"
    estimate = read_digits(cv2.imread(str(path)))
    if estimate.confidence >= GLYPH_MATCH_FLOOR and estimate.value:
        assert parse_clock_text(estimate.value) is None


def test_validate_corpus_json_shape() -> None:
    report = evaluate_corpus(CORPUS)
    assert "results" in report
    assert report["synthetic_excluded_from_acceptance"]["total"] >= 1
