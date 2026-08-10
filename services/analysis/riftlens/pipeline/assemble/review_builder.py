from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from riftlens import __version__
from riftlens.adapters.db.engine import init_database, make_session_factory
from riftlens.adapters.db.repositories import (
    SqlCoachingRepository,
    SqlFindingRepository,
    SqlMatchRepository,
    SqlMetricRepository,
    SqlPlayerRepository,
    SqlReviewRepository,
)
from riftlens.adapters.ddragon.patch_data import PatchDataProvider
from riftlens.adapters.riot.models import MatchDto, TimelineDto
from riftlens.analysis.metrics.base import MetricValue
from riftlens.analysis.metrics.registry import compute_metrics, persist_metrics
from riftlens.analysis.rules.engine import RuleEngine, persist_findings
from riftlens.analysis.rules.lab import production_rules
from riftlens.analysis.rules.loader import load_rule_pack
from riftlens.analysis.rules.models import RulePack
from riftlens.coaching.causal_tests import causal_test_names, import_causal_tests
from riftlens.coaching.clusterer import cluster_findings
from riftlens.coaching.data import (
    load_causal_graph,
    load_checks,
    load_rank_relevance,
    load_scoring,
    load_taxonomy_index,
    validate_causal_tests,
)
from riftlens.coaching.items import coaching_items_from_clusters
from riftlens.coaching.prioritizer import prioritize
from riftlens.coaching.scoring import score_clusters
from riftlens.config import Settings, get_settings
from riftlens.domain.enums import GamePhase
from riftlens.domain.ids import new_ulid
from riftlens.domain.ports import (
    CoachingItemRecord,
    FocusCommitmentRecord,
    PlayerRecord,
    ReviewRecord,
)
from riftlens.domain.review import CoachingItem, MetricSnapshot, Review
from riftlens.domain.timeline import GameStateTimeline
from riftlens.pipeline.ingest_riot.fact_builder import build_game_state_timeline, games_are_paired
from riftlens.pipeline.ingest_riot.persist import persist_riot_match

_LOCAL_PLAYER_FILE = "local_player_id"


@dataclass(frozen=True)
class ReviewBuildResult:
    review: Review
    gst: GameStateTimeline
    paired: bool


def build_review(
    gst: GameStateTimeline,
    pid: int,
    *,
    rank: str = "UNRANKED",
    llm_provider: str = "null",
    match: MatchDto | None = None,
    timeline: TimelineDto | None = None,
    persist: bool = True,
    settings: Settings | None = None,
    player_id: str | None = None,
) -> ReviewBuildResult:
    """Assemble a deterministic Review from GST + H.7 findings. Assumes GST is complete."""
    import_causal_tests()
    scoring = load_scoring()
    graph = load_causal_graph()
    validate_causal_tests(graph, sorted(causal_test_names()))
    ranks = load_rank_relevance(unranked_treats_as=scoring.unranked_treats_as)
    taxonomy = load_taxonomy_index()
    checks = load_checks()
    patch = PatchDataProvider()
    patch.load_bundled(gst.patch)
    pack = _production_pack()
    findings = RuleEngine(pack, patch=patch).run(gst, pid)
    metrics = compute_metrics(gst, pid, patch)
    clustered = cluster_findings(
        findings, graph=graph, taxonomy=taxonomy, ranks=ranks, scoring=scoring
    )
    scored = score_clusters(
        clustered.clusters, rank=rank, scoring=scoring, ranks=ranks, taxonomy=taxonomy
    )
    picked = prioritize(scored, rank=rank, scoring=scoring, ranks=ranks)
    focus = coaching_items_from_clusters(
        picked.focus, checks=checks, scoring=scoring, is_focus=True, is_strength=False, rank_start=1
    )
    secondary = coaching_items_from_clusters(
        picked.secondary,
        checks=checks,
        scoring=scoring,
        is_focus=False,
        is_strength=False,
        rank_start=len(focus) + 1,
    )
    strengths = coaching_items_from_clusters(
        picked.strengths,
        checks=checks,
        scoring=scoring,
        is_focus=False,
        is_strength=True,
        rank_start=len(focus) + len(secondary) + 1,
    )
    info = gst.participants[pid]
    result = _match_result(gst, pid, match)
    now_ms = int(time.time() * 1000)
    review = Review(
        id=new_ulid(),
        player_id=player_id or "",
        match_id=gst.match_id,
        participant_id=pid,
        champion=info.champion,
        role=info.role,
        rank=rank,
        patch=gst.patch,
        duration_ms=gst.duration_ms,
        result=result,
        rule_pack_version=pack.version,
        engine_version=__version__,
        llm_provider=llm_provider,
        status="COMPLETE",
        summary_text=_summary_text(focus, strengths),
        findings=tuple(findings),
        clusters=tuple(scored),
        grouping_log=clustered.grouping_log,
        focus_items=tuple(focus),
        secondary_items=tuple(secondary),
        strengths=tuple(strengths),
        metrics=tuple(_metric_snapshot(item) for item in metrics),
        created_at=now_ms,
        completed_at=now_ms,
        unpaired_match_timeline=_unpaired(match, timeline),
        overall_scores=_domain_scores(scored),
    )
    paired = not _unpaired(match, timeline)
    if persist:
        resolved = settings or get_settings()
        review = _persist_review(review, gst, metrics, match, timeline, resolved)
    return ReviewBuildResult(review=review, gst=gst, paired=paired)


