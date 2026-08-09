from __future__ import annotations

import asyncio
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import structlog
import typer

from riftlens.adapters.ddragon.patch_data import PatchDataProvider
from riftlens.adapters.riot.cache import RiotCache
from riftlens.adapters.riot.client import RiotClient
from riftlens.adapters.riot.models import MatchDto, TimelineDto
from riftlens.adapters.riot.rate_limiter import RiotRateLimiter
from riftlens.analysis.metrics.base import MetricValue
from riftlens.analysis.metrics.registry import compute_metrics
from riftlens.analysis.rules.engine import RuleEngine
from riftlens.analysis.rules.loader import load_rule_pack
from riftlens.config import get_settings
from riftlens.domain.enums import FactKind, GamePhase
from riftlens.domain.fact import SubjectRef
from riftlens.domain.geometry import Point, zone_of
from riftlens.domain.timeline import GameStateTimeline
from riftlens.logging import configure_logging
from riftlens.pipeline.ingest_riot.fact_builder import build_game_state_timeline, games_are_paired

app = typer.Typer(add_completion=False, no_args_is_help=True)
riot_app = typer.Typer(add_completion=False, no_args_is_help=True)
app.add_typer(riot_app, name="riot")

log = structlog.get_logger("riftlens.cli")
_FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "riot"


@riot_app.command("fetch-match")
def fetch_match(
    match_id: str,
    region: str = typer.Option("americas", "--region"),
) -> None:
    """Download and permanently cache a MATCH-V5 game. Assumes RIFTLENS_RIOT_API_KEY is set."""
    configure_logging()
    asyncio.run(_fetch_match(match_id=match_id, region=region))


async def _fetch_match(*, match_id: str, region: str) -> None:
    settings = get_settings()
    if not settings.riot_api_key:
        raise typer.BadParameter("RIFTLENS_RIOT_API_KEY is not set")
    cache = RiotCache(settings.cache_dir)
    client = RiotClient(
        api_key=settings.riot_api_key,
        cache=cache,
        limiter=RiotRateLimiter(),
    )
    try:
        match = await client.get_match(match_id, region)
        timeline = await client.get_timeline(match_id, region)
    finally:
        await client.aclose()
    log.info(
        "fetch_match_done",
        match_id=match.metadata.match_id,
        queue_id=match.info.queue_id,
        frames=len(timeline.info.frames),
        cache_dir=str(settings.cache_dir),
    )


@app.command("metrics")
def dump_metrics(
    match_id: str,
    pid: Annotated[int, typer.Option("--pid", help="Participant id to score.")],
    fixtures: Annotated[
        Path | None, typer.Option("--fixtures", help="Directory of NA1_fixture_* folders.")
    ] = None,
) -> None:
    """Print H.5 metrics for a local fixture. Assumes GST is built without network."""
    configure_logging()
    match, timeline = _load_fixture_pair(match_id, fixtures)
    gst = build_game_state_timeline(match, timeline)
    patch = PatchDataProvider()
    patch.load_bundled(gst.patch)
    values = compute_metrics(gst, pid, patch)
    _print_metrics_table(gst, pid, values, paired=games_are_paired(match, timeline))


@app.command("rules")
def dump_rules(
    match_id: str,
    pid: Annotated[int, typer.Option("--pid", help="Participant id to evaluate.")],
    fixtures: Annotated[
        Path | None, typer.Option("--fixtures", help="Directory of NA1_fixture_* folders.")
    ] = None,
) -> None:
    """Print H.6 rule findings for a local fixture. Assumes GST is built without network."""
    configure_logging()
    match, timeline = _load_fixture_pair(match_id, fixtures)
    gst = build_game_state_timeline(match, timeline)
    patch = PatchDataProvider()
    patch.load_bundled(gst.patch)
    pack = load_rule_pack()
    findings = RuleEngine(pack, patch=patch).run(gst, pid)
    _print_findings(gst, pid, findings, paired=games_are_paired(match, timeline))


@app.command("review")
def dump_review(
    match_id: str,
    pid: Annotated[int, typer.Option("--pid", help="Participant id to coach.")],
    fixtures: Annotated[
        Path | None, typer.Option("--fixtures", help="Directory of NA1_fixture_* folders.")
    ] = None,
    rank: Annotated[
        str, typer.Option("--rank", help="Rank tier for relevance curves.")
    ] = "UNRANKED",
    no_llm: Annotated[
        bool, typer.Option("--no-llm", help="Use Jinja templates only (H.8 default).")
    ] = False,
    persist: Annotated[
        bool, typer.Option("--persist/--no-persist", help="Write the Review to the local DB.")
    ] = True,
) -> None:
    """Print a deterministic H.8 coaching review. Assumes GST is built without network."""
    del no_llm  # H.11 LLM narration is not in scope; templates are always used.
    configure_logging()
    match, timeline = _load_fixture_pair(match_id, fixtures)
    from riftlens.pipeline.assemble.review_builder import build_review_from_dtos

    result = build_review_from_dtos(
        match,
        timeline,
        pid,
        rank=rank,
        llm_provider="null",
        persist=persist,
    )
    _print_review(result.review, paired=result.paired)


