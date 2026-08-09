from __future__ import annotations

from riftlens.analysis.rules.lab import collect_cases, format_report, run_rule_lab


def test_rule_lab_synthetic_corpus_and_report() -> None:
    cases = collect_cases(source="synthetic", limit=40)
    assert len(cases) == 40
    sources = {case.source for case in cases}
    assert sources & {"synthetic-labelled", "synthetic-must-fire", "synthetic-quiet"}
    ids = {case.match_id for case in cases}
    assert len(ids) == len(cases), "fire-rate corpus must not be identical copies"
    report = run_rule_lab("R-001", cases)
    text = format_report(report)
    assert "fire rate" in text
    assert report.matches == 40
    assert report.fire_rate <= 50.0 or "R-001" in text
