from __future__ import annotations

import json
import random
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from riftlens.adapters.ddragon.patch_data import PatchDataProvider
from riftlens.adapters.riot.cache import RiotCache
from riftlens.adapters.riot.models import MatchDto, TimelineDto
from riftlens.analysis.rules.engine import RuleEngine
from riftlens.analysis.rules.loader import load_rule_pack
from riftlens.analysis.rules.models import RuleDefinition, RulePack
from riftlens.config import get_settings
from riftlens.domain.finding import Finding
from riftlens.domain.timeline import GameStateTimeline
from riftlens.pipeline.ingest_riot.fact_builder import build_game_state_timeline, games_are_paired

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "riot"


@dataclass(frozen=True)
class MatchCase:
    match_id: str
    gst: GameStateTimeline
    pid: int
    source: str


@dataclass(frozen=True)
class RuleLabReport:
    rule_id: str
    matches: int
    firing_matches: int
    fire_rate: float
    findings_per_firing_match: float
    severity_hist: dict[str, int]
    confidence_hist: dict[str, int]
    samples: tuple[Finding, ...]
    source_note: str


def production_rules(pack: RulePack) -> list[RuleDefinition]:
    """Return R-001..R-020 and P-001..P-005. Test throwaways are excluded."""
    return [
        rule
        for rule in pack.rules
        if rule.id.startswith(("R-0", "P-0")) and rule.id != "R-000"
    ]


def run_rule_lab(
    rule_id: str,
    cases: Sequence[MatchCase],
    *,
    sample_n: int = 10,
    seed: int = 7,
) -> RuleLabReport:
    """Evaluate one rule on ``cases`` and return fire-rate statistics."""
    pack = load_rule_pack()
    rule = next(item for item in pack.rules if item.id == rule_id)
    scoped = RulePack([rule], list(pack.concept_ids))
    by_match: list[list[Finding]] = []
    all_findings: list[Finding] = []
    for case in cases:
        patch = PatchDataProvider()
        patch.load_bundled(case.gst.patch)
        found = RuleEngine(scoped, patch=patch).run(case.gst, case.pid)
        by_match.append(found)
        all_findings.extend(found)
    firing = [rows for rows in by_match if rows]
    n = len(cases) or 1
    fire_rate = 100.0 * len(firing) / n
    per = (sum(len(rows) for rows in firing) / len(firing)) if firing else 0.0
    sev = Counter(item.severity.value for item in all_findings)
    conf = Counter(_conf_bucket(item.confidence) for item in all_findings)
    rng = random.Random(seed)
    samples = (
        tuple(rng.sample(all_findings, k=min(sample_n, len(all_findings)))) if all_findings else ()
    )
    sources = sorted({case.source for case in cases})
    return RuleLabReport(
        rule_id=rule_id,
        matches=len(cases),
        firing_matches=len(firing),
        fire_rate=fire_rate,
        findings_per_firing_match=per,
        severity_hist=dict(sev),
        confidence_hist=dict(conf),
        samples=samples,
        source_note=", ".join(sources),
    )


def format_report(report: RuleLabReport) -> str:
    """Return a printable rule_lab report. Assumes histograms use severity/confidence labels."""
    lines = [
        f"rule {report.rule_id}",
        f"corpus {report.matches} matches ({report.source_note})",
        f"fire rate {report.fire_rate:.1f}% ({report.firing_matches}/{report.matches})",
        f"findings per firing match {report.findings_per_firing_match:.2f}",
        f"severity {report.severity_hist}",
        f"confidence {report.confidence_hist}",
        "",
        "sample findings:",
    ]
    if not report.samples:
        lines.append("  (none)")
        return "\n".join(lines) + "\n"
    for finding in report.samples:
        lines.append(
            f"  {finding.rule_id} t={finding.t_ms} sev={finding.severity.value} "
            f"conf={finding.confidence:.2f} suppressed={finding.suppressed}"
        )
        lines.append(f"    title: {finding.title}")
        if finding.explanation:
            lines.append(f"    explanation: {finding.explanation.strip().splitlines()[0]}")
        for item in finding.evidence:
            lines.append(
                f"    evidence[{item.kind.value}/{item.source.value}] "
                f"{item.label} t={item.t_ms} conf={item.confidence}: {item.value!r}"
            )
    return "\n".join(lines) + "\n"


def collect_cases(
    *,
    source: str,
    limit: int,
    cache_dir: Path | None = None,
    fixture_root: Path | None = None,
) -> list[MatchCase]:
    """Load GST cases from cache, fixtures, and/or synthetic labelled+quiet sets.

    Does not call the Riot API. Empty cache is not padded with fake live games.
    """
    cases: list[MatchCase] = []
    if source in {"cache", "all"}:
        cases.extend(_from_cache(cache_dir or get_settings().cache_dir, limit=limit))
    if source in {"fixtures", "all"} and len(cases) < limit:
        cases.extend(_from_fixtures(fixture_root or FIXTURE_ROOT, limit=limit - len(cases)))
    if source in {"synthetic", "all", "cache"} and len(cases) < limit:
        # ``cache`` falls back to synthetic when the on-disk Riot cache is empty.
        if source != "cache" or not cases:
            cases.extend(_from_synthetic(limit=limit - len(cases)))
    return cases[:limit]


