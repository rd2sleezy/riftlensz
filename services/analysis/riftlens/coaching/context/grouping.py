"""Deterministic temporal grouping of findings into episode windows.

Merged windows mean TEMPORAL_COPRESENCE only. They do not imply CAUSAL_RELATION,
parent/child structure, symptoms, or root causes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from riftlens.coaching.context.models import EpisodeBuilderConfig, finding_window
from riftlens.domain.finding import Finding
from riftlens.domain.timeline import GameStateTimeline


@dataclass(frozen=True)
class TemporalCluster:
    """One merged context window. Membership is temporal, not causal."""

    start_ms: int
    end_ms: int
    anchors: tuple[Finding, ...]
    associated: tuple[Finding, ...]


def cluster_findings_temporally(
    gst: GameStateTimeline,
    findings: Sequence[Finding],
    config: EpisodeBuilderConfig,
) -> list[TemporalCluster]:
    """Return merged context windows for non-suppressed findings.

    Suppressed findings never seed a cluster. If their ``t_ms`` falls inside a
    seeded window they are TEMPORALLY_ASSOCIATED and keep ``suppressed=True``.
    """
    seeds = [item for item in findings if not item.suppressed]
    if not seeds:
        return []
    ordered = sorted(seeds, key=lambda item: (_window(gst, item, config)[0], item.t_ms, item.id))
    opens: list[_OpenCluster] = []
    for item in ordered:
        start, end = _window(gst, item, config)
        if opens and start <= opens[-1].end_ms + config.merge_gap_ms:
            opens[-1].start_ms = min(opens[-1].start_ms, start)
            opens[-1].end_ms = max(opens[-1].end_ms, end)
            opens[-1].anchors.append(item)
            continue
        opens.append(_OpenCluster(start_ms=start, end_ms=end, anchors=[item]))
    suppressed = [item for item in findings if item.suppressed]
    return [_freeze(cluster, suppressed) for cluster in opens]


def _window(
    gst: GameStateTimeline, item: Finding, config: EpisodeBuilderConfig
) -> tuple[int, int]:
    return finding_window(item.t_ms, item.t_end_ms, gst.duration_ms, config)


def _freeze(cluster: _OpenCluster, suppressed: Sequence[Finding]) -> TemporalCluster:
    anchors = tuple(sorted(cluster.anchors, key=lambda item: (item.t_ms, item.id)))
    associated = tuple(
        sorted(
            (item for item in suppressed if cluster.start_ms <= item.t_ms <= cluster.end_ms),
            key=lambda item: (item.t_ms, item.id),
        )
    )
    return TemporalCluster(
        start_ms=cluster.start_ms,
        end_ms=cluster.end_ms,
        anchors=anchors,
        associated=associated,
    )


@dataclass
class _OpenCluster:
    start_ms: int
    end_ms: int
    anchors: list[Finding]
