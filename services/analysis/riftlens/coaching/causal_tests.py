from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from statistics import median
from typing import Any

from riftlens.domain.finding import Finding

CausalTest = Callable[["CausalTestContext"], bool]

_TESTS: dict[str, CausalTest] = {}


@dataclass(frozen=True)
class CausalTestContext:
    """Inputs for a causal-graph test. Tests may only read structured findings/evidence."""

    symptom_concept_id: str
    symptom_findings: tuple[Finding, ...]
    all_findings: tuple[Finding, ...]
    params: Mapping[str, Any]


def register_causal_test(name: str) -> Callable[[CausalTest], CausalTest]:
    """Register ``fn`` under ``name``. Assumes names are unique dotted paths."""

    def decorator(fn: CausalTest) -> CausalTest:
        if name in _TESTS and _TESTS[name] is not fn:
            raise ValueError(f"causal test already registered: {name}")
        _TESTS[name] = fn
        return fn

    return decorator


def get_causal_test(name: str) -> CausalTest:
    """Return a registered causal test. Assumes the module was imported."""
    try:
        return _TESTS[name]
    except KeyError as exc:
        raise KeyError(f"unregistered causal test: {name}") from exc


def causal_test_names() -> frozenset[str]:
    """Return registered causal test names."""
    return frozenset(_TESTS)


def import_causal_tests() -> None:
    """Import this module so ``@register_causal_test`` side effects run."""
    return None


def _as_mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _evidence_maps(finding: Finding) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    for item in finding.evidence:
        mapped = _as_mapping(item.value)
        if mapped is not None:
            out.append(mapped)
    return out


def _info_age_ms(finding: Finding) -> int | None:
    for payload in _evidence_maps(finding):
        if "age_ms" in payload:
            try:
                return int(payload["age_ms"])
            except (TypeError, ValueError):
                continue
        if "info_age_ms" in payload:
            try:
                return int(payload["info_age_ms"])
            except (TypeError, ValueError):
                continue
    return None


def _wave_state(finding: Finding) -> str | None:
    for payload in _evidence_maps(finding):
        for key in ("wave_state", "waveState", "wave"):
            raw = payload.get(key)
            if isinstance(raw, str) and raw:
                return raw.upper()
    return None


def _ward_count(finding: Finding) -> int | None:
    for item in finding.evidence:
        label = item.label.casefold()
        payload = _as_mapping(item.value)
        if "ward" not in label and payload is None:
            continue
        if payload is not None and "count" in payload and "ward" in label:
            try:
                return int(payload["count"])
            except (TypeError, ValueError):
                continue
        if payload is not None and "wards" in payload:
            try:
                return int(payload["wards"])
            except (TypeError, ValueError):
                continue
    return None


@register_causal_test("coaching.causal.median_jungler_info_age_gt")
def median_jungler_info_age_gt(ctx: CausalTestContext) -> bool:
    """Return True when median inferred jungler info-age exceeds ``min_age_ms``."""
    ages = [_info_age_ms(item) for item in ctx.symptom_findings]
    known = [age for age in ages if age is not None]
    if not known:
        return False
    minimum = int(ctx.params.get("min_age_ms") or 45_000)
    return float(median(known)) > float(minimum)


@register_causal_test("coaching.causal.no_ward_before_majority_deaths")
def no_ward_before_majority_deaths(ctx: CausalTestContext) -> bool:
    """Return True when ≥min_fraction of deaths cite zero wards in lookback evidence."""
    counts = [_ward_count(item) for item in ctx.symptom_findings]
    known = [count for count in counts if count is not None]
    related = _nearby_rules(ctx, [str(item) for item in ctx.params.get("rule_ids") or ["R-003"]])
    if not known and related:
        return True
    if not known:
        return False
    fraction = sum(1 for count in known if count == 0) / len(known)
    return fraction >= float(ctx.params.get("min_fraction") or 0.6)


@register_causal_test("coaching.causal.majority_deaths_while_pushing")
def majority_deaths_while_pushing(ctx: CausalTestContext) -> bool:
    """Return True only when wave-state evidence exists and a majority is pushing."""
    states = [_wave_state(item) for item in ctx.symptom_findings]
    known = [state for state in states if state is not None]
    if not known:
        return False
    pushing = {"PUSHING", "CRASHED_THEIRS", "CRASHING", "SHOVE", "HARD_PUSH"}
    fraction = sum(1 for state in known if state in pushing) / len(known)
    return fraction >= float(ctx.params.get("min_fraction") or 0.6)


@register_causal_test("coaching.causal.related_rule_near")
def related_rule_near(ctx: CausalTestContext) -> bool:
    """Return True when a listed root-cause rule fires near most symptom findings."""
    return _nearby_rules(ctx, [str(item) for item in ctx.params.get("rule_ids") or []])


def _nearby_rules(ctx: CausalTestContext, rule_ids: Sequence[str]) -> bool:
    wanted = set(rule_ids)
    if not wanted or not ctx.symptom_findings:
        return False
    window = int(ctx.params.get("window_ms") or 1_000)
    peers = [item for item in ctx.all_findings if item.rule_id in wanted]
    if not peers:
        return False
    hits = 0
    for symptom in ctx.symptom_findings:
        if any(abs(peer.t_ms - symptom.t_ms) <= window for peer in peers):
            hits += 1
    return hits / len(ctx.symptom_findings) >= float(ctx.params.get("min_fraction") or 0.6)
