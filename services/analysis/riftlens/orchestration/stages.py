from __future__ import annotations

import asyncio
import json
import time

from riftlens.adapters.db.repositories import (
    SqlGameplayRepository,
    SqlMatchRepository,
    SqlMediaRepository,
    SqlSyncRepository,
)
from riftlens.adapters.riot.models import MatchDto, TimelineDto
from riftlens.analysis.metrics.registry import compute_metrics
from riftlens.analysis.rules.engine import RuleEngine
from riftlens.analysis.rules.lab import production_rules
from riftlens.analysis.rules.loader import load_rule_pack
from riftlens.analysis.rules.models import RulePack
from riftlens.coaching.causal_tests import causal_test_names, import_causal_tests
from riftlens.coaching.clusterer import cluster_findings
from riftlens.coaching.composer import compose_review
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
from riftlens.coaching.providers.factory import create_provider
from riftlens.coaching.scoring import score_clusters
from riftlens.domain.clock_store import SOURCE_TYPE_ROFL
from riftlens.domain.ports import MediaAssetRecord
from riftlens.domain.sync_map import SyncMap
from riftlens.orchestration.context import StageContext, StageResult, fixture_root
from riftlens.pipeline.assemble.real_match import ensure_match_ingested
from riftlens.pipeline.assemble.review_builder import persist_review_async, review_from_parts
from riftlens.pipeline.ingest_riot.fact_builder import build_game_state_timeline, games_are_paired
from riftlens.pipeline.ingest_riot.persist import content_hash
from riftlens.pipeline.ingest_video.probe import probe
from riftlens.pipeline.sync.errors import AutoSyncError
from riftlens.pipeline.sync.service import AutoSyncService

ALLOWED_FIXTURES = frozenset({"NA1_fixture_a", "NA1_fixture_b", "NA1_fixture_c"})


class BaseStage:
    name: str = ""
    version: str = "1"
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    cacheable: bool = True

    def bound_version(self, ctx: StageContext) -> str:
        """Return the job-overridable version for this stage."""
        return ctx.version_for(self.name)

    def stored_outputs(self, outputs: dict[str, object]) -> dict[str, object]:
        """Return the subset of outputs that may be pickled into the stage cache."""
        return outputs

    def extra_cache_refs(self, ctx: StageContext) -> dict[str, object]:
        """Return extra JSON-safe values mixed into this stage's cache key."""
        del ctx
        return {}

    def restore(self, ctx: StageContext, cached: dict[str, object]) -> None:
        """Rehydrate artifacts from a cache hit. Assumes declared inputs are present."""
        ctx.artifacts.update(cached)

    async def run(self, ctx: StageContext) -> StageResult:
        """Execute the stage. Subclasses must override."""
        del ctx
        raise NotImplementedError(self.name)


class IngestRiotStage(BaseStage):
    name = "ingest_riot"
    inputs = ()
    outputs = ("match", "timeline", "match_hash", "timeline_hash")

    async def run(self, ctx: StageContext) -> StageResult:
        """Load MATCH-V5 + timeline from fixtures or H.2 ingest. Assumes match_id is set."""
        await ctx.tick(self.name, 5, "Loading match")
        match_id = ctx.job.inputs.match_id
        if match_id in ALLOWED_FIXTURES:
            match, timeline = _load_fixture_pair(match_id)
        else:
            ingested = await ensure_match_ingested(
                match_id,
                api_key=ctx.api_key,
                region=ctx.job.inputs.region,
                settings=ctx.settings,
            )
            match, timeline = ingested.match, ingested.timeline
        await ctx.tick(self.name, 100, "Match ready")
        return StageResult(
            outputs={
                "match": match,
                "timeline": timeline,
                "match_hash": content_hash(match.model_dump(by_alias=True)),
                "timeline_hash": content_hash(timeline.model_dump(by_alias=True)),
            },
            message="Match ready",
        )


