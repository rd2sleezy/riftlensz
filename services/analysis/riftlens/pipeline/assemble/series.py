from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from riftlens.domain.enums import FactKind
from riftlens.domain.timeline import GameStateTimeline

_KIND_MAP = {
    "gold": FactKind.GOLD,
    "cs": FactKind.CS,
    "level": FactKind.LEVEL,
    "xp": FactKind.XP,
    "health": FactKind.HEALTH,
}


def review_series(
    gst: GameStateTimeline,
    participant_id: int,
    *,
    kinds: Sequence[str],
    stride_ms: int,
) -> dict[str, Any]:
    """Return downsampled GST series. Stride is deterministic; no new coaching logic."""
    stride = max(1_000, int(stride_ms))
    wanted = [item.strip().lower() for item in kinds if item.strip()]
    if not wanted:
        wanted = ["gold", "cs", "level"]
    times = list(range(0, max(gst.duration_ms, 0) + 1, stride))
    if times[-1] != gst.duration_ms:
        times.append(gst.duration_ms)
    series: dict[str, list[dict[str, Any]]] = {}
    for kind_name in wanted:
        fact_kind = _KIND_MAP.get(kind_name)
        if fact_kind is None:
            continue
        points: list[dict[str, Any]] = []
        for t_ms in times:
            snap = gst.at(t_ms)
            part = snap.participants.get(participant_id)
            estimate = None if part is None else getattr(part, kind_name, None)
            value = None if estimate is None else estimate.value
            points.append(
                {
                    "t_ms": t_ms,
                    "value": value,
                    "confidence": None if estimate is None else estimate.confidence,
                }
            )
        series[kind_name] = points
    return {
        "match_id": gst.match_id,
        "participant_id": participant_id,
        "stride_ms": stride,
        "kinds": list(series.keys()),
        "series": series,
    }