def build_review_from_dtos(
    match: MatchDto,
    timeline: TimelineDto,
    pid: int,
    *,
    rank: str = "UNRANKED",
    llm_provider: str = "null",
    persist: bool = True,
    settings: Settings | None = None,
) -> ReviewBuildResult:
    """Build a GST then a Review. Assumes DTOs are already loaded (no network)."""
    gst = build_game_state_timeline(match, timeline)
    return build_review(
        gst,
        pid,
        rank=rank,
        llm_provider=llm_provider,
        match=match,
        timeline=timeline,
        persist=persist,
        settings=settings,
    )


def _unpaired(match: MatchDto | None, timeline: TimelineDto | None) -> bool:
    if match is None or timeline is None:
        return False
    return not games_are_paired(match, timeline)


def _production_pack() -> RulePack:
    pack = load_rule_pack()
    return RulePack(production_rules(pack), tuple(pack.concept_ids))


def _metric_snapshot(value: MetricValue) -> MetricSnapshot:
    if isinstance(value.phase, GamePhase):
        phase: str | None = value.phase.value
    elif value.phase is None:
        phase = None
    else:
        phase = str(value.phase)
    return MetricSnapshot(
        metric_id=value.metric_id,
        value=value.value,
        unit=value.unit,
        phase=str(phase) if phase is not None else None,
        confidence=value.confidence,
        baseline_percentile=value.baseline_percentile,
        sample_context=value.sample_context,
        detail=dict(value.detail),
    )


def _match_result(gst: GameStateTimeline, pid: int, match: MatchDto | None) -> str | None:
    del gst
    if match is None:
        return None
    for participant in match.info.participants:
        if participant.participant_id == pid:
            return "WIN" if participant.win else "LOSS"
    return None


def _summary_text(focus: Sequence[CoachingItem], strengths: Sequence[CoachingItem]) -> str:
    titles = [item.title for item in focus]
    keeps = [item.title for item in strengths]
    focus_bit = "; ".join(titles) if titles else "no focus items"
    keep_bit = "; ".join(keeps) if keeps else "no strengths detected"
    return f"Focus: {focus_bit}. Keep: {keep_bit}."