class IngestVideoStage(BaseStage):
    name = "ingest_video"
    inputs = ()
    outputs = ("media_asset", "video_path", "media_hash")

    async def run(self, ctx: StageContext) -> StageResult:
        """Probe/hash VIDEO media. ROFL assets are skipped. Assumes media_asset_id when run."""
        media_id = ctx.job.inputs.media_asset_id
        if media_id is None:
            return StageResult(outputs={}, skipped=True, message="No VIDEO media")
        await _cooperative_hold(ctx, self.name)
        await ctx.tick(self.name, 20, "Loading media asset")
        asset = await _load_media(ctx, media_id)
        if asset is None:
            raise FileNotFoundError(f"media asset not found: {media_id}")
        if _is_rofl_media(ctx, asset):
            return StageResult(outputs={}, skipped=True, message="ROFL media skipped")
        path = asset.playable_path or asset.original_path
        await ctx.tick(self.name, 40, "Probing video")
        probed = await ctx.pool.run(probe, path, cancel=ctx.cancel)
        await ctx.tick(self.name, 100, "Video ingested")
        return StageResult(
            outputs={
                "media_asset": asset,
                "video_path": path,
                "media_hash": probed.content_hash,
                "video_duration_ms": probed.duration_ms,
            },
            message="Video ingested",
        )


class SynchronizeStage(BaseStage):
    name = "synchronize"
    inputs = ("media_hash", "match_hash")
    outputs = ("sync_map", "sync_quality")

    async def run(self, ctx: StageContext) -> StageResult:
        """Run H.10 VIDEO auto-sync. Never OCR-calibrates ROFL or launches League."""
        if "media_asset" not in ctx.artifacts:
            return StageResult(outputs={}, skipped=True, message="No VIDEO to synchronize")
        await ctx.tick(self.name, 10, "Synchronizing VIDEO")
        service = _sync_service(ctx)
        match: MatchDto = ctx.artifacts["match"]
        duration_s = match.info.game_duration
        match_duration_ms = duration_s * 1000 if duration_s < 100_000 else duration_s
        try:
            outcome = await service.run(
                match_id=ctx.job.inputs.match_id,
                video_path=str(ctx.artifacts.get("video_path") or ""),
                video_duration_ms=int(ctx.artifacts.get("video_duration_ms") or 0) or None,
                match_duration_ms=match_duration_ms or None,
                media_asset_id=ctx.job.inputs.media_asset_id or "",
                content_hash=str(ctx.artifacts.get("media_hash") or ""),
            )
        except AutoSyncError:
            raise
        quality = {
            "verdict": outcome.sync_map.quality.verdict,
            "residual_p95_ms": outcome.sync_map.quality.residual_p95_ms,
            "coverage": outcome.sync_map.quality.coverage,
            "verified": outcome.sync_map.verified,
            "cached": outcome.cached,
        }
        await ctx.tick(self.name, 100, "Sync complete")
        return StageResult(
            outputs={"sync_map": outcome.sync_map, "sync_quality": quality},
            message="Sync complete",
        )


class BuildFactsStage(BaseStage):
    name = "build_facts"
    inputs = ("match_hash", "timeline_hash")
    outputs = ("gst", "fact_count", "paired")

    async def run(self, ctx: StageContext) -> StageResult:
        """Build GST from ingested DTOs. Does not reread Riot JSON in analysis."""
        await ctx.tick(self.name, 10, "Building facts")
        gst = build_game_state_timeline(ctx.artifacts["match"], ctx.artifacts["timeline"])
        paired = games_are_paired(ctx.artifacts["match"], ctx.artifacts["timeline"])
        await ctx.tick(self.name, 100, "Facts ready")
        return StageResult(
            outputs={"gst": gst, "fact_count": len(gst.facts()), "paired": paired},
            message="Facts ready",
        )

    def stored_outputs(self, outputs: dict[str, object]) -> dict[str, object]:
        """GST is rebuilt from cached match+timeline; it is not pickle-safe."""
        return {key: value for key, value in outputs.items() if key != "gst"}

    def restore(self, ctx: StageContext, cached: dict[str, object]) -> None:
        ctx.artifacts.update(cached)
        match = ctx.artifacts["match"]
        timeline = ctx.artifacts["timeline"]
        ctx.artifacts["gst"] = build_game_state_timeline(match, timeline)


