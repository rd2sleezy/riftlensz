#!/usr/bin/env python3
"""Minimal C.7 benchmark CLI (developer tooling — not production UI)."""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="C.7 coaching quality benchmark")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("regression", help="Run CI regression benchmark")
    sub.add_parser("corpus", help="List initial corpus case ids")
    sub.add_parser("template", help="Print human rating JSON template")
    sub.add_parser("report", help="Summarize empty/automated corpus report")

    args = parser.parse_args(argv)

    from riftlens.coaching.evaluation import (
        build_initial_corpus,
        rating_template,
        render_report_markdown,
        run_ci_regression_benchmark,
        summarize_benchmark,
    )

    if args.cmd == "regression":
        result = run_ci_regression_benchmark()
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 0 if result.passed else 1
    if args.cmd == "corpus":
        for case in build_initial_corpus():
            print(f"{case.case_id}\t{case.source_type.value}\t{','.join(case.domains)}")
        return 0
    if args.cmd == "template":
        print(json.dumps(rating_template(), indent=2, sort_keys=True))
        return 0
    if args.cmd == "report":
        cases = build_initial_corpus()
        summary = summarize_benchmark(cases, ())
        print(render_report_markdown(summary))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