def _domain_scores(clusters: Sequence[object]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for cluster in clusters:
        domain = getattr(cluster, "domain", None)
        impact = float(getattr(cluster, "impact_score", 0.0))
        if isinstance(domain, str):
            totals[domain] = totals.get(domain, 0.0) + impact
    return totals


def _persist_review(
    review: Review,
    gst: GameStateTimeline,
    metrics: Sequence[MetricValue],
    match: MatchDto | None,
    timeline: TimelineDto | None,
    settings: Settings,
) -> Review:
    del gst
    import asyncio

    engine = init_database(settings)
    factory = make_session_factory(engine)
    players = SqlPlayerRepository(factory)
    matches = SqlMatchRepository(factory)
    reviews = SqlReviewRepository(factory)
    findings_repo = SqlFindingRepository(factory)
    metric_repo = SqlMetricRepository(factory)
    coaching = SqlCoachingRepository(factory)

    async def work() -> Review:
        player_id = review.player_id or await _ensure_local_player(settings, players)
        if match is not None and timeline is not None:
            await persist_riot_match(matches, match, timeline, now_ms=review.created_at)
        updated = _with_player(review, player_id)
        await reviews.upsert(_review_record(updated))
        await persist_findings(findings_repo, updated.id, updated.findings)
        await persist_metrics(metric_repo, updated.id, metrics)
        await coaching.replace_for_review(
            updated.id, [_coaching_record(updated.id, item) for item in _all_items(updated)]
        )
        for item in updated.focus_items:
            await coaching.upsert_focus_commitment(_commitment(updated, item, player_id))
        from riftlens.pipeline.assemble.review_presentation import (
            review_to_presentation,
            save_review_presentation,
        )

        save_review_presentation(settings.data_dir, review_to_presentation(updated))
        return updated

    return asyncio.run(work())


def _commitment(review: Review, item: CoachingItem, player_id: str) -> FocusCommitmentRecord:
    return FocusCommitmentRecord(
        id=new_ulid(),
        player_id=player_id,
        review_id=review.id,
        concept_id=item.root_concept_id,
        metric_id=None,
        target_value=None,
        comparison=None,
        created_at=review.created_at,
        resolved_review_id=None,
        outcome=None,
    )


def _with_player(review: Review, player_id: str) -> Review:
    return Review(
        id=review.id,
        player_id=player_id,
        match_id=review.match_id,
        participant_id=review.participant_id,
        champion=review.champion,
        role=review.role,
        rank=review.rank,
        patch=review.patch,
        duration_ms=review.duration_ms,
        result=review.result,
        rule_pack_version=review.rule_pack_version,
        engine_version=review.engine_version,
        llm_provider=review.llm_provider,
        status=review.status,
        summary_text=review.summary_text,
        findings=review.findings,
        clusters=review.clusters,
        grouping_log=review.grouping_log,
        focus_items=review.focus_items,
        secondary_items=review.secondary_items,
        strengths=review.strengths,
        metrics=review.metrics,
        created_at=review.created_at,
        completed_at=review.completed_at,
        unpaired_match_timeline=review.unpaired_match_timeline,
        overall_scores=review.overall_scores,
    )


def _all_items(review: Review) -> list[CoachingItem]:
    return [*review.focus_items, *review.secondary_items, *review.strengths]


def _review_record(review: Review) -> ReviewRecord:
    return ReviewRecord(
        id=review.id,
        player_id=review.player_id,
        match_id=review.match_id,
        participant_id=review.participant_id,
        media_asset_id=None,
        sync_map_id=None,
        rule_pack_version=review.rule_pack_version,
        engine_version=review.engine_version,
        analysis_tiers=json.dumps(["RIOT", "DERIVED"]),
        status=review.status,
        summary_text=review.summary_text,
        overall_scores=json.dumps(dict(review.overall_scores or {})),
        llm_provider=review.llm_provider,
        llm_model=None,
        llm_prompt_version=None,
        created_at=review.created_at,
        completed_at=review.completed_at,
    )


def _coaching_record(review_id: str, item: CoachingItem) -> CoachingItemRecord:
    return CoachingItemRecord(
        id=item.id,
        review_id=review_id,
        root_concept_id=item.root_concept_id,
        rank=item.rank,
        is_focus=1 if item.is_focus else 0,
        is_strength=1 if item.is_strength else 0,
        issue_type=item.issue_type.value,
        impact_score=item.impact_score,
        gold_equivalent=item.gold_equivalent,
        occurrences=item.occurrences,
        confidence=item.confidence,
        title=item.title,
        body=item.body,
        the_fix=item.the_fix,
        next_game_check=item.next_game_check,
        exemplar_finding_id=item.exemplar_finding_id,
        finding_ids=item.finding_ids,
    )


async def _ensure_local_player(settings: Settings, players: SqlPlayerRepository) -> str:
    path = Path(settings.data_dir) / _LOCAL_PLAYER_FILE
    player_id = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    if not player_id:
        player_id = new_ulid()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(player_id + "\n", encoding="utf-8")
    await players.upsert_player(
        PlayerRecord(
            id=player_id,
            display_name="local",
            is_local_user=1,
            created_at=int(time.time() * 1000),
        )
    )
    return player_id
