from __future__ import annotations

from pathlib import Path

import pytest
from riftlens.adapters.db.engine import init_database, make_session_factory
from riftlens.adapters.db.repositories import (
    SqlCoachingRepository,
    SqlFindingRepository,
    SqlReviewRepository,
)
from riftlens.cli import app
from riftlens.config import Settings
from riftlens.logging import configure_logging
from riftlens.pipeline.assemble.review_builder import build_review_from_dtos
from tests.helpers.gst import load_fixture_pair
from typer.testing import CliRunner

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "riot"


@pytest.fixture(autouse=True)
def _bind_structlog_to_stderr() -> None:
    configure_logging()


def test_cli_review_fixture_b_prints_focus_secondary_strengths_and_metrics(
    settings: Settings, monkeypatch: object
) -> None:
    monkeypatch.setattr("riftlens.cli.get_settings", lambda: settings)
    monkeypatch.setattr(
        "riftlens.pipeline.assemble.review_builder.get_settings", lambda: settings
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "review",
            "NA1_fixture_b",
            "--pid",
            "5",
            "--no-llm",
            "--no-persist",
            "--fixtures",
            str(_FIXTURES),
        ],
    )
    assert result.exit_code == 0, result.output
    text = result.output
    assert "FOCUS" in text
    assert "SECONDARY" in text
    assert "STRENGTHS" in text
    assert "METRICS" in text
    assert "M-01" in text
    assert "unpaired" in text.lower()
    assert "type=" in text
    assert "check:" in text
    assert "fix:" in text
    assert "evidence_t=" in text


def test_review_builder_persists_findings_and_coaching_items(settings: Settings) -> None:
    match, timeline = load_fixture_pair("NA1_fixture_b")
    built = build_review_from_dtos(
        match, timeline, 5, rank="SILVER", persist=True, settings=settings
    )
    review = built.review
    assert len(review.focus_items) <= 3
    if review.clusters:
        mistake_clusters = [item for item in review.clusters if not item.is_strength]
        if len(mistake_clusters) >= 3:
            assert len(review.focus_items) == 3
    assert all(item.evidence for item in review.findings)
    original_ids = {item.id for item in review.findings}
    grouped_ids = {row.finding_id for row in review.grouping_log}
    assert original_ids <= grouped_ids
    engine = init_database(settings)
    factory = make_session_factory(engine)
    stored = __import__("asyncio").run(SqlReviewRepository(factory).get(review.id))
    assert stored is not None
    assert stored.llm_provider == "null"
    findings = __import__("asyncio").run(SqlFindingRepository(factory).list_for_review(review.id))
    assert {row.id for row in findings} == original_ids
    items = __import__("asyncio").run(SqlCoachingRepository(factory).list_for_review(review.id))
    assert items
    linked = {fid for item in items for fid in item.finding_ids}
    assert linked <= original_ids


def test_causal_graph_tests_are_all_registered() -> None:
    from riftlens.coaching.causal_tests import causal_test_names, import_causal_tests
    from riftlens.coaching.data import load_causal_graph, validate_causal_tests

    import_causal_tests()
    validate_causal_tests(load_causal_graph(), sorted(causal_test_names()))