class ComputeMetricsStage(BaseStage):
    name = "compute_metrics"
    inputs = ("match_hash", "timeline_hash")
    outputs = ("metrics",)

    async def run(self, ctx: StageContext) -> StageResult:
        """Compute H.5 metrics from GST."""
        await ctx.tick(self.name, 10, "Computing metrics")
        from riftlens.adapters.ddragon.patch_data import PatchDataProvider

        gst = ctx.artifacts["gst"]
        patch = PatchDataProvider()
        patch.load_bundled(gst.patch)
        metrics = compute_metrics(gst, ctx.job.inputs.participant_id, patch)
        await ctx.tick(self.name, 100, "Metrics ready")
        return StageResult(outputs={"metrics": tuple(metrics)}, message="Metrics ready")


class RunRulesStage(BaseStage):
    name = "run_rules"
    inputs = ("match_hash", "timeline_hash")
    outputs = ("findings", "rule_pack_version")

    async def run(self, ctx: StageContext) -> StageResult:
        """Run the H.6/H.7 RuleEngine. Does not select coaching items."""
        await ctx.tick(self.name, 10, "Running rules")
        from riftlens.adapters.ddragon.patch_data import PatchDataProvider

        gst = ctx.artifacts["gst"]
        patch = PatchDataProvider()
        patch.load_bundled(gst.patch)
        pack = _production_pack()
        findings = RuleEngine(pack, patch=patch).run(gst, ctx.job.inputs.participant_id)
        await ctx.tick(self.name, 100, "Rules complete")
        return StageResult(
            outputs={"findings": tuple(findings), "rule_pack_version": pack.version},
            message="Rules complete",
        )


