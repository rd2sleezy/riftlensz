from __future__ import annotations

from pathlib import Path

import yaml
from riftlens.analysis.rules.engine import RuleEngine
from riftlens.analysis.rules.loader import load_rule_pack
from tests.helpers.gst import bundled_patch
from tests.helpers.h7_scenarios import LABELLED

_CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "labelled_corpus"


def test_labelled_corpus_aggregate_precision() -> None:
    """Precision on 15 synthetic GSTs. These are not 15 real Riot games."""
    pack = load_rule_pack()
    production = {
        rule.id
        for rule in pack.rules
        if rule.id.startswith(("R-0", "P-0")) and rule.id != "R-000"
    }
    tp = 0
    fp = 0
    assert len(LABELLED) == 15
    for name, builder, _fallback in LABELLED:
        expected_path = _CORPUS / name / "expected.yaml"
        payload = yaml.safe_load(expected_path.read_text(encoding="utf-8"))
        assert payload["synthetic"] is True
        assert payload["match_id"] == name
        allowed = set(payload.get("expected_rule_ids") or [])
        gst = builder()
        pid = int(payload["subject_pid"])
        findings = RuleEngine(pack, patch=bundled_patch(gst.patch)).run(gst, pid)
        visible = [
            item
            for item in findings
            if not item.suppressed and item.rule_id in production
        ]
        for item in visible:
            if item.rule_id in allowed:
                tp += 1
            else:
                fp += 1
    total = tp + fp
    precision = 1.0 if total == 0 else tp / total
    assert precision >= 0.8, f"precision={precision:.3f} tp={tp} fp={fp}"


def test_labelled_expected_files_exist() -> None:
    for name, _builder, _expected in LABELLED:
        path = _CORPUS / name / "expected.yaml"
        assert path.is_file(), path
