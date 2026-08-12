from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from riftlens.analysis.rules.engine import RuleEngine
from riftlens.analysis.rules.loader import import_predicate_modules, load_rule_file, load_rule_pack
from riftlens.analysis.rules.models import RulePack
from riftlens.analysis.rules.registry import global_predicates
from riftlens.domain.enums import DataTier, EvidenceKind, FactKind, Source
from riftlens.domain.evidence import Evidence
from riftlens.domain.fact import Provenance
from riftlens.domain.ids import new_ulid
from riftlens.domain.observation import (
    CameraControl,
    EntityObservation,
    HudObservation,
    HudValue,
    KnowledgeState,
    VisibilityState,
    VisualClaimKind,
    camera_from_capture,
    entity_visibility_evidence,
    evidence_origin_label,
    frame_observation_to_evidence,
    hud_value_evidence,
)
from riftlens.domain.observation.camera import CameraProvenance
from riftlens.domain.timeline import GameStateTimeline
from riftlens.pipeline.assemble.review_presentation import _evidence_json
from tests.helpers.gst import bundled_patch, fact, load_gst, make_gst
from tests.unit.test_frame_observation_r11 import _frame
from tests.unit.test_rules_engine import _minimal_rule_payload

_FIXTURE_A = "NA1_fixture_a"


def _gst_fingerprint(gst: GameStateTimeline) -> bytes:
    rows = []
    for item in gst.facts():
        rows.append(
            {
                "t_ms": item.t_ms,
                "kind": item.kind.value,
                "subject_kind": item.subject.kind,
                "subject_id": item.subject.id,
                "payload": dict(item.payload),
                "source": item.source.value,
                "confidence": item.confidence,
                "producer": item.provenance.producer,
                "producer_version": item.provenance.producer_version,
                "upstream": list(item.provenance.upstream),
            }
        )
    return json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def test_visual_observation_becomes_frame_evidence() -> None:
    observation = _frame(
        camera=camera_from_capture(camera_controlled=False),
        confidence=0.55,
        claim_kind=VisualClaimKind.OBSERVED,
    )
    evidence = frame_observation_to_evidence(
        observation,
        label="viewport_sampled",
        value={"sampled": True},
        claim_established=True,
    )
    assert evidence is not None
    assert evidence.kind is EvidenceKind.FRAME
    assert evidence.source is Source.VISUAL
    assert evidence.t_ms == observation.game_t_ms
    assert evidence.confidence == 0.55
    assert evidence.provenance is not None
    assert observation.observation_id in "".join(evidence.provenance.upstream)
    assert observation.media_artifact_id in "".join(evidence.provenance.upstream)
    payload = evidence.value
    assert isinstance(payload, dict)
    assert payload["observation_id"] == observation.observation_id
    assert evidence_origin_label(evidence.source) == "observed from replay footage"


def test_inferred_claim_stays_visual_inferred() -> None:
    observation = _frame(claim_kind=VisualClaimKind.INFERRED, confidence=0.3)
    evidence = frame_observation_to_evidence(
        observation,
        label="rotation_inferred",
        value={"inferred": True},
        claim_established=True,
    )
    assert evidence is not None
    assert evidence.source is Source.VISUAL_INFERRED
    assert evidence_origin_label(evidence.source) == "inferred from replay footage"
    assert evidence.source is not Source.RIOT_TIMELINE
    assert evidence.source is not Source.CV


def test_confidence_does_not_increase_on_conversion() -> None:
    observation = _frame(confidence=0.4)
    evidence = frame_observation_to_evidence(
        observation,
        label="kept",
        value={},
        claim_established=True,
        confidence=0.2,
    )
    assert evidence is not None
    assert evidence.confidence == 0.2
    with pytest.raises(Exception, match="cannot increase"):
        frame_observation_to_evidence(
            observation,
            label="boosted",
            value={},
            claim_established=True,
            confidence=0.9,
        )


def test_unknown_does_not_become_affirmative_evidence() -> None:
    observation = _frame(confidence=0.5)
    unknown = EntityObservation(
        entity_observation_id=new_ulid(),
        visibility=VisibilityState.UNKNOWN,
        confidence=0.0,
    )
    assert entity_visibility_evidence(observation, unknown) is None
    not_detected = EntityObservation(
        entity_observation_id=new_ulid(),
        visibility=VisibilityState.NOT_VISIBLE,
        confidence=0.4,
        identity_knowledge=KnowledgeState.UNKNOWN,
    )
    assert entity_visibility_evidence(observation, not_detected) is None
    known_absent = EntityObservation(
        entity_observation_id=new_ulid(),
        visibility=VisibilityState.NOT_VISIBLE,
        confidence=0.4,
        identity_knowledge=KnowledgeState.ABSENT,
    )
    absent_evidence = entity_visibility_evidence(observation, known_absent)
    assert absent_evidence is not None
    assert absent_evidence.source is Source.VISUAL
    visible = EntityObservation(
        entity_observation_id=new_ulid(),
        visibility=VisibilityState.VISIBLE,
        confidence=0.3,
        champion_id="Kaisa",
    )
    visible_evidence = entity_visibility_evidence(observation, visible)
    assert visible_evidence is not None
    assert visible_evidence.confidence == 0.3


