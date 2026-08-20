"""Pure C.1 episode builder. No network, DB, LLM, replay, or visual I/O.

``build_coaching_episodes`` turns existing Findings plus GST into temporally
grouped CoachingEpisode objects. It does not change which findings fire or
which coaching items the player sees.

Grouping is TEMPORAL_COPRESENCE. It does not imply CAUSAL_RELATION.
"""

from __future__ import annotations

from collections.abc import Sequence

from riftlens.analysis.features.fights import segment_fights
from riftlens.coaching.context.grouping import TemporalCluster, cluster_findings_temporally
from riftlens.coaching.context.models import (
    COACHING_EPISODE_SCHEMA_VERSION,
    EPISODE_GROUPING_SEMANTICS,
    EPISODE_PRODUCER,
    EPISODE_PRODUCER_VERSION,
    CoachingEpisode,
    ContextOrigin,
    EpisodeBuilderConfig,
    FactRef,
    FightWindowRef,
    FindingAssociation,
    FindingRef,
    episode_id,
    origin_for_source,
    sanitize_payload,
)
from riftlens.coaching.context.resolution import resolve_conditions
from riftlens.coaching.context.snapshots import build_gaps, build_samples
from riftlens.domain.enums import FactKind, Source
from riftlens.domain.fact import Fact, Provenance
from riftlens.domain.finding import Finding
from riftlens.domain.ports import PatchData
from riftlens.domain.timeline import GameStateTimeline

_EVENT_KINDS = frozenset(
    {
        FactKind.CHAMPION_KILL,
        FactKind.ELITE_MONSTER_KILL,
        FactKind.BUILDING_KILL,
        FactKind.TURRET_PLATE_DESTROYED,
        FactKind.ITEM_PURCHASED,
        FactKind.ITEM_SOLD,
        FactKind.ITEM_DESTROYED,
        FactKind.WARD_PLACED,
        FactKind.WARD_KILL,
        FactKind.LEVEL_UP,
        FactKind.SKILL_LEVEL_UP,
        FactKind.GAME_END,
        FactKind.PAUSE_END,
        FactKind.DERIVED,
    }
)
_SUBJECT_FRAME_KINDS = frozenset(
    {
        FactKind.POSITION,
        FactKind.GOLD,
        FactKind.XP,
        FactKind.LEVEL,
        FactKind.CS,
        FactKind.HEALTH,
        FactKind.DAMAGE_ACCUM,
    }
)
_VISUAL_SOURCES = frozenset({Source.VISUAL, Source.VISUAL_INFERRED, Source.CV})


def build_coaching_episodes(
    gst: GameStateTimeline,
    findings: Sequence[Finding],
    participant_id: int,
    config: EpisodeBuilderConfig | None = None,
    *,
    patch: PatchData | None = None,
) -> list[CoachingEpisode]:
    """Return temporally grouped episodes for ``findings``.

    Assumes GST uses integer game-clock ms. Zero findings yield no episodes.
    Does not persist, narrate, or select coaching items.
    """
    settings = config or EpisodeBuilderConfig()
    if not findings:
        return []
    clusters = cluster_findings_temporally(gst, findings, settings)
    return [
        _build_episode(gst, cluster, participant_id, settings, patch) for cluster in clusters
    ]


