from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from types import SimpleNamespace
from typing import Any

from riftlens.analysis.features.deaths import DeathCause, classify, death_cost
from riftlens.analysis.features.fights import Fight, segment_fights
from riftlens.analysis.features.gold import unspent_gold
from riftlens.analysis.features.health import hp_fraction
from riftlens.analysis.features.jungle_info import info_age
from riftlens.analysis.rules.models import RuleDefinition
from riftlens.domain.enums import EvidenceKind, FactKind, Lane, Role, Severity, Source, Team
from riftlens.domain.estimate import Estimate
from riftlens.domain.evidence import Evidence
from riftlens.domain.fact import Fact, Provenance
from riftlens.domain.finding import Finding, require_evidence
from riftlens.domain.ids import new_ulid
from riftlens.domain.ports import PatchData
from riftlens.domain.timeline import GameStateTimeline

_FRAME_FACT_ALIASES = frozenset(
    {"PARTICIPANT_FRAME", "PARTICIPANT_FRAMES", "FRAME", "FRAMES"}
)
_SEVERITY_ORDER = (Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL)
_CMP = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?P<op>==|!=|>=|<=|>|<)\s*(?P<rhs>.+)$"
)
_KNOWN_FEATURES = frozenset(
    {
        "unspent_gold",
        "unspent_gold_estimate",
        "hp_fraction",
        "hp_fraction_estimate",
        "info_age",
        "segment_fights",
        "classify_death",
        "death_cost",
    }
)


class FeatureFacade:
    """H.5 feature functions over GST. Does not reimplement gold/hp/fights/deaths."""

    def __init__(self, gst: GameStateTimeline, patch: PatchData) -> None:
        self._gst = gst
        self._patch = patch
        self._fights: list[Fight] | None = None

    def available(self) -> frozenset[str]:
        """Return feature names this facade can evaluate. Assumes H.5 is loaded."""
        return _KNOWN_FEATURES

    def unspent_gold(self, pid: int, t_ms: int) -> Estimate[int]:
        """Return reconstructed currentGold. Assumes GOLD facts exist for ``pid``."""
        return unspent_gold(self._gst, pid, t_ms, self._patch)

    def hp_fraction(self, pid: int, t_ms: int) -> Estimate[float]:
        """Return HP/HPMax. Exact at frames; between frames regen is quarantined."""
        return hp_fraction(self._gst, pid, t_ms, self._patch)

    def info_age(self, team: Team, target_pid: int, t_ms: int) -> Estimate[int]:
        """Return ms since ``target_pid`` was observable by ``team``."""
        return info_age(self._gst, team, target_pid, t_ms)

    def segment_fights(self) -> list[Fight]:
        """Return cached fight clusters. Assumes CHAMPION_KILL facts carry positions."""
        if self._fights is None:
            self._fights = segment_fights(self._gst)
        return list(self._fights)

    def classify_death(self, kill_fact: Fact) -> Estimate[DeathCause]:
        """Return M-05 death cause for ``kill_fact``. Assumes it is a CHAMPION_KILL."""
        return classify(self._gst, kill_fact, self._patch)

    def death_cost(self, kill_fact: Fact) -> Estimate[float]:
        """Return gold-equivalent death cost. Assumes ``kill_fact`` is the victim death."""
        return death_cost(self._gst, kill_fact, self._patch)

    def resolve(self, name: str, pid: int, t_ms: int) -> Estimate[Any] | None:
        """Return a named estimate used by required_inputs min_confidence checks."""
        key = name.strip()
        if key in {"unspent_gold", "unspent_gold_estimate"}:
            return self.unspent_gold(pid, t_ms)
        if key in {"hp_fraction", "hp_fraction_estimate"}:
            return self.hp_fraction(pid, t_ms)
        if key in {"info_age"}:
            try:
                team = self._gst.participants[pid].team
            except KeyError:
                return None
            return self.info_age(team, pid, t_ms)
        return None


