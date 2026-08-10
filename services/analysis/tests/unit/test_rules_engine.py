from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from riftlens.adapters.db.engine import init_database, make_session_factory
from riftlens.adapters.db.repositories import (
    SqlFindingRepository,
    SqlMatchRepository,
    SqlPlayerRepository,
    SqlReviewRepository,
)
from riftlens.analysis.rules.context import FeatureFacade, RuleContext, evidence_fact
from riftlens.analysis.rules.engine import RuleEngine, persist_findings
from riftlens.analysis.rules.loader import (
    RuleLoadError,
    import_predicate_modules,
    load_rule_file,
    load_rule_pack,
)
from riftlens.analysis.rules.models import RulePack, dump_rule_schema
from riftlens.analysis.rules.registry import global_predicates
from riftlens.config import Settings
from riftlens.domain.enums import FactKind, Role
from riftlens.domain.finding import Finding
from riftlens.domain.ids import new_ulid
from riftlens.domain.ports import PlayerRecord, ReviewRecord
from riftlens.domain.timeline import GameStateTimeline
from riftlens.logging import configure_logging
from riftlens.pipeline.ingest_riot.persist import persist_riot_match
from tests.helpers.gst import bundled_patch, fact, load_fixture_pair, load_gst, make_gst

_RESOURCES = Path(__file__).resolve().parents[2] / "riftlens" / "resources"
_SCHEMA = _RESOURCES / "rules" / "_schema.json"
_FIXTURE_A = "NA1_fixture_a"


@pytest.fixture(autouse=True)
def _bind_structlog_to_stderr() -> None:
    """Avoid PrintLogger writing to a pytest capture file closed by TestClient."""
    configure_logging()


@pytest.fixture
def pack() -> RulePack:
    import_predicate_modules()
    return load_rule_pack()


@pytest.fixture
def gst_a() -> GameStateTimeline:
    return load_gst(_FIXTURE_A)


def _minimal_rule_payload(concept_id: str = "LANING", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "T-TMP",
        "version": 1,
        "name": "tmp",
        "concept_id": concept_id,
        "category": "LANING",
        "severity_base": "LOW",
        "data_tier": "RIOT_ONLY",
        "applicability": {
            "roles": ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"],
            "queues": [440, 420],
            "phases": ["EARLY", "MID", "LATE"],
        },
        "trigger": {
            "evaluate_on": "EVENT",
            "fact_kinds": ["LEVEL_UP"],
            "predicate": "rules.test.always_fires",
        },
        "false_positives": ["synthetic a", "synthetic b"],
    }
    payload.update(overrides)
    return payload


def test_schema_file_matches_pydantic_model() -> None:
    dumped = dump_rule_schema()
    on_disk = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    assert on_disk == dumped


def test_always_fires_role_gate_and_suppression(pack: RulePack, gst_a: GameStateTimeline) -> None:
    patch = bundled_patch(gst_a.patch)
    pid = 5
    assert gst_a.role_of(pid) is Role.UTILITY
    findings = RuleEngine(pack, patch=patch).run(gst_a, pid)
    by_rule: dict[str, list[Finding]] = {}
    for finding in findings:
        by_rule.setdefault(finding.rule_id, []).append(finding)
    assert by_rule.get("T-001"), "always-fires must emit on LEVEL_UP"
    assert "T-002" not in by_rule
    weak = by_rule["T-003"]
    strong = by_rule["T-004"]
    assert weak and strong
    assert all(item.suppressed for item in weak)
    assert all(item.suppressed_by == "T-004" for item in weak)
    assert all(not item.suppressed for item in strong)
    assert "R-000" not in by_rule


def test_engine_fixture_a_under_500ms(pack: RulePack, gst_a: GameStateTimeline) -> None:
    patch = bundled_patch(gst_a.patch)
    engine = RuleEngine(pack, patch=patch)
    engine.run(gst_a, 5)
    started = time.perf_counter()
    engine.run(gst_a, 5)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert elapsed_ms < 500.0, f"engine took {elapsed_ms:.1f} ms"