@app.command("gst")
def dump_gst(
    match_id: str,
    pid: Annotated[int, typer.Option("--pid", help="Participant id to tabulate.")],
    fixtures: Annotated[
        Path | None, typer.Option("--fixtures", help="Directory of NA1_fixture_* folders.")
    ] = None,
) -> None:
    """Print a GameStateTimeline summary for a local fixture match. Assumes no network."""
    configure_logging()
    match, timeline = _load_fixture_pair(match_id, fixtures)
    gst = build_game_state_timeline(match, timeline)
    _print_participant_summary(gst)
    _print_fact_histogram(gst)
    _print_per_minute_table(gst, pid)


def _load_fixture_pair(match_id: str, fixtures: Path | None) -> tuple[MatchDto, TimelineDto]:
    """Return MatchDto+TimelineDto for ``match_id``. Assumes a local fixture folder exists."""
    root = fixtures if fixtures is not None else _FIXTURE_ROOT
    folder = root / match_id
    if not folder.is_dir():
        raise typer.BadParameter(f"fixture folder not found: {folder}")
    match_path = folder / "match.json"
    timeline_path = folder / "timeline.json"
    match = MatchDto.model_validate(json.loads(match_path.read_text(encoding="utf-8")))
    timeline = TimelineDto.model_validate(json.loads(timeline_path.read_text(encoding="utf-8")))
    return match, timeline


def _print_participant_summary(gst: GameStateTimeline) -> None:
    print(
        f"match_id={gst.match_id} patch={gst.patch} "
        f"queue_id={gst.queue_id} duration_ms={gst.duration_ms}"
    )
    print("pid  champion        role      team  opponent  puuid")
    for pid, info in sorted(gst.participants.items()):
        opponent = gst.lane_opponent(pid)
        print(
            f"{pid:<4} {info.champion:<15} {info.role.value:<9} {info.team.name:<5} "
            f"{str(opponent):<9} {info.puuid[:20]}"
        )


def _print_fact_histogram(gst: GameStateTimeline) -> None:
    counts: Counter[str] = Counter(fact.kind.value for fact in gst.facts())
    print("\nfact counts")
    for kind, count in sorted(counts.items()):
        print(f"  {kind:<24} {count}")
    print(f"  {'TOTAL':<24} {sum(counts.values())}")