class PrioritizeStage(BaseStage):
    name = "prioritize"
    inputs = ("match_hash", "timeline_hash")
    outputs = ("review",)

    async def run(self, ctx: StageContext) -> StageResult:
        """Deterministic H.8 clustering and CoachingItem templates. LLM does not run here."""
        await ctx.tick(self.name, 10, "Prioritizing")
        import_causal_tests()
        scoring = load_scoring()
        graph = load_causal_graph()
        validate_causal_tests(graph, sorted(causal_test_names()))
        ranks = load_rank_relevance(unranked_treats_as=scoring.unranked_treats_as)
        taxonomy = load_taxonomy_index()
        checks = load_checks()
        findings = ctx.artifacts["findings"]
        clustered = cluster_findings(
            findings, graph=graph, taxonomy=taxonomy, ranks=ranks, scoring=scoring
        )
        scored = score_clusters(
            clustered.clusters,
            rank=ctx.job.inputs.rank,
            scoring=scoring,
            ranks=ranks,
            taxonomy=taxonomy,
        )
        picked = prioritize(scored, rank=ctx.job.inputs.rank, scoring=scoring, ranks=ranks)
        focus = coaching_items_from_clusters(
            picked.focus,
            checks=checks,
            scoring=scoring,
            is_focus=True,
            is_strength=False,
            rank_start=1,
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
        review = review_from_parts(
            gst=ctx.artifacts["gst"],
            pid=ctx.job.inputs.participant_id,
            rank=ctx.job.inputs.rank,
            findings=tuple(findings),
            metrics=ctx.artifacts["metrics"],
            focus=tuple(focus),
            secondary=tuple(secondary),
            strengths=tuple(strengths),
            clusters=tuple(scored),
            grouping_log=clustered.grouping_log,
            match=ctx.artifacts["match"],
            timeline=ctx.artifacts["timeline"],
            llm_provider=ctx.job.inputs.llm_provider,
            rule_pack_version=str(ctx.artifacts.get("rule_pack_version") or ""),
        )
        await ctx.tick(self.name, 100, "Coaching items selected")
        return StageResult(outputs={"review": review}, message="Coaching items selected")


class ComposeCoachingStage(BaseStage):
    name = "compose_coaching"
    inputs = ("match_hash", "timeline_hash")
    outputs = ("review", "llm_fallback", "llm_model")

    def extra_cache_refs(self, ctx: StageContext) -> dict[str, object]:
        from riftlens.coaching.composer import PROMPT_VERSION

        return {
            "llm_provider": ctx.job.inputs.llm_provider,
            "llm_model": ctx.job.inputs.llm_model,
            "prompt_version": PROMPT_VERSION,
        }

    async def run(self, ctx: StageContext) -> StageResult:
        """Narrate H.8 items from EvidenceBundle. Null provider keeps template prose."""
        await ctx.tick(self.name, 10, "Composing coaching")
        provider = create_provider(
            ctx.job.inputs.llm_provider,
            model=ctx.job.inputs.llm_model,
            settings=ctx.settings,
        )
        cache_dir = ctx.settings.cache_dir / "llm"
        composed = await compose_review(
            ctx.artifacts["review"],
            ctx.artifacts["gst"],
            provider,
            cache_dir=cache_dir,
        )
        await ctx.tick(self.name, 100, "Narration complete")
        return StageResult(
            outputs={
                "review": composed.review,
                "llm_fallback": composed.llm_fallback,
                "llm_model": provider.model,
            },
            message="Narration complete",
        )


class PersistStage(BaseStage):
    name = "persist"
    inputs = ()
    outputs = ("review_id",)
    cacheable = False

    async def run(self, ctx: StageContext) -> StageResult:
        """Persist the Review and presentation JSON. Assumes compose already ran."""
        await ctx.tick(self.name, 10, "Saving review")
        review = ctx.artifacts["review"]
        sync_map = ctx.artifacts.get("sync_map")
        saved = await persist_review_async(
            review,
            ctx.artifacts["gst"],
            ctx.artifacts["metrics"],
            ctx.artifacts.get("match"),
            ctx.artifacts.get("timeline"),
            ctx.settings,
            sync_map=sync_map if isinstance(sync_map, SyncMap) else None,
        )
        await ctx.tick(self.name, 100, "Review saved")
        return StageResult(outputs={"review": saved, "review_id": saved.id}, message="Review saved")


def default_stages() -> list[BaseStage]:
    """Return the H.11 stage list in DAG order."""
    return [
        IngestRiotStage(),
        IngestVideoStage(),
        SynchronizeStage(),
        BuildFactsStage(),
        ComputeMetricsStage(),
        RunRulesStage(),
        PrioritizeStage(),
        ComposeCoachingStage(),
        PersistStage(),
    ]


def _production_pack() -> RulePack:
    pack = load_rule_pack()
    return RulePack(production_rules(pack), tuple(pack.concept_ids))


def _load_fixture_pair(match_id: str) -> tuple[MatchDto, TimelineDto]:
    folder = fixture_root() / match_id
    match = MatchDto.model_validate(json.loads((folder / "match.json").read_text(encoding="utf-8")))
    timeline = TimelineDto.model_validate(
        json.loads((folder / "timeline.json").read_text(encoding="utf-8"))
    )
    return match, timeline


async def _load_media(ctx: StageContext, media_id: str) -> MediaAssetRecord | None:
    if ctx.session_factory is None:
        return None
    return await SqlMediaRepository(ctx.session_factory).get_asset(media_id)


def _is_rofl_media(ctx: StageContext, asset: MediaAssetRecord) -> bool:
    if asset.source_kind.lower() == SOURCE_TYPE_ROFL:
        return True
    if ctx.session_factory is None:
        return False
    return False


def _sync_service(ctx: StageContext) -> AutoSyncService:
    if ctx.session_factory is None:
        return AutoSyncService()
    return AutoSyncService(
        syncs=SqlSyncRepository(ctx.session_factory),
        media=SqlMediaRepository(ctx.session_factory),
        matches=SqlMatchRepository(ctx.session_factory),
        gameplay=SqlGameplayRepository(ctx.session_factory),
    )


async def _cooperative_hold(ctx: StageContext, stage: str) -> None:
    hold_ms = int(getattr(ctx.settings, "ingest_video_hold_ms", 0) or 0)
    if hold_ms <= 0:
        return
    started = time.monotonic()
    while (time.monotonic() - started) * 1000.0 < hold_ms:
        ctx.cancel.raise_if_set()
        elapsed = (time.monotonic() - started) * 1000.0
        pct = min(90, int(100 * elapsed / hold_ms))
        await ctx.tick(stage, max(5, pct), "Ingesting video")
        await asyncio.sleep(0.05)
