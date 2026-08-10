from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from riftlens.domain.enums import DataTier, FactKind, GamePhase, Role
from riftlens.domain.ports import MetricValueRecord, PatchData
from riftlens.domain.timeline import GameStateTimeline


@dataclass(frozen=True)
class RequiredInputs:
    fact_kinds: tuple[FactKind, ...] = ()
    features: tuple[str, ...] = ()
    data_tiers: tuple[DataTier, ...] = (DataTier.RIOT_ONLY, DataTier.RIOT_DERIVED)


@dataclass(frozen=True)
class MetricValue:
    metric_id: str
    value: float
    unit: str
    phase: GamePhase | str | None
    confidence: float
    baseline_key: str | None = None
    baseline_percentile: float | None = None
    sample_context: str = ""
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_record(self, review_id: str) -> MetricValueRecord:
        """Return a persistence row. Assumes ``review_id`` already exists."""
        phase = self.phase.value if isinstance(self.phase, GamePhase) else self.phase
        return MetricValueRecord(
            review_id=review_id,
            metric_id=self.metric_id,
            phase=phase,
            value=self.value,
            unit=self.unit,
            confidence=self.confidence,
            baseline_key=self.baseline_key,
            baseline_p50=None,
            baseline_percentile=self.baseline_percentile,
            detail_json=json.dumps(dict(self.detail), sort_keys=True, separators=(",", ":")),
        )


class MetricComputer(Protocol):
    id: str
    concept_id: str
    requires: RequiredInputs
    phases: tuple[GamePhase, ...]

    def compute(self, gst: GameStateTimeline, pid: int) -> list[MetricValue]:
        """Return metric rows for ``pid``. Assumes GST is the only data source."""


class BaselineTable:
    """Provisional percentile bands loaded from YAML. Assumes Phase 11 will replace this."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._payload = dict(payload)
        metrics = payload.get("metrics")
        self._metrics: dict[str, Any] = metrics if isinstance(metrics, dict) else {}
        self.default_tier = str(payload.get("default_tier") or "UNRANKED")
        self.default_class = str(payload.get("default_class") or "UNKNOWN")

    def percentile(
        self,
        metric_id: str,
        value: float,
        *,
        role: Role,
        band_key: str,
    ) -> tuple[str, float | None]:
        """Return (baseline_key, percentile). Assumes bands are p10..p90."""
        bands = self._bands(metric_id, role, band_key)
        patch_label = "provisional"
        key = f"{self.default_tier}|{role.value}|{self.default_class}|{patch_label}|{band_key}"
        if not bands:
            return key, None
        return key, _percentile(value, bands)

    def _bands(self, metric_id: str, role: Role, band_key: str) -> dict[str, float] | None:
        metric = self._metrics.get(metric_id)
        if not isinstance(metric, dict):
            return None
        by_role = metric.get("bands")
        if not isinstance(by_role, dict):
            return None
        role_blob = by_role.get(role.value) or by_role.get("default")
        if not isinstance(role_blob, dict):
            return None
        cell = role_blob.get(band_key)
        if not isinstance(cell, dict):
            return None
        return {str(name): float(raw) for name, raw in cell.items() if _is_number(raw)}


@dataclass(frozen=True)
class MetricContext:
    patch: PatchData
    baselines: BaselineTable
    tier: str = "UNRANKED"
    champion_class: str = "UNKNOWN"


def _is_number(raw: object) -> bool:
    return isinstance(raw, int | float) and not isinstance(raw, bool)


def _percentile(value: float, bands: Mapping[str, float]) -> float | None:
    points: list[tuple[float, float]] = []
    for name, threshold in bands.items():
        if not name.startswith("p"):
            continue
        try:
            pct = float(name[1:])
        except ValueError:
            continue
        points.append((threshold, pct))
    if len(points) < 2:
        return None
    points.sort()
    if value <= points[0][0]:
        return max(1.0, points[0][1] - 5.0) if value < points[0][0] else points[0][1]
    if value >= points[-1][0]:
        return min(99.0, points[-1][1] + 5.0) if value > points[-1][0] else points[-1][1]
    for index in range(1, len(points)):
        left_v, left_p = points[index - 1]
        right_v, right_p = points[index]
        if value <= right_v:
            if right_v == left_v:
                return right_p
            mix = (value - left_v) / (right_v - left_v)
            return left_p + mix * (right_p - left_p)
    return None


def emit(
    metric_id: str,
    value: float,
    unit: str,
    *,
    phase: GamePhase | str | None,
    confidence: float,
    context: MetricContext,
    role: Role,
    band_key: str,
    sample_context: str = "",
    detail: Mapping[str, Any] | None = None,
) -> MetricValue:
    """Build a MetricValue with provisional percentile. Assumes baselines were loaded."""
    baseline_key, percentile = context.baselines.percentile(
        metric_id, value, role=role, band_key=band_key
    )
    return MetricValue(
        metric_id=metric_id,
        value=value,
        unit=unit,
        phase=phase,
        confidence=confidence,
        baseline_key=baseline_key,
        baseline_percentile=percentile,
        sample_context=sample_context,
        detail=dict(detail or {}),
    )


def load_provisional_baselines(path: str | None = None) -> BaselineTable:
    """Return provisional.yaml bands. Assumes the resource file is shipped with the package."""
    target = (
        Path(path)
        if path
        else Path(__file__).resolve().parents[2] / "resources" / "baselines" / "provisional.yaml"
    )
    payload = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("provisional.yaml must be a mapping")
    return BaselineTable(payload)
