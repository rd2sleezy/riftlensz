from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import yaml

from riftlens.analysis.rules.loader import load_taxonomy
from riftlens.domain.enums import IssueType, RankTier

_COACHING = Path(__file__).resolve().parents[1] / "resources" / "coaching"


@dataclass(frozen=True)
class ScoringConfig:
    confidence_floor: float
    frequency_exponent: float
    diversity_penalty: float
    domain_dominance_ratio: float
    max_gold_equivalent: float
    unspent_gold_weight: float
    default_death_gold: float
    default_cs_gold_per_minion: float
    focus_count: int
    secondary_cap: int
    strength_min: int
    strength_max: int
    dedup_window_ms: int
    incident_window_ms: int
    exemplar_clip_count: int
    min_title_words: int
    max_title_words: int
    confidence_mode: str
    unranked_treats_as: str
    below_gold_tiers: frozenset[str]
    gold_floor_for_zero: float
    outcome_gold: Mapping[str, float]


@dataclass(frozen=True)
class CauseSpec:
    concept_id: str
    strength: float
    test: str
    params: Mapping[str, Any]
    description: str


@dataclass(frozen=True)
class SymptomSpec:
    symptom: str
    causes: tuple[CauseSpec, ...]


@dataclass(frozen=True)
class CausalGraph:
    edges: tuple[SymptomSpec, ...]

    def causes_for(self, concept_id: str) -> tuple[CauseSpec, ...]:
        """Return authored causes for ``concept_id``, or empty if it is not a symptom."""
        for edge in self.edges:
            if edge.symptom == concept_id:
                return edge.causes
        return ()


@dataclass(frozen=True)
class CheckCopy:
    title: str
    the_fix: str
    next_game_check: str


@dataclass(frozen=True)
class TaxonomyIndex:
    by_id: Mapping[str, Mapping[str, Any]]

    def domain_of(self, concept_id: str) -> str:
        """Return the taxonomy domain for ``concept_id``, or the first path segment."""
        row = self.by_id.get(concept_id)
        if row is not None:
            domain = row.get("domain")
            if isinstance(domain, str) and domain:
                return domain
        if "." in concept_id:
            return concept_id.split(".", 1)[0]
        return concept_id or "UNKNOWN"

    def teachability(self, concept_id: str) -> float:
        """Return taxonomy teachability, walking to parents when a leaf is missing."""
        for key in _walk_ids(concept_id):
            row = self.by_id.get(key)
            if row is None:
                continue
            raw = row.get("teachability")
            if isinstance(raw, int | float) and not isinstance(raw, bool):
                return float(raw)
        return 1.0

    def parent_of(self, concept_id: str) -> str | None:
        """Return parent id or None. Assumes taxonomy parents resolve."""
        row = self.by_id.get(concept_id)
        if row is None:
            return None
        parent = row.get("parent_id", row.get("parent"))
        if parent in (None, ""):
            return None
        return str(parent)

    def label(self, concept_id: str) -> str:
        """Return the taxonomy label, or the concept id."""
        row = self.by_id.get(concept_id)
        if row is None:
            return concept_id
        label = row.get("label")
        return str(label) if label else concept_id


@dataclass(frozen=True)
class RankRelevanceTable:
    ranks: tuple[str, ...]
    default_value: float
    curves: Mapping[str, tuple[float, ...]]
    issue_types: Mapping[str, IssueType]
    unranked_treats_as: str

    def relevance(self, concept_id: str, rank: str) -> float:
        """Return the rank-relevance multiplier for ``concept_id`` at ``rank``."""
        resolved = self._resolve_rank(rank)
        index = self._rank_index(resolved)
        for key in _walk_ids(concept_id):
            curve = self.curves.get(key)
            if curve is not None:
                return curve[min(index, len(curve) - 1)]
        return self.default_value

    def issue_type(self, concept_id: str) -> IssueType:
        """Return MECHANICAL/TACTICAL/STRATEGIC by walking concept → parent → domain."""
        for key in _walk_ids(concept_id):
            found = self.issue_types.get(key)
            if found is not None:
                return found
        return IssueType.TACTICAL

    def is_below_gold(self, rank: str, below: frozenset[str]) -> bool:
        """Return True when rank constraint §6.5 applies."""
        if rank.upper() in below:
            return True
        resolved = self._resolve_rank(rank)
        try:
            order = [item.value for item in RankTier if item is not RankTier.UNRANKED]
            return order.index(resolved) < order.index(RankTier.GOLD.value)
        except ValueError:
            return True

    def _resolve_rank(self, rank: str) -> str:
        key = rank.strip().upper()
        if key == RankTier.UNRANKED.value:
            return self.unranked_treats_as
        if key in {item.value for item in RankTier}:
            return key
        return self.unranked_treats_as

    def _rank_index(self, rank: str) -> int:
        try:
            return self.ranks.index(rank)
        except ValueError:
            return 0


