from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_ANALYSIS = _REPO / "services" / "analysis"
if str(_ANALYSIS) not in sys.path:
    sys.path.insert(0, str(_ANALYSIS))

from riftlens.analysis.rules.lab import (  # noqa: E402
    collect_cases,
    format_report,
    run_rule_lab,
)


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m tools.rule_lab run --rule R-001 --matches cache --limit 200``."""
    parser = argparse.ArgumentParser(prog="rule_lab", description="H.7 rule fire-rate lab")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="Evaluate one rule over a local corpus")
    run.add_argument("--rule", required=True, help="Rule id, e.g. R-001")
    run.add_argument(
        "--matches",
        default="cache",
        choices=("cache", "fixtures", "synthetic", "all"),
        help="cache (fall back to synthetic if empty), fixtures, synthetic, or all",
    )
    run.add_argument("--limit", type=int, default=200)
    args = parser.parse_args(argv)
    if args.cmd != "run":
        parser.error("unknown command")
    cases = collect_cases(source=args.matches, limit=max(1, args.limit))
    if not cases:
        print(
            "No matches available. On-disk Riot cache is empty and no fixtures/synthetic "
            "cases were loaded. rule_lab does not crawl live Riot games.",
            file=sys.stderr,
        )
        return 2
    report = run_rule_lab(args.rule, cases)
    print(format_report(report), end="")
    if report.fire_rate > 50.0:
        print(
            f"WARNING: fire rate {report.fire_rate:.1f}% > 50%. "
            "Retune or add a YAML justification comment if this describes normal play.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
