from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import structlog

from riftlens.analysis.rules.champion_tags import load_champion_tags
from riftlens.analysis.rules.context import FeatureFacade, RuleContext
from riftlens.analysis.rules.models import RuleDefinition, RulePack
from riftlens.analysis.rules.postprocess import DEFAULT_CONFIDENCE_FLOOR, postprocess
from riftlens.analysis.rules.registry import (
    PredicateRegistry,
    get_segmenter,
    global_predicates,
)
from riftlens.domain.enums import FactKind, GamePhase
from riftlens.domain.fact import SubjectRef
from riftlens.domain.finding import Finding
from riftlens.domain.ports import EvidenceRecord, FindingRecord, FindingRepository, PatchData
from riftlens.domain.timeline import GameStateTimeline

log = structlog.get_logger("riftlens.analysis.rules")


class RuleEngine:
    """Evaluate a RulePack against one participant on a GameStateTimeline."""

    def __init__(
        self,
        pack: RulePack,
        registry: PredicateRegistry | None = None,
        *,
        patch: PatchData,
        min_confidence: float = DEFAULT_CONFIDENCE_FLOOR,
        champion_tags: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        self.pack = pack
        self.registry = registry or global_predicates()
        self.patch = patch
        self.min_confidence = min_confidence
        loaded = load_champion_tags() if champion_tags is None else champion_tags
        self._champion_tags = {name: tuple(tags) for name, tags in dict(loaded).items()}

    def run(self, gst: GameStateTimeline, subject_pid: int) -> list[Finding]:
        """Return postprocessed findings for ``subject_pid``. Assumes GST is complete."""
        champion = gst.champion_of(subject_pid)
        tags = self._champion_tags.get(champion, ())
        applicable = self.pack.applicable(
            role=gst.role_of(subject_pid),
            champion=champion,
            patch=gst.patch,
            queue=gst.queue_id,
            available_tiers=gst.available_data_tiers,
            champion_tags=tags,
        )
        features = FeatureFacade(gst, self.patch)
        findings: list[Finding] = []
        for rule in applicable:
            findings.extend(self._run_rule(gst, subject_pid, rule, features))
        return postprocess(findings, applicable, min_confidence=self.min_confidence)

    def _run_rule(
        self,
        gst: GameStateTimeline,
        subject_pid: int,
        rule: RuleDefinition,
        features: FeatureFacade,
    ) -> list[Finding]:
        predicate = self.registry[rule.trigger.predicate]
        times = self._candidate_times(rule, gst, subject_pid)
        if not times:
            return []
        probe = RuleContext(
            gst, rule, subject_pid, times[0], patch=self.patch, features=features
        )
        if not probe.inputs_satisfied():
            log.info(
                "rule_inputs_unsatisfied",
                rule_id=rule.id,
                concept_id=rule.concept_id,
                subject_pid=subject_pid,
                required_inputs=list(rule.required_feature_names())
                + list(rule.required_fact_names()),
            )
            return []
        findings: list[Finding] = []
        for t_ms in times:
            ctx = RuleContext(gst, rule, subject_pid, t_ms, patch=self.patch, features=features)
            if not ctx.inputs_satisfied():
                continue
            finding = predicate(ctx)
            if finding is not None:
                findings.append(finding)
        return findings

    def _candidate_times(
        self, rule: RuleDefinition, gst: GameStateTimeline, subject_pid: int
    ) -> list[int]:
        phases = frozenset(rule.applicability.phases)
        mode = rule.trigger.evaluate_on
        if mode == "EVENT":
            times = _event_times(rule, gst, subject_pid)
        elif mode == "PERIODIC":
            period = rule.trigger.period_ms or 30_000
            times = list(range(0, max(gst.duration_ms, 0) + 1, period))
        else:
            segmenter = get_segmenter(rule.trigger.segmenter or "")
            times = [int(stamp) for stamp in segmenter(gst, subject_pid)]
        return [t_ms for t_ms in times if gst.phase(t_ms) in phases]


_GLOBAL_EVENT_KINDS = frozenset(
    {
        FactKind.ELITE_MONSTER_KILL,
        FactKind.BUILDING_KILL,
        FactKind.TURRET_PLATE_DESTROYED,
        FactKind.GAME_END,
        FactKind.PAUSE_END,
    }
)


def _event_times(rule: RuleDefinition, gst: GameStateTimeline, subject_pid: int) -> list[int]:
    kinds = rule.event_fact_kinds()
    if not kinds:
        kinds = (FactKind.LEVEL_UP,)
    subject = SubjectRef(kind="participant", id=subject_pid)
    stamps: set[int] = set()
    for kind in kinds:
        if kind in _GLOBAL_EVENT_KINDS:
            for fact in gst.facts(kind=kind):
                stamps.add(fact.t_ms)
            continue
        for fact in gst.facts(kind=kind, subject=subject):
            stamps.add(fact.t_ms)
        if kind is FactKind.CHAMPION_KILL:
            for fact in gst.facts(kind=kind):
                if fact.payload.get("victimId") == subject_pid:
                    stamps.add(fact.t_ms)
    return sorted(stamps)


async def persist_findings(
    repo: FindingRepository,
    review_id: str,
    findings: Sequence[Finding],
) -> None:
    """Insert findings and evidence via the H.4 repository. Assumes the review exists."""
    for finding in findings:
        record, evidence = finding_to_records(finding, review_id)
        await repo.add(record, evidence)


def finding_to_records(
    finding: Finding, review_id: str
) -> tuple[FindingRecord, list[EvidenceRecord]]:
    """Map a domain Finding onto H.4 persistence rows. Assumes ``review_id`` exists."""
    record = FindingRecord(
        id=finding.id,
        review_id=review_id,
        rule_id=finding.rule_id,
        rule_version=finding.rule_version,
        concept_id=finding.concept_id,
        t_ms=finding.t_ms,
        t_end_ms=finding.t_end_ms,
        severity=finding.severity.value,
        confidence=finding.confidence,
        gold_equivalent=finding.gold_equivalent,
        outcome=finding.outcome,
        map_x=finding.map_x,
        map_y=finding.map_y,
        title=finding.title,
        explanation=finding.explanation,
        alternative=finding.alternative,
        explanation_source=finding.explanation_source,
        suppressed=1 if finding.suppressed else 0,
        suppressed_by=finding.suppressed_by,
    )
    evidence = [
        EvidenceRecord(
            finding_id=finding.id,
            kind=item.kind.value,
            label=item.label,
            value_json=json.dumps(_jsonable(item.value), sort_keys=True, separators=(",", ":")),
            t_ms=item.t_ms,
            source=item.source.value,
            confidence=item.confidence,
            provenance_json=_provenance_json(item.provenance),
        )
        for item in finding.evidence
    ]
    return record, evidence


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, GamePhase):
        return value.value
    return str(value)


def _provenance_json(provenance: object) -> str | None:
    if provenance is None:
        return None
    producer = getattr(provenance, "producer", None)
    version = getattr(provenance, "producer_version", None)
    upstream = getattr(provenance, "upstream", ())
    payload = {
        "producer": producer,
        "producer_version": version,
        "upstream": list(upstream),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
