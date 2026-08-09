from __future__ import annotations

from pathlib import Path

import pytest
from riftlens.analysis.rules.loader import RuleLoadError, load_taxonomy, validate_taxonomy_parents

_TAXONOMY = (
    Path(__file__).resolve().parents[2]
    / "riftlens"
    / "resources"
    / "taxonomy"
    / "taxonomy.yaml"
)


def test_full_taxonomy_parents_resolve() -> None:
    concepts = load_taxonomy(_TAXONOMY)
    ids = {str(item["id"]) for item in concepts}
    assert "FUNDAMENTALS" in ids
    assert "LANING.FARM" in ids
    assert "LANING.WAVE_MANAGEMENT.SLOW_PUSH" in ids
    assert "RISK.DEATH_CAUSE.DEATH_TO_UNSEEN_JUNGLER" in ids
    assert "VISION.PLACEMENT" in ids
    assert len(concepts) >= 140
    for item in concepts:
        parent = item.get("parent_id")
        if parent:
            assert parent in ids


def test_missing_parent_fails_loudly() -> None:
    with pytest.raises(RuleLoadError, match="does not resolve"):
        validate_taxonomy_parents(
            [
                {
                    "id": "LANING.MISSING_CHILD",
                    "parent_id": "LANING.DOES_NOT_EXIST",
                    "domain": "LANING",
                    "label": "x",
                    "description": "x",
                    "data_tier": "RIOT_ONLY",
                    "teachability": 1.0,
                    "roles": ["TOP"],
                    "phases": ["EARLY"],
                }
            ],
            source="test",
        )