def _from_cache(cache_dir: Path, *, limit: int) -> list[MatchCase]:
    index = cache_dir / "riot_cache.sqlite3"
    if not index.is_file():
        return []
    cache = RiotCache(cache_dir)
    # Best-effort: scan index URLs for paired match + timeline payloads.
    import sqlite3

    conn = sqlite3.connect(index)
    try:
        rows = conn.execute("SELECT url FROM riot_cache WHERE status = 200").fetchall()
    finally:
        conn.close()
    timelines: dict[str, bytes] = {}
    matches: dict[str, bytes] = {}
    for (url,) in rows:
        if not isinstance(url, str):
            continue
        body = cache.get(url)
        if body is None:
            continue
        if "/timelines/" in url:
            match_id = url.rstrip("/").split("/")[-1].split("?")[0]
            timelines[match_id] = body
        elif "/matches/" in url and "/timelines/" not in url:
            match_id = url.rstrip("/").split("/")[-1].split("?")[0]
            matches[match_id] = body
    cases: list[MatchCase] = []
    for match_id, raw_match in matches.items():
        raw_tl = timelines.get(match_id)
        if raw_tl is None:
            continue
        try:
            match = MatchDto.model_validate(json.loads(raw_match.decode("utf-8")))
            timeline = TimelineDto.model_validate(json.loads(raw_tl.decode("utf-8")))
        except (ValueError, json.JSONDecodeError):
            continue
        if not games_are_paired(match, timeline):
            continue
        gst = build_game_state_timeline(match, timeline)
        cases.append(MatchCase(match_id, gst, 1, "cache"))
        if len(cases) >= limit:
            break
    return cases


def _from_fixtures(root: Path, *, limit: int) -> list[MatchCase]:
    cases: list[MatchCase] = []
    if not root.is_dir():
        return cases
    for folder in sorted(root.iterdir()):
        if not (folder / "match.json").is_file() or not (folder / "timeline.json").is_file():
            continue
        match = MatchDto.model_validate(
            json.loads((folder / "match.json").read_text(encoding="utf-8"))
        )
        timeline = TimelineDto.model_validate(
            json.loads((folder / "timeline.json").read_text(encoding="utf-8"))
        )
        gst = build_game_state_timeline(match, timeline)
        note = "fixture" if games_are_paired(match, timeline) else "fixture-unpaired"
        cases.append(MatchCase(folder.name, gst, 1, note))
        if len(cases) >= limit:
            break
    return cases


def _from_synthetic(limit: int) -> list[MatchCase]:
    import importlib
    import sys

    analysis_root = str(Path(__file__).resolve().parents[3])
    if analysis_root not in sys.path:
        sys.path.insert(0, analysis_root)
    scenarios: Any = importlib.import_module("tests.helpers.h7_scenarios")

    cases: list[MatchCase] = []
    for name, builder, _expected in scenarios.LABELLED:
        gst = builder()
        cases.append(MatchCase(name, gst, 1, "synthetic-labelled"))
        if len(cases) >= limit:
            return cases
    for rule_id, builder in scenarios.MUST_FIRE.items():
        gst = builder()
        cases.append(MatchCase(f"must_{rule_id}", gst, 1, "synthetic-must-fire"))
        if len(cases) >= limit:
            return cases
    n = 0
    while len(cases) < limit:
        gst = scenarios.quiet_game(n)
        cases.append(MatchCase(gst.match_id, gst, 1, "synthetic-quiet"))
        n += 1
    return cases


def _conf_bucket(confidence: float) -> str:
    if confidence >= 0.85:
        return ">=0.85"
    if confidence >= 0.6:
        return "0.60-0.85"
    if confidence >= 0.35:
        return "0.35-0.60"
    return "<0.35"


def dump_finding(finding: Finding) -> dict[str, Any]:
    """Return a JSON-able evidence dump for one finding."""
    return {
        "id": finding.id,
        "rule_id": finding.rule_id,
        "t_ms": finding.t_ms,
        "severity": finding.severity.value,
        "confidence": finding.confidence,
        "title": finding.title,
        "explanation": finding.explanation,
        "suppressed": finding.suppressed,
        "evidence": [
            {
                "kind": item.kind.value,
                "source": item.source.value,
                "label": item.label,
                "value": item.value,
                "t_ms": item.t_ms,
                "confidence": item.confidence,
            }
            for item in finding.evidence
        ],
    }


def iter_production_ids(pack: RulePack | None = None) -> Iterable[str]:
    """Yield production rule ids in stable order."""
    loaded = pack or load_rule_pack()
    for rule in production_rules(loaded):
        yield rule.id
