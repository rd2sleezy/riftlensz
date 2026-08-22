#!/usr/bin/env python3
"""Developer-only: run ONE real Riot match through experimental C.x coaching.

Not production review wiring. Does not modify H.8/H.11 player-facing behavior.

HUMAN QUALITY VALIDATION has NOT been performed.

Cache side effects:
  ensure_match_ingested may write Riot forever-cache under settings.cache_dir
  and may upsert match/timeline rows into the local SQLite DB. The harness
  itself calls build_review_from_dtos(..., persist=False) so it does not write
  review presentation / coaching rows.

Privacy:
  Does not print PUUID, summoner names, API keys, or raw Riot DTOs.
  --out refuses paths inside the git repository.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run experimental C.1–C.5 (optional C.6/C.7) on one real Riot match. "
            "Developer validation only — not production coaching."
        )
    )
    parser.add_argument("--match-id", required=True, help="Platform match id, e.g. NA1_...")
    parser.add_argument(
        "--pid",
        type=int,
        required=True,
        help="Participant id 1..10",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Also emit structured JSON after the human report",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write JSON result outside the repo (refused if under repo root)",
    )
    parser.add_argument(
        "--include-c6",
        action="store_true",
        help="Build single-game longitudinal state for inspection",
    )
    parser.add_argument(
        "--include-c7",
        action="store_true",
        help="Run C.7 automated structural checks (not human quality validation)",
    )
    parser.add_argument(
        "--region",
        default=None,
        help="Optional Riot routing region override",
    )
    parser.add_argument(
        "--rank",
        default="UNRANKED",
        help="Rank label for H.7/H.8 finding build path (default UNRANKED)",
    )
    args = parser.parse_args(argv)

    try:
        from riftlens.coaching.validation import (
            assert_safe_output_path,
            format_human_report,
            run_cx_pipeline,
            validate_participant_id,
        )
        from riftlens.coaching.validation.cx_real_match import load_patch_data
        from riftlens.config import get_settings
        from riftlens.pipeline.assemble.real_match import ensure_match_ingested
        from riftlens.pipeline.assemble.review_builder import build_review_from_dtos
    except ImportError as exc:
        print(f"Import failure: {exc}", file=sys.stderr)
        return 2

    try:
        validate_participant_id(args.pid)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    settings = get_settings()

    async def _load() -> tuple:
        ingested = await ensure_match_ingested(
            args.match_id,
            region=args.region,
            settings=settings,
        )
        built = build_review_from_dtos(
            ingested.match,
            ingested.timeline,
            args.pid,
            rank=args.rank,
            llm_provider="null",
            persist=False,
            settings=settings,
        )
        return ingested, built

    try:
        ingested, built = asyncio.run(_load())
    except Exception as exc:  # noqa: BLE001 — surface clear developer errors
        print(f"ERROR: ingest/build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    gst = built.gst
    findings = list(built.review.findings)
    patch, patch_status = load_patch_data(gst)
    if patch is None:
        print(f"WARNING: {patch_status}", file=sys.stderr)

    try:
        result = run_cx_pipeline(
            gst,
            findings,
            args.pid,
            patch=patch,
            include_c6=args.include_c6,
            include_c7=args.include_c7,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: C.x pipeline failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    report = format_human_report(result)
    print(report)

    if args.json or args.out is not None:
        payload = result.to_dict()
        # Never embed raw DTOs
        payload["ingest"] = {
            "match_id": ingested.match_id,
            "fetched": ingested.fetched,
            "cache_note": (
                "ensure_match_ingested may write Riot forever-cache and/or "
                "match DB rows; review persist=False"
            ),
        }
        text = json.dumps(payload, indent=2, sort_keys=True)
        if args.json:
            print("----- JSON -----")
            print(text)
        if args.out is not None:
            try:
                out_path = assert_safe_output_path(args.out, repo_root=_repo_root())
            except ValueError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(text + "\n", encoding="utf-8")
            print(f"Wrote JSON to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