def test_unavailable_required_inputs_skipped(gst_a: GameStateTimeline, tmp_path: Path) -> None:
    import_predicate_modules()
    path = tmp_path / "T-MISSING.yaml"
    path.write_text(
        yaml.safe_dump(
            _minimal_rule_payload(
                id="T-MISSING",
                required_inputs=[
                    {"facts": ["LEVEL_UP"]},
                    {"features": ["wave_state_estimate"]},
                    {"min_confidence": {"wave_state_estimate": 0.4}},
                ],
            ),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    rule = load_rule_file(path, concept_ids={"LANING"}, registry=global_predicates())
    logged = MagicMock()
    with patch("riftlens.analysis.rules.engine.log.info", logged):
        findings = RuleEngine(RulePack([rule], ["LANING"]), patch=bundled_patch(gst_a.patch)).run(
            gst_a, 5
        )
    assert findings == []
    logged.assert_called()
    assert logged.call_args.args[0] == "rule_inputs_unsatisfied"


def test_unknown_concept_id_fails_at_load(tmp_path: Path) -> None:
    import_predicate_modules()
    path = tmp_path / "bad.yaml"
    path.write_text(
        yaml.safe_dump(_minimal_rule_payload(concept_id="DOES.NOT.EXIST"), sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(RuleLoadError, match="unknown concept_id"):
        load_rule_file(path, concept_ids={"LANING"}, registry=global_predicates())


def test_malformed_rule_is_startup_error(tmp_path: Path) -> None:
    import_predicate_modules()
    path = tmp_path / "malformed.yaml"
    path.write_text("id: NOPE\nname: missing almost everything\n", encoding="utf-8")
    with pytest.raises(RuleLoadError, match="not a valid RuleDefinition"):
        load_rule_file(path, concept_ids={"LANING"}, registry=global_predicates())


def test_finding_stamps_rule_identity() -> None:
    import_predicate_modules()
    gst = make_gst([fact(0, FactKind.LEVEL_UP, 1, {"level": 2})], duration_ms=60_000)
    pack = load_rule_pack()
    rule = next(item for item in pack.rules if item.id == "T-001")
    ctx = RuleContext(gst, rule, 1, 0, patch=bundled_patch())
    finding = ctx.finding(
        confidence=1.0,
        evidence=[evidence_fact("stamp", {"ok": 1}, t_ms=0)],
    )
    assert finding.rule_id == "T-001"
    assert finding.rule_version == rule.version
    assert finding.concept_id == rule.concept_id
    with pytest.raises(ValueError, match="at least one Evidence"):
        ctx.finding(confidence=1.0, evidence=[])


def test_feature_facade_does_not_expose_quarantined_units(gst_a: GameStateTimeline) -> None:
    facade = FeatureFacade(gst_a, bundled_patch(gst_a.patch))
    assert not hasattr(facade, "gold_per_second")
    assert not hasattr(facade, "health_regen")
    assert "unspent_gold" in facade.available()
    assert "hp_fraction" in facade.available()


def test_window_trigger_uses_registered_segmenter(tmp_path: Path) -> None:
    import_predicate_modules()
    gst = load_gst(_FIXTURE_A)
    path = tmp_path / "T-WINDOW.yaml"
    path.write_text(
        yaml.safe_dump(
            _minimal_rule_payload(
                id="T-WINDOW",
                data_tier="RIOT_DERIVED",
                trigger={
                    "evaluate_on": "WINDOW",
                    "segmenter": "fights.segment_fights",
                    "predicate": "rules.test.always_fires",
                },
            ),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    rule = load_rule_file(path, concept_ids={"LANING"}, registry=global_predicates())
    findings = RuleEngine(RulePack([rule], ["LANING"]), patch=bundled_patch(gst.patch)).run(gst, 5)
    assert isinstance(findings, list)


@pytest.mark.asyncio
async def test_persist_findings_via_h4_repo(tmp_path: Path, gst_a: GameStateTimeline) -> None:
    settings = Settings(data_dir=tmp_path)
    engine_db = init_database(settings)
    try:
        factory = make_session_factory(engine_db)
        players = SqlPlayerRepository(factory)
        matches = SqlMatchRepository(factory)
        reviews = SqlReviewRepository(factory)
        findings_repo = SqlFindingRepository(factory)
        player_id = new_ulid()
        review_id = new_ulid()
        await players.upsert_player(
            PlayerRecord(id=player_id, display_name="local", is_local_user=1, created_at=1)
        )
        match, timeline = load_fixture_pair(_FIXTURE_A)
        await persist_riot_match(matches, match, timeline, now_ms=2)
        await reviews.upsert(
            ReviewRecord(
                id=review_id,
                player_id=player_id,
                match_id=match.metadata.match_id,
                participant_id=5,
                media_asset_id=None,
                sync_map_id=None,
                rule_pack_version="h6-1",
                engine_version="0.1.0",
                analysis_tiers='["RIOT"]',
                status="COMPLETE",
                summary_text=None,
                overall_scores=None,
                llm_provider=None,
                llm_model=None,
                llm_prompt_version=None,
                created_at=3,
                completed_at=4,
            )
        )
        found = RuleEngine(load_rule_pack(), patch=bundled_patch(gst_a.patch)).run(gst_a, 5)
        await persist_findings(findings_repo, review_id, found)
        stored = await findings_repo.list_for_review(review_id)
        assert len(stored) == len(found)
        if stored:
            evidence = await findings_repo.list_evidence(stored[0].id)
            assert evidence
    finally:
        engine_db.dispose()