class RuleContext:
    """Per-candidate evaluation context. ``finding()`` is the only stamped constructor."""

    def __init__(
        self,
        gst: GameStateTimeline,
        rule: RuleDefinition,
        subject_pid: int,
        t_ms: int,
        *,
        patch: PatchData,
        features: FeatureFacade | None = None,
    ) -> None:
        self.gst = gst
        self.rule = rule
        self.subject_pid = subject_pid
        self.t_ms = t_ms
        self.patch = patch
        self.params = SimpleNamespace(**dict(rule.params))
        self.features = features or FeatureFacade(gst, patch)

    def lane_of(self, pid: int) -> Lane | None:
        """Return the lane axis for ``pid``, or None for jungle/unknown."""
        role = self.gst.role_of(pid)
        if role is Role.TOP:
            return Lane.TOP
        if role is Role.MIDDLE:
            return Lane.MIDDLE
        if role in {Role.BOTTOM, Role.UTILITY}:
            return Lane.BOTTOM
        return None

    def severity_with_modifiers(self, bindings: Mapping[str, Any]) -> Severity:
        """Return base severity plus YAML modifier deltas. Assumes bindings use YAML names."""
        severity = self.rule.severity_base
        delta = 0
        for modifier in self.rule.severity_modifiers:
            if _eval_condition(modifier.condition, bindings):
                delta += modifier.then
        return _shift_severity(severity, delta)

    def finding(
        self,
        *,
        evidence: Sequence[Evidence],
        confidence: float,
        severity: Severity | None = None,
        t_ms: int | None = None,
        t_end_ms: int | None = None,
        title: str | None = None,
        explanation: str | None = None,
        alternative: str | None = None,
        gold_equivalent: float | None = None,
        outcome: str | None = None,
        map_x: int | None = None,
        map_y: int | None = None,
        explanation_source: str = "TEMPLATE",
    ) -> Finding:
        """Return a Finding stamped with this rule's id/version/concept. Evidence required."""
        items = require_evidence(evidence)
        return Finding(
            id=new_ulid(),
            rule_id=self.rule.id,
            rule_version=self.rule.version,
            concept_id=self.rule.concept_id,
            t_ms=self.t_ms if t_ms is None else t_ms,
            t_end_ms=t_end_ms,
            severity=self.rule.severity_base if severity is None else severity,
            confidence=confidence,
            title=self.rule.name if title is None else title,
            explanation=explanation,
            alternative=alternative,
            explanation_source=explanation_source,
            gold_equivalent=gold_equivalent,
            outcome=outcome,
            map_x=map_x,
            map_y=map_y,
            evidence=items,
        )

    def inputs_satisfied(self) -> bool:
        """Return True when required facts/features exist at a usable confidence."""
        if not _facts_present(self.gst, self.rule.required_fact_names()):
            return False
        available = self.features.available()
        for name in self.rule.required_feature_names():
            if name not in available:
                return False
        for name, floor in self.rule.min_confidences().items():
            estimate = self.features.resolve(name, self.subject_pid, self.t_ms)
            if estimate is None or estimate.confidence < floor:
                return False
        return True


def evidence_fact(
    label: str,
    value: Mapping[str, Any] | str | int | float | bool | None,
    *,
    t_ms: int | None,
    source: Source = Source.RIOT_TIMELINE,
    confidence: float = 1.0,
    provenance: Provenance | None = None,
    kind: EvidenceKind = EvidenceKind.FACT,
) -> Evidence:
    """Return a FACT evidence item. Assumes ``label`` is UI-facing."""
    return Evidence(
        kind=kind,
        label=label,
        value=value,
        source=source,
        t_ms=t_ms,
        confidence=confidence,
        provenance=provenance,
    )


def _facts_present(gst: GameStateTimeline, names: Sequence[str]) -> bool:
    for name in names:
        key = name.strip().upper()
        if key in _FRAME_FACT_ALIASES:
            if not any(
                gst.facts(kind=kind)
                for kind in (FactKind.GOLD, FactKind.POSITION, FactKind.HEALTH)
            ):
                return False
            continue
        try:
            kind = FactKind(key)
        except ValueError:
            return False
        if not gst.facts(kind=kind):
            return False
    return True


def _shift_severity(base: Severity, delta: int) -> Severity:
    index = _SEVERITY_ORDER.index(base)
    next_index = max(0, min(len(_SEVERITY_ORDER) - 1, index + delta))
    return _SEVERITY_ORDER[next_index]


def _eval_condition(expr: str, bindings: Mapping[str, Any]) -> bool:
    match = _CMP.match(expr.strip())
    if match is None:
        return False
    name = match.group("name")
    if name not in bindings:
        return False
    left = bindings[name]
    right = _parse_rhs(match.group("rhs").strip())
    op = match.group("op")
    try:
        if op == "==":
            return bool(left == right)
        if op == "!=":
            return bool(left != right)
        if op == ">":
            return bool(left > right)
        if op == "<":
            return bool(left < right)
        if op == ">=":
            return bool(left >= right)
        if op == "<=":
            return bool(left <= right)
    except TypeError:
        return False
    return False


def _parse_rhs(raw: str) -> Any:
    if len(raw) >= 2 and raw[0] in {"'", '"'} and raw[-1] == raw[0]:
        return raw[1:-1]
    if raw in {"True", "False"}:
        return raw == "True"
    if raw == "None":
        return None
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw
