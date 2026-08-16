"""H.9.1 REAL clock OCR evaluation with atlas train/eval separation."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Literal, cast

from riftlens.validation.vod_corpus.kinds import ATLAS_TRAIN_MATCH_IDS
from riftlens.vision.ocr.validate_corpus import corpus_root, evaluate_corpus, load_manifest

AtlasRole = Literal["atlas_match", "held_out", "synthetic"]


def atlas_role_for_sample(
    sample: dict[str, Any],
    *,
    atlas_train_match_ids: frozenset[str] | None = None,
) -> AtlasRole:
    """Return whether this crop may be reported as held-out accuracy."""
    if str(sample.get("source_type")) == "SYNTHETIC":
        return "synthetic"
    explicit = sample.get("atlas_role")
    if explicit in {"atlas_match", "held_out", "synthetic"}:
        return cast(AtlasRole, str(explicit))
    train = atlas_train_match_ids or ATLAS_TRAIN_MATCH_IDS
    match_id = str(sample.get("source_match_id") or "")
    if match_id in train:
        return "atlas_match"
    return "held_out"


def clock_corpus_diversity(root: Path | None = None) -> dict[str, Any]:
    """Describe REAL crop coverage. Does not run OCR."""
    samples = [item for item in load_manifest(root) if str(item.get("source_type")) == "REAL"]
    clean = [item for item in samples if item.get("readable")]
    matches = {str(item.get("source_match_id") or "") for item in clean}
    matches.discard("")
    resolutions: set[str] = set()
    for item in clean:
        for label in item.get("resolutions_validated") or []:
            resolutions.add(str(label))
        w, h = item.get("frame_width"), item.get("frame_height")
        if isinstance(w, int) and isinstance(h, int):
            resolutions.add(f"{w}x{h}")
    times = [
        int(item["expected_t_game_ms"])
        for item in clean
        if item.get("expected_t_game_ms") is not None
    ]
    has_early = any(t < 10 * 60 * 1000 for t in times)
    has_mid = any(10 * 60 * 1000 <= t < 25 * 60 * 1000 for t in times)
    has_late = any(t >= 25 * 60 * 1000 for t in times)
    return {
        "n_real": len(samples),
        "n_real_clean": len(clean),
        "n_matches": len(matches),
        "match_ids": sorted(matches),
        "n_resolutions": len(resolutions),
        "resolutions": sorted(resolutions),
        "has_early": has_early,
        "has_mid": has_mid,
        "has_late": has_late,
    }


def evaluate_clock_corpus(
    root: Path | None = None,
    *,
    atlas_train_match_ids: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Wrap ``evaluate_corpus`` and split REAL metrics by atlas role.

    Same-match/template crops are never reported as held-out accuracy.
    SYNTHETIC samples stay excluded from REAL acceptance.
    """
    root = root or corpus_root()
    base = evaluate_corpus(root)
    samples = load_manifest(root)
    by_id = {str(item["id"]): item for item in samples}
    train_ids = atlas_train_match_ids or ATLAS_TRAIN_MATCH_IDS
    roles: dict[str, AtlasRole] = {}
    for row in base["results"]:
        sample = by_id.get(str(row["sample_id"]), {})
        roles[str(row["sample_id"])] = atlas_role_for_sample(
            sample, atlas_train_match_ids=train_ids
        )

    def _select(role: AtlasRole, *, readable: bool | None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in base["results"]:
            if roles.get(str(row["sample_id"])) != role:
                continue
            if readable is None:
                out.append(row)
            elif bool(row["readable_label"]) is readable:
                out.append(row)
        return out

    held_clean = _select("held_out", readable=True)
    held_neg = _select("held_out", readable=False)
    atlas_clean = _select("atlas_match", readable=True)
    atlas_neg = _select("atlas_match", readable=False)
    return {
        **base,
        "atlas_train_match_ids": sorted(train_ids),
        "atlas_match_clean": _bucket(atlas_clean),
        "atlas_match_negative": _bucket(atlas_neg),
        "held_out_clean": _bucket(held_clean),
        "held_out_negative": _bucket(held_neg),
        "held_out_available": bool(held_clean or held_neg),
        "note": (
            "held_out_* is the only REAL accuracy that may be compared to the "
            "product gate. atlas_match_* reuses the glyph-template match and is "
            "not held-out."
        ),
    }


def _bucket(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(row["status"]) for row in rows)
    total = len(rows)
    correct = counts["correct"]
    wrong = counts["wrong"]
    return {
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "abstained": counts["abstained"],
        "rejected": counts["rejected"],
        "confident_wrong": counts["confident_wrong"],
        "accuracy": (correct / total) if total else None,
        "non_abstain_coverage": ((correct + wrong) / total) if total else None,
        "rejection_rate": (counts["rejected"] / total) if total else None,
    }
