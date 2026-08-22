#!/usr/bin/env python3
"""Developer RP.0 parity CLI — not production UI."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RP.0 reference parity benchmark")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("matrix", help="Print capability × reference matrix")
    sub.add_parser("baseline", help="Print Vladimir PILOT_SELF_REVIEW cases")
    sub.add_parser("gaps", help="Print ranked TOP PARITY GAPS")
    sub.add_parser("roadmap", help="Print RP.1+ tracks and acceptance policy")
    sub.add_parser("sources", help="Print evidence-source dependency table")
    args = parser.parse_args(argv)

    from riftlens.coaching.parity.report import (
        render_baseline,
        render_gaps,
        render_matrix,
        render_roadmap,
        render_sources,
    )

    reports = {
        "matrix": render_matrix,
        "baseline": render_baseline,
        "gaps": render_gaps,
        "roadmap": render_roadmap,
        "sources": render_sources,
    }
    print(reports[args.cmd](), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