def _print_per_minute_table(gst: GameStateTimeline, pid: int) -> None:
    print(f"\nper-minute state pid={pid}")
    print(f"{'t':<10} {'mm:ss':<8} {'zone':<20} {'gold':<8} {'cs':<6} {'lvl':<5} {'hp%':<8}")
    subject = SubjectRef(kind="participant", id=pid)
    frame_times = sorted({fact.t_ms for fact in gst.facts(kind=FactKind.GOLD, subject=subject)})
    for t_ms in frame_times:
        snap = gst.at(t_ms)
        participant = snap.participants[pid]
        zone = "UNKNOWN"
        if participant.position is not None:
            zone = zone_of(Point(participant.position.value.x, participant.position.value.y)).value
        gold = participant.gold.value if participant.gold else "-"
        cs = participant.cs.value if participant.cs else "-"
        level = participant.level.value if participant.level else "-"
        hp_pct: str | float = "-"
        health = participant.health
        health_max = participant.health_max
        if health is not None and health_max is not None and health_max.value:
            hp_pct = round(100.0 * health.value / health_max.value, 1)
        minutes, seconds = divmod(t_ms // 1000, 60)
        clock = f"{minutes:02d}:{seconds:02d}"
        print(f"{t_ms:<10} {clock:<8} {zone:<20} {gold:<8} {cs:<6} {level:<5} {hp_pct}")


def _print_metrics_table(
    gst: GameStateTimeline,
    pid: int,
    values: Sequence[MetricValue],
    *,
    paired: bool,
) -> None:
    info = gst.participants.get(pid)
    champ = info.champion if info else "?"
    role = info.role.value if info else "?"
    print(f"match_id={gst.match_id} pid={pid} champion={champ} role={role} patch={gst.patch}")
    if not paired:
        print(
            "NOTE: match.json and timeline.json are unpaired games. "
            "Metrics are computed from the GameStateTimeline (timeline-grounded) only."
        )
    print()
    header = (
        f"{'metric':<6} {'phase':<16} {'value':>10} {'unit':<16} {'conf':>5} {'pctl':>6}  context"
    )
    print(header)
    print("-" * len(header))
    for raw in values:
        if isinstance(raw.phase, GamePhase):
            phase_label = raw.phase.value
        elif raw.phase is None:
            phase_label = "-"
        else:
            phase_label = str(raw.phase)
        pctl = "-" if raw.baseline_percentile is None else f"{raw.baseline_percentile:5.1f}"
        print(
            f"{raw.metric_id:<6} {phase_label:<16} {raw.value:10.3f} {raw.unit:<16} "
            f"{raw.confidence:5.2f} {pctl:>6}  {raw.sample_context}"
        )


def _print_findings(
    gst: GameStateTimeline,
    pid: int,
    findings: Sequence[object],
    *,
    paired: bool,
) -> None:
    from riftlens.domain.finding import Finding

    info = gst.participants.get(pid)
    champ = info.champion if info else "?"
    role = info.role.value if info else "?"
    print(f"match_id={gst.match_id} pid={pid} champion={champ} role={role} patch={gst.patch}")
    if not paired:
        print(
            "NOTE: match.json and timeline.json are unpaired games. "
            "Findings are computed from the GameStateTimeline only."
        )
    print(f"findings={len(findings)}")
    print()
    for raw in findings:
        if not isinstance(raw, Finding):
            continue
        minutes, seconds = divmod(raw.t_ms // 1000, 60)
        clock = f"{minutes:02d}:{seconds:02d}"
        flag = " suppressed" if raw.suppressed else ""
        print(
            f"{raw.rule_id} v{raw.rule_version} {clock} {raw.severity.value} "
            f"conf={raw.confidence:.2f}{flag}  {raw.title}"
        )
        print(f"  concept={raw.concept_id} suppressed_by={raw.suppressed_by}")
        for item in raw.evidence:
            print(f"  evidence[{item.kind.value}] {item.label}: {item.value}")


def _print_review(review: object, *, paired: bool) -> None:
    from riftlens.domain.review import Review

    if not isinstance(review, Review):
        raise TypeError("expected a Review")
    print(
        f"match_id={review.match_id} pid={review.participant_id} "
        f"champion={review.champion} role={review.role.value} rank={review.rank} "
        f"patch={review.patch} duration_ms={review.duration_ms} result={review.result}"
    )
    print(f"llm_provider={review.llm_provider} engine={review.engine_version}")
    if not paired or review.unpaired_match_timeline:
        print(
            "NOTE: match.json and timeline.json are unpaired games. "
            "Review is computed from the GameStateTimeline only. "
            "Do not treat this fixture dump as a paired match+timeline validation."
        )
    print(f"findings={len(review.findings)} clusters={len(review.clusters)}")
    print()
    print("FOCUS")
    for item in review.focus_items:
        _print_coaching_item(item)
    print("SECONDARY")
    if not review.secondary_items:
        print("  (none)")
    for item in review.secondary_items:
        _print_coaching_item(item)
    print("STRENGTHS")
    if not review.strengths:
        print("  (none)")
    for item in review.strengths:
        _print_coaching_item(item)
    print("METRICS")
    header = (
        f"{'metric':<6} {'phase':<16} {'value':>10} {'unit':<16} "
        f"{'conf':>5} {'pctl':>6}  context"
    )
    print(header)
    print("-" * len(header))
    for metric in review.metrics:
        pctl = "-" if metric.baseline_percentile is None else f"{metric.baseline_percentile:5.1f}"
        phase = metric.phase or "-"
        print(
            f"{metric.metric_id:<6} {phase:<16} {metric.value:10.3f} {metric.unit:<16} "
            f"{metric.confidence:5.2f} {pctl:>6}  {metric.sample_context}"
        )


def _print_coaching_item(item: object) -> None:
    from riftlens.domain.review import CoachingItem, format_mmss

    if not isinstance(item, CoachingItem):
        return
    clocks = ", ".join(format_mmss(stamp) for stamp in item.evidence_timestamps_ms) or "-"
    kind = "FOCUS" if item.is_focus else ("STRENGTH" if item.is_strength else "SECONDARY")
    print(f"{item.rank}. [{kind}] {item.title}")
    print(f"   type={item.issue_type.value} cost={item.cost_summary} conf={item.confidence:.2f}")
    print(f"   why: {item.body.replace(chr(10), ' / ')}")
    print(f"   fix: {item.the_fix}")
    print(f"   check: {item.next_game_check}")
    print(f"   evidence_t={clocks} (ms={list(item.evidence_timestamps_ms)})")
    print(f"   grouping: {item.grouping_reason}")
    print(f"   findings={list(item.finding_ids)}")
    print()


def main() -> None:
    """CLI entrypoint. Assumes invocation via python -m riftlens.cli."""
    app()


if __name__ == "__main__":
    main()
