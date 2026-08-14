"""Validate H.9.1 clock OCR against the labelled clock corpus.

Loads ``tests/fixtures/vision/clock_corpus/manifest.json``, runs classical OCR on
each sample, and prints separated REAL / SYNTHETIC metrics. OCR output is never
used as ground truth.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np

from riftlens.vision.detectors.clock import parse_clock_text
from riftlens.vision.ocr.digits import read_digits

Status = Literal["correct", "wrong", "abstained", "rejected", "confident_wrong"]


@dataclass(frozen=True)
class SampleResult:
    sample_id: str
    source_type: str
    expected: str | None
    predicted: str
    confidence: float
    status: Status
    basis: str
    in_game_label: bool
    readable_label: bool
    notes: str


def corpus_root() -> Path:
    """Return the clock corpus fixture directory."""
    return Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "vision" / "clock_corpus"


def load_manifest(root: Path | None = None) -> list[dict[str, Any]]:
    """Load the corpus manifest as a list of sample dicts."""
    path = (root or corpus_root()) / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("clock corpus manifest must be a JSON list")
    return data


def evaluate_sample(sample: dict[str, Any], *, root: Path) -> SampleResult:
    """Run OCR on one manifest sample and classify the outcome."""
    image = cv2.imread(str(root / sample["file"]))
    if image is None:
        return SampleResult(
            sample_id=str(sample["id"]),
            source_type=str(sample["source_type"]),
            expected=sample.get("expected_raw_clock_text")
            if isinstance(sample.get("expected_raw_clock_text"), str)
            else None,
            predicted="",
            confidence=0.0,
            status="abstained",
            basis="missing_image",
            in_game_label=bool(sample.get("in_game")),
            readable_label=bool(sample.get("readable")),
            notes=str(sample.get("notes") or ""),
        )
    estimate = read_digits(np.asarray(image, dtype=np.uint8))
    expected = sample.get("expected_raw_clock_text")
    readable = bool(sample.get("readable"))
    if readable:
        if estimate.value == expected and estimate.confidence > 0.0:
            status: Status = "correct"
        elif not estimate.value or estimate.confidence <= 0.0:
            status = "abstained"
        else:
            status = "wrong"
    elif (
        estimate.confidence > 0.0
        and estimate.value
        and parse_clock_text(estimate.value) is not None
    ):
        status = "confident_wrong"
    else:
        status = "rejected"
    return SampleResult(
        sample_id=str(sample["id"]),
        source_type=str(sample["source_type"]),
        expected=expected if isinstance(expected, str) else None,
        predicted=str(estimate.value),
        confidence=float(estimate.confidence),
        status=status,
        basis=str(estimate.basis or ""),
        in_game_label=bool(sample.get("in_game")),
        readable_label=readable,
        notes=str(sample.get("notes") or ""),
    )


def evaluate_corpus(root: Path | None = None) -> dict[str, Any]:
    """Evaluate the full corpus and return a JSON-serializable metrics dict."""
    root = root or corpus_root()
    samples = load_manifest(root)
    results = [evaluate_sample(sample, root=root) for sample in samples]
    real = [r for r in results if r.source_type == "REAL"]
    synthetic = [r for r in results if r.source_type == "SYNTHETIC"]
    clean = [r for r in real if r.readable_label]
    non_clock = [r for r in real if not r.readable_label]

    def _bucket(rows: list[SampleResult]) -> dict[str, Any]:
        counts = Counter(r.status for r in rows)
        total = len(rows)
        correct = counts["correct"]
        return {
            "total": total,
            "correct": correct,
            "wrong": counts["wrong"],
            "abstained": counts["abstained"],
            "rejected": counts["rejected"],
            "confident_wrong": counts["confident_wrong"],
            "accuracy": (correct / total) if total else None,
            "coverage": ((correct + counts["wrong"]) / total) if total else None,
            "rejection_rate": (counts["rejected"] / total) if total else None,
        }

    return {
        "corpus_root": str(root),
        "real_clean_in_game": _bucket(clean),
        "real_non_clock": _bucket(non_clock),
        "synthetic_excluded_from_acceptance": _bucket(synthetic),
        "results": [asdict(r) for r in results],
    }


def main() -> None:
    """CLI entry: print summary metrics for the labelled corpus."""
    report = evaluate_corpus()
    clean = report["real_clean_in_game"]
    non_clock = report["real_non_clock"]
    print("REAL clean in-game:", clean)
    print("REAL non-clock:", non_clock)
    print("SYNTHETIC (excluded):", report["synthetic_excluded_from_acceptance"])
    confident_wrong = clean["confident_wrong"] + non_clock["confident_wrong"]
    print("confidently_wrong_total:", confident_wrong)


if __name__ == "__main__":
    main()