def test_missing_hud_is_not_evidence() -> None:
    observation = _frame(
        hud=HudObservation(hud_visible=KnowledgeState.UNKNOWN),
        confidence=0.8,
    )
    assert observation.hud is not None
    assert hud_value_evidence(observation, "health", observation.hud.get("health")) is None
    known = HudValue(knowledge=KnowledgeState.KNOWN, value=0.2, confidence=0.5)
    evidence = hud_value_evidence(observation, "health", known)
    assert evidence is not None
    assert evidence.confidence == 0.5
    assert evidence.t_ms == observation.game_t_ms


def test_h8_labels_visual_evidence_distinctly() -> None:
    observation = _frame()
    evidence = frame_observation_to_evidence(
        observation,
        label="viewport_sampled",
        value={"sampled": True},
        claim_established=True,
    )
    assert evidence is not None
    body = _evidence_json(evidence)
    assert body["source"] == "VISUAL"
    assert body["origin_label"] == "observed from replay footage"
    riot = Evidence(
        kind=EvidenceKind.FACT,
        label="gold",
        value=1,
        source=Source.RIOT_TIMELINE,
        t_ms=1000,
        confidence=1.0,
        provenance=Provenance(producer="test", producer_version=1),
    )
    riot_body = _evidence_json(riot)
    assert riot_body["origin_label"] == "riot timeline"
    assert riot_body["source"] == "RIOT_TIMELINE"


def test_gst_byte_identical_with_observations_present(gst_a: GameStateTimeline) -> None:
    before = _gst_fingerprint(gst_a)
    before_count = len(gst_a.facts())
    _frame(
        match_id=gst_a.match_id,
        camera=CameraProvenance(control=CameraControl.UNCONTROLLED, confidence=1.0),
        hud=HudObservation(),
    )
    after = _gst_fingerprint(gst_a)
    assert before == after
    assert len(gst_a.facts()) == before_count
    assert DataTier.CV_REQUIRED not in gst_a.available_data_tiers


def test_requires_visual_suppresses_when_visual_tier_absent(
    gst_a: GameStateTimeline, tmp_path: Path
) -> None:
    import_predicate_modules()
    yaml_path = tmp_path / "T-VISUAL.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            _minimal_rule_payload(id="T-VISUAL", requires_visual=True),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    rule = load_rule_file(yaml_path, concept_ids={"LANING"}, registry=global_predicates())
    assert rule.requires_visual is True
    findings = RuleEngine(RulePack([rule], ["LANING"]), patch=bundled_patch(gst_a.patch)).run(
        gst_a, 5
    )
    assert findings == []


def test_requires_visual_applies_when_cv_tier_present() -> None:
    import_predicate_modules()
    gst = make_gst([fact(0, FactKind.LEVEL_UP, 1, {"level": 2})], duration_ms=60_000)
    gst.available_data_tiers = frozenset(
        {DataTier.RIOT_ONLY, DataTier.RIOT_DERIVED, DataTier.CV_REQUIRED}
    )
    from pathlib import Path
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as folder:
        path = Path(folder) / "T-VISUAL.yaml"
        path.write_text(
            yaml.safe_dump(
                _minimal_rule_payload(
                    id="T-VISUAL",
                    requires_visual=True,
                    applicability={
                        "roles": ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"],
                        "queues": [420],
                        "phases": ["EARLY", "MID", "LATE"],
                    },
                ),
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        rule = load_rule_file(path, concept_ids={"LANING"}, registry=global_predicates())
        findings = RuleEngine(RulePack([rule], ["LANING"]), patch=bundled_patch()).run(gst, 1)
    assert findings
    assert findings[0].rule_id == "T-VISUAL"


def test_production_rules_do_not_require_visual() -> None:
    pack = load_rule_pack()
    production = [rule for rule in pack.rules if not rule.id.startswith("T-")]
    assert production
    assert all(rule.requires_visual is False for rule in production)


def test_h6_evidence_riot_source_unchanged() -> None:
    evidence = Evidence(
        kind=EvidenceKind.FACT,
        label="cs",
        value=50,
        source=Source.RIOT_TIMELINE,
        t_ms=60_000,
        confidence=1.0,
    )
    assert evidence.source is Source.RIOT_TIMELINE
    assert evidence.kind is EvidenceKind.FACT
    with pytest.raises(ValueError, match="0..1"):
        Evidence(
            kind=EvidenceKind.FACT,
            label="bad",
            value=1,
            source=Source.RIOT_TIMELINE,
            confidence=1.5,
        )


def test_h7_findings_unchanged_when_observations_constructed(gst_a: GameStateTimeline) -> None:
    pack = load_rule_pack()
    patch = bundled_patch(gst_a.patch)
    before = [
        (item.rule_id, item.t_ms, item.concept_id, item.title, item.severity.value)
        for item in RuleEngine(pack, patch=patch).run(gst_a, 5)
    ]
    _frame(match_id=gst_a.match_id)
    after = [
        (item.rule_id, item.t_ms, item.concept_id, item.title, item.severity.value)
        for item in RuleEngine(pack, patch=patch).run(gst_a, 5)
    ]
    assert before == after


@pytest.fixture
def gst_a() -> GameStateTimeline:
    return load_gst(_FIXTURE_A)