def load_scoring(path: Path | None = None) -> ScoringConfig:
    """Load scoring.yaml. Assumes the file is a mapping of numeric knobs."""
    payload = _load_yaml(path or _COACHING / "scoring.yaml")
    below = payload.get("below_gold_tiers") or ["IRON", "BRONZE", "SILVER", "UNRANKED"]
    outcomes = payload.get("outcome_gold") or {}
    return ScoringConfig(
        confidence_floor=float(payload["confidence_floor"]),
        frequency_exponent=float(payload["frequency_exponent"]),
        diversity_penalty=float(payload["diversity_penalty"]),
        domain_dominance_ratio=float(payload["domain_dominance_ratio"]),
        max_gold_equivalent=float(payload["max_gold_equivalent"]),
        unspent_gold_weight=float(payload["unspent_gold_weight"]),
        default_death_gold=float(payload["default_death_gold"]),
        default_cs_gold_per_minion=float(payload["default_cs_gold_per_minion"]),
        focus_count=int(payload["focus_count"]),
        secondary_cap=int(payload["secondary_cap"]),
        strength_min=int(payload["strength_min"]),
        strength_max=int(payload["strength_max"]),
        dedup_window_ms=int(payload["dedup_window_ms"]),
        incident_window_ms=int(payload["incident_window_ms"]),
        exemplar_clip_count=int(payload["exemplar_clip_count"]),
        min_title_words=int(payload["min_title_words"]),
        max_title_words=int(payload["max_title_words"]),
        confidence_mode=str(payload.get("confidence_mode") or "min"),
        unranked_treats_as=str(payload.get("unranked_treats_as") or "IRON"),
        below_gold_tiers=frozenset(str(item).upper() for item in below),
        gold_floor_for_zero=float(payload.get("gold_floor_for_zero") or 1.0),
        outcome_gold={str(key): float(value) for key, value in dict(outcomes).items()},
    )


def load_causal_graph(path: Path | None = None) -> CausalGraph:
    """Load causal_graph.yaml. Assumes every ``test`` is a registered predicate name."""
    payload = _load_yaml(path or _COACHING / "causal_graph.yaml")
    raw_edges = payload.get("edges") or []
    edges: list[SymptomSpec] = []
    for item in raw_edges:
        if not isinstance(item, Mapping):
            raise ValueError("causal_graph edges must be mappings")
        causes: list[CauseSpec] = []
        for cause in item.get("causes") or []:
            if not isinstance(cause, Mapping):
                raise ValueError("causal_graph cause must be a mapping")
            causes.append(
                CauseSpec(
                    concept_id=str(cause["concept"]),
                    strength=float(cause.get("strength") or 0.0),
                    test=str(cause["test"]),
                    params=dict(cause.get("params") or {}),
                    description=str(cause.get("description") or cause["test"]),
                )
            )
        edges.append(SymptomSpec(symptom=str(item["symptom"]), causes=tuple(causes)))
    return CausalGraph(tuple(edges))


def load_checks(path: Path | None = None) -> Mapping[str, CheckCopy]:
    """Load checks.yaml concept copy. Assumes defaults exist for unknown concepts."""
    payload = _load_yaml(path or _COACHING / "checks.yaml")
    defaults = payload.get("defaults") or {}
    fallback = CheckCopy(
        title=str(defaults.get("title") or "Fix this repeated mistake"),
        the_fix=str(defaults.get("the_fix") or ""),
        next_game_check=str(defaults.get("next_game_check") or ""),
    )
    out: dict[str, CheckCopy] = {"__default__": fallback}
    for key, raw in dict(payload.get("concepts") or {}).items():
        if not isinstance(raw, Mapping):
            continue
        out[str(key)] = CheckCopy(
            title=str(raw.get("title") or fallback.title),
            the_fix=str(raw.get("the_fix") or fallback.the_fix),
            next_game_check=str(raw.get("next_game_check") or fallback.next_game_check),
        )
    return out


def load_rank_relevance(
    path: Path | None = None, *, unranked_treats_as: str = "IRON"
) -> RankRelevanceTable:
    """Load rank_relevance.yaml curves. Assumes each curve matches ``ranks`` length."""
    payload = _load_yaml(path or _COACHING / "rank_relevance.yaml")
    ranks = tuple(str(item) for item in payload.get("ranks") or [])
    curves_raw = payload.get("curves") or {}
    curves: dict[str, tuple[float, ...]] = {}
    for key, values in dict(curves_raw).items():
        if not isinstance(values, list):
            raise ValueError(f"rank curve for {key} must be a list")
        curves[str(key)] = tuple(float(item) for item in values)
    types_raw = payload.get("issue_types") or {}
    types: dict[str, IssueType] = {}
    for key, value in dict(types_raw).items():
        types[str(key)] = IssueType(str(value))
    return RankRelevanceTable(
        ranks=ranks,
        default_value=float(payload.get("default_value") or 1.0),
        curves=curves,
        issue_types=types,
        unranked_treats_as=unranked_treats_as,
    )


@lru_cache(maxsize=1)
def load_taxonomy_index() -> TaxonomyIndex:
    """Return taxonomy concepts keyed by id. Assumes taxonomy.yaml parents resolve."""
    rows = load_taxonomy()
    return TaxonomyIndex({str(item["id"]): dict(item) for item in rows})


def check_for(checks: Mapping[str, CheckCopy], concept_id: str) -> CheckCopy:
    """Return the closest authored check copy, walking parents then defaults."""
    for key in _walk_ids(concept_id):
        found = checks.get(key)
        if found is not None:
            return found
    return checks["__default__"]


def _walk_ids(concept_id: str) -> tuple[str, ...]:
    parts = [part for part in concept_id.split(".") if part]
    out = [concept_id]
    while parts:
        parts = parts[:-1]
        if parts:
            out.append(".".join(parts))
    return tuple(out)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"coaching data file missing: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must be a YAML mapping")
    return cast(dict[str, Any], loaded)


def validate_causal_tests(graph: CausalGraph, registered: Sequence[str]) -> None:
    """Raise if any graph ``test`` is not registered. Assumes registry was imported."""
    known = set(registered)
    missing = sorted(
        {cause.test for edge in graph.edges for cause in edge.causes if cause.test not in known}
    )
    if missing:
        raise ValueError(f"unregistered causal tests: {missing}")