def _build_episode(
    gst: GameStateTimeline,
    cluster: TemporalCluster,
    participant_id: int,
    config: EpisodeBuilderConfig,
    patch: PatchData | None,
) -> CoachingEpisode:
    anchors = cluster.anchors
    associated = cluster.associated
    stamps = tuple(sorted({item.t_ms for item in anchors}))
    ident = episode_id(
        gst.match_id,
        participant_id,
        cluster.start_ms,
        cluster.end_ms,
        tuple(item.id for item in anchors),
    )
    members = tuple(sorted((*anchors, *associated), key=lambda item: (item.t_ms, item.id)))
    return CoachingEpisode(
        id=ident,
        schema_version=COACHING_EPISODE_SCHEMA_VERSION,
        match_id=gst.match_id,
        participant_id=participant_id,
        start_ms=cluster.start_ms,
        end_ms=cluster.end_ms,
        phase=gst.phase(anchors[0].t_ms),
        findings=_finding_refs(anchors, associated),
        fact_refs=_select_fact_refs(gst, participant_id, cluster.start_ms, cluster.end_ms),
        samples=build_samples(gst, participant_id, cluster, stamps, patch),
        fights=_fight_refs(gst, cluster.start_ms, cluster.end_ms),
        gaps=build_gaps(gst, participant_id, cluster, stamps, patch),
        resolutions=resolve_conditions(
            gst,
            members,
            participant_id=participant_id,
            window_start_ms=cluster.start_ms,
            window_end_ms=cluster.end_ms,
            config=config,
            patch=patch,
        ),
        provenance=Provenance(
            producer=EPISODE_PRODUCER,
            producer_version=EPISODE_PRODUCER_VERSION,
            upstream=("gst", "findings"),
        ),
        grouping=EPISODE_GROUPING_SEMANTICS,
        anchor_timestamps_ms=stamps,
    )


def _finding_refs(
    anchors: Sequence[Finding], associated: Sequence[Finding]
) -> tuple[FindingRef, ...]:
    rows = [_to_finding_ref(item, FindingAssociation.ANCHOR) for item in anchors]
    rows.extend(
        _to_finding_ref(item, FindingAssociation.TEMPORALLY_ASSOCIATED) for item in associated
    )
    return tuple(sorted(rows, key=lambda item: (item.t_ms, item.finding_id)))


def _to_finding_ref(item: Finding, association: FindingAssociation) -> FindingRef:
    return FindingRef(
        finding_id=item.id,
        association=association,
        rule_id=item.rule_id,
        concept_id=item.concept_id,
        t_ms=item.t_ms,
        t_end_ms=item.t_end_ms,
        suppressed=item.suppressed,
        suppressed_by=item.suppressed_by,
        evidence_labels=tuple(evidence.label for evidence in item.evidence),
    )


def _select_fact_refs(
    gst: GameStateTimeline, pid: int, start_ms: int, end_ms: int
) -> tuple[FactRef, ...]:
    refs: list[FactRef] = []
    for fact in gst.facts(window=(start_ms, end_ms)):
        if fact.source in _VISUAL_SOURCES:
            continue
        if not _keep_fact(fact, pid):
            continue
        refs.append(_to_fact_ref(fact))
    refs.sort(key=lambda item: (item.t_ms, item.kind.value, str(item.subject_id)))
    return tuple(refs)


def _keep_fact(fact: Fact, pid: int) -> bool:
    if fact.kind in _EVENT_KINDS:
        return True
    if fact.kind in _SUBJECT_FRAME_KINDS:
        return fact.subject.kind == "participant" and fact.subject.id == pid
    if fact.kind is FactKind.OBSERVATION:
        return fact.payload.get("omniscient") is False
    return False


def _to_fact_ref(fact: Fact) -> FactRef:
    origin = origin_for_source(fact.source)
    if fact.kind is FactKind.DERIVED:
        origin = ContextOrigin.FEATURE
    return FactRef(
        t_ms=fact.t_ms,
        kind=fact.kind,
        subject_kind=fact.subject.kind,
        subject_id=fact.subject.id,
        source=fact.source,
        confidence=fact.confidence,
        producer=fact.provenance.producer,
        producer_version=fact.provenance.producer_version,
        payload=sanitize_payload(fact.payload),
        origin=origin,
    )


def _fight_refs(gst: GameStateTimeline, start_ms: int, end_ms: int) -> tuple[FightWindowRef, ...]:
    rows: list[FightWindowRef] = []
    for fight in segment_fights(gst):
        if fight.t_end < start_ms or fight.t_start > end_ms:
            continue
        pids = tuple(
            sorted(pid for members in fight.participants_by_team.values() for pid in members)
        )
        rows.append(FightWindowRef(t_start=fight.t_start, t_end=fight.t_end, participant_ids=pids))
    rows.sort(key=lambda item: (item.t_start, item.t_end, item.participant_ids))
    return tuple(rows)
