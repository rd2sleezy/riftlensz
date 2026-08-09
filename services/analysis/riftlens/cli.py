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


def main() -> None:
    """CLI entrypoint. Assumes invocation via python -m riftlens.cli."""
    app()


if __name__ == "__main__":
    main()
