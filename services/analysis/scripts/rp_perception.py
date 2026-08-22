#!/usr/bin/env python3
"""Developer RP.1 perception CLI — not production UI.

Frames come from an existing R.10 capture directory or a still image.
Match-id alone cannot produce pixels without an R.10 capture (or --capture).

Real-replay path (Vladimir baseline):
  1) Ensure local .rofl is imported / linked (R.10 GameplaySourceService).
  2) Capture short CLIP windows (±2.5s) via:
       python scripts/rp_perception.py baseline --capture --debug
     (requires RIFTLENS_RP1_CAPTURE=1 and an active League replay session).
  3) Or reuse existing dirs under ~/.riftlens/captures/{match_id}/:
       python scripts/rp_perception.py baseline --debug
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from riftlens.perception.capture import CapturedFrame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RP.1 rich replay perception")
    sub = parser.add_subparsers(dest="cmd", required=True)

    audit = sub.add_parser("audit", help="Print perception capability list")
    audit.add_argument("--json", action="store_true")

    inspect = sub.add_parser("inspect", help="Perceive one timestamp from a capture/image")
    _add_source_args(inspect)
    inspect.add_argument("--timestamp", type=int, required=True, help="Requested game t_ms")
    inspect.add_argument("--fps", type=float, default=2.0)
    inspect.add_argument("--debug", action="store_true")
    inspect.add_argument("--debug-dir", type=Path, default=None)
    inspect.add_argument("--json", action="store_true")

    seq = sub.add_parser("sequence", help="Perceive a short window around a timestamp")
    _add_source_args(seq)
    seq.add_argument("--timestamp", type=int, required=True)
    seq.add_argument("--pre-ms", type=int, default=3000)
    seq.add_argument("--post-ms", type=int, default=3000)
    seq.add_argument("--fps", type=float, default=2.0)
    seq.add_argument("--debug", action="store_true")
    seq.add_argument("--debug-dir", type=Path, default=None)
    seq.add_argument("--json", action="store_true")

    manifest = sub.add_parser(
        "baseline-manifest",
        help="Print Vladimir baseline inspection timestamps (no media)",
    )
    manifest.add_argument("--json", action="store_true")

    coverage = sub.add_parser(
        "baseline-coverage",
        help="Report which baseline windows already have R.10 captures",
    )
    coverage.add_argument("--match-id", type=str, default=None)
    coverage.add_argument("--captures-root", type=Path, default=None)
    coverage.add_argument("--half-window-ms", type=int, default=2500)
    coverage.add_argument("--json", action="store_true")

    baseline = sub.add_parser(
        "baseline",
        help="Batch-inspect all Vladimir baseline timestamps from R.10 captures",
    )
    baseline.add_argument("--match-id", type=str, default=None)
    baseline.add_argument("--captures-root", type=Path, default=None)
    baseline.add_argument(
        "--half-window-ms",
        type=int,
        default=2500,
        help="±ms around each baseline t (default 2500)",
    )
    baseline.add_argument("--fps", type=float, default=2.0)
    baseline.add_argument("--debug", action="store_true")
    baseline.add_argument("--debug-dir", type=Path, default=None)
    baseline.add_argument("--json", action="store_true")
    baseline.add_argument(
        "--capture",
        action="store_true",
        help="Request missing R.10 CLIP windows (requires RIFTLENS_RP1_CAPTURE=1)",
    )
    baseline.add_argument(
        "--rofl",
        type=Path,
        default=None,
        help="Optional .rofl path when --capture imports a source",
    )
    baseline.add_argument(
        "--source-id",
        type=str,
        default=None,
        help="Existing gameplay source id (skip import when set)",
    )
    baseline.add_argument(
        "--allow-partial",
        action="store_true",
        help="Inspect covered timestamps even when some baseline windows are missing",
    )

    args = parser.parse_args(argv)
    if args.cmd == "audit":
        return _cmd_audit(args.json)
    if args.cmd == "baseline-manifest":
        return _cmd_manifest(args.json)
    if args.cmd == "baseline-coverage":
        return _cmd_coverage(args)
    if args.cmd == "baseline":
        return _cmd_baseline(args)
    if args.cmd == "inspect":
        return _cmd_inspect(args)
    if args.cmd == "sequence":
        return _cmd_sequence(args)
    return 2


def _add_source_args(parser: argparse.ArgumentParser) -> None:
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--capture-dir",
        type=Path,
        help="Existing R.10 capture directory with manifest.json + media",
    )
    src.add_argument(
        "--image",
        type=Path,
        help="Still RGB image (PNG/JPEG) treated as the frame at --timestamp",
    )


def _cmd_audit(as_json: bool) -> int:
    from riftlens.perception.models import PerceptionCapabilityStatus
    from riftlens.perception.readiness import evaluate_perception_capabilities

    # Empty evidence → BLOCKED sensors listed with schema.
    caps = evaluate_perception_capabilities((), ())
    if as_json:
        print(json.dumps([item.to_dict() for item in caps], indent=2, sort_keys=True))
    else:
        print("RP.1 PERCEPTION CAPABILITIES (no frames → BLOCKED)")
        for item in caps:
            print(f"- {item.capability_id}: {item.status.value} — {item.evidence}")
        print(f"statuses: {', '.join(s.value for s in PerceptionCapabilityStatus)}")
    return 0


def _cmd_manifest(as_json: bool) -> int:
    from riftlens.perception.baseline import VLADIMIR_BASELINE_MANIFEST

    if as_json:
        print(json.dumps(VLADIMIR_BASELINE_MANIFEST, indent=2, sort_keys=True))
    else:
        print("VLADIMIR BASELINE INSPECTION MANIFEST")
        print(f"match_id: {VLADIMIR_BASELINE_MANIFEST['match_id']}")
        print(f"participant_id: {VLADIMIR_BASELINE_MANIFEST['participant_id']}")
        print(f"champion: {VLADIMIR_BASELINE_MANIFEST['champion']}")
        print(f"role: {VLADIMIR_BASELINE_MANIFEST['role']}")
        print("timestamps:")
        for row in VLADIMIR_BASELINE_MANIFEST["timestamps"]:
            print(f"  - {row['clock']}  {row['t_ms']}  {row['subject']}")
        print("NOTE: media is not committed; capture locally via R.10 then inspect.")
    return 0


def _cmd_coverage(args: argparse.Namespace) -> int:
    from riftlens.perception.validation import plan_baseline_windows, render_coverage_report

    plans = plan_baseline_windows(
        match_id=args.match_id,
        captures_root=args.captures_root,
        half_window_ms=args.half_window_ms,
    )
    if args.json:
        payload = [
            {
                "clock": plan.stamp.clock,
                "t_ms": plan.stamp.t_ms,
                "subject": plan.stamp.subject,
                "window_start_ms": plan.window_start_ms,
                "window_end_ms": plan.window_end_ms,
                "covered": plan.covered,
                "capture_id": None if plan.covering is None else plan.covering.capture_id,
                "capture_dir": (
                    None if plan.covering is None else str(plan.covering.capture_dir)
                ),
            }
            for plan in plans
        ]
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_coverage_report(plans), end="")
    return 0


def _cmd_baseline(args: argparse.Namespace) -> int:
    from riftlens.perception.assemble import assemble_rich_state
    from riftlens.perception.baseline import VLADIMIR_BASELINE_MANIFEST
    from riftlens.perception.capture import sample_capture_dir, sequence_around
    from riftlens.perception.debug import default_debug_root, write_debug_bundle
    from riftlens.perception.validation import (
        plan_baseline_windows,
        render_baseline_human_check,
        render_coverage_report,
        validate_capture_dir,
    )

    match_id = args.match_id or str(VLADIMIR_BASELINE_MANIFEST["match_id"])
    if args.capture:
        code = asyncio.run(
            _capture_missing_baseline_windows(
                match_id=match_id,
                captures_root=args.captures_root,
                half_window_ms=args.half_window_ms,
                rofl=args.rofl,
                source_id=args.source_id,
                only_missing=True,
            )
        )
        if code != 0:
            return code

    plans = plan_baseline_windows(
        match_id=match_id,
        captures_root=args.captures_root,
        half_window_ms=args.half_window_ms,
    )
    print(render_coverage_report(plans), end="")
    missing = [plan for plan in plans if not plan.covered]
    if missing and not args.allow_partial:
        print(
            "ERROR: missing R.10 captures for some baseline windows.\n"
            "Provide media via:\n"
            "  python scripts/rp_perception.py baseline --capture --debug\n"
            "  (set RIFTLENS_RP1_CAPTURE=1; League replay session must be READY)\n"
            "Or re-run with --allow-partial to inspect covered timestamps only.\n",
            file=sys.stderr,
        )
        return 3

    debug_root = args.debug_dir or default_debug_root()
    results: list[dict[str, Any]] = []
    runnable = [plan for plan in plans if plan.covered]
    if not runnable:
        print("ERROR: no covering R.10 captures found for any baseline timestamp.", file=sys.stderr)
        return 3
    for plan in runnable:
        assert plan.covering is not None
        capture_dir = plan.covering.capture_dir
        validate_capture_dir(capture_dir)
        samples = sample_capture_dir(capture_dir, fps=args.fps)
        frames = sequence_around(
            samples,
            requested_game_t_ms=plan.stamp.t_ms,
            pre_ms=args.half_window_ms,
            post_ms=args.half_window_ms,
        )
        state = assemble_rich_state(frames, requested_game_t_ms=plan.stamp.t_ms)
        if args.json:
            results.append(
                {
                    "clock": plan.stamp.clock,
                    "subject": plan.stamp.subject,
                    "capture_dir": str(capture_dir),
                    "state": state.to_dict(),
                }
            )
        else:
            print(
                render_baseline_human_check(
                    state,
                    clock=plan.stamp.clock,
                    subject=plan.stamp.subject,
                    capture_dir=capture_dir,
                ),
                end="",
            )
        if args.debug:
            dest = write_debug_bundle(
                state,
                frames,
                out_dir=debug_root,
                label=f"baseline_{plan.stamp.clock.replace(':', '')}",
            )
            print(f"debug artifacts: {dest}", file=sys.stderr)
    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    return 0


async def _capture_missing_baseline_windows(
    *,
    match_id: str,
    captures_root: Path | None,
    half_window_ms: int,
    rofl: Path | None,
    source_id: str | None,
    only_missing: bool,
) -> int:
    """Smallest R.10 bridge: CLIP each uncovered ±window. Developer-only."""
    if os.environ.get("RIFTLENS_RP1_CAPTURE") != "1":
        print(
            "REFUSED: set RIFTLENS_RP1_CAPTURE=1 to request real R.10 captures.\n"
            "Requires League client + local .rofl + READY replay session.",
            file=sys.stderr,
        )
        return 2

    from riftlens.adapters.db.engine import init_database, make_session_factory
    from riftlens.adapters.db.repositories import (
        SqlCaptureRepository,
        SqlGameplayRepository,
        SqlMatchRepository,
    )
    from riftlens.config import get_settings
    from riftlens.domain.capture import CaptureMode, CaptureRequest, CaptureStatus, RetentionClass
    from riftlens.gameplay.service import GameplaySourceService
    from riftlens.perception.validation import plan_baseline_windows
    from riftlens.replay_host.capture.capture_service import CaptureService
    from riftlens.replay_host.factory import create_replay_host

    plans = plan_baseline_windows(
        match_id=match_id,
        captures_root=captures_root,
        half_window_ms=half_window_ms,
    )
    todo = [plan for plan in plans if (not only_missing) or (not plan.covered)]
    if not todo:
        print("All baseline windows already covered by existing R.10 captures.")
        return 0

    settings = get_settings()
    engine = init_database(settings)
    factory = make_session_factory(engine)
    host = create_replay_host()
    gameplay_repo = SqlGameplayRepository(factory)
    capture_repo = SqlCaptureRepository(factory)
    captures = CaptureService(
        host=host,
        captures=capture_repo,
        gameplay=gameplay_repo,
        captures_dir=settings.captures_dir if captures_root is None else Path(captures_root),
        budget=settings.capture_budget,
    )
    service = GameplaySourceService(
        host=host,
        gameplay=gameplay_repo,
        matches=SqlMatchRepository(factory),
        captures=captures,
    )

    resolved_source = source_id
    if resolved_source is None:
        resolved_source = await _resolve_or_import_source(
            service,
            match_id=match_id,
            rofl=rofl,
            gameplay_repo=gameplay_repo,
        )
        if resolved_source is None:
            engine.dispose()
            return 4

    print(f"OPENING REPLAY SESSION for source {resolved_source} ...")
    session = await service.open_linked_source(resolved_source)
    print("SESSION", session.phase, session.error)
    if not session.is_active:
        engine.dispose()
        return 5

    failures = 0
    for plan in todo:
        req = CaptureRequest(
            source_id=resolved_source,
            start_game_ms=plan.window_start_ms,
            end_game_ms=plan.window_end_ms,
            mode=CaptureMode.CLIP,
            retention=RetentionClass.EPHEMERAL,
        )
        print(
            f"CAPTURE {plan.stamp.clock} t={plan.stamp.t_ms} "
            f"[{plan.window_start_ms},{plan.window_end_ms}]"
        )
        started = await service.request_capture(req, now_ms=int(time.time() * 1000))
        if started.capture_id is None:
            print("  FAIL start", started.status, started.error)
            failures += 1
            continue
        result = await captures.await_result(started.capture_id, timeout_s=600.0)
        print("  DONE", result.status, result.ok, result.error)
        if not result.ok or result.status is not CaptureStatus.COMPLETE:
            failures += 1

    await service.close_session(resolved_source, now_ms=int(time.time() * 1000))
    engine.dispose()
    return 0 if failures == 0 else 6


async def _resolve_or_import_source(
    service: object,
    *,
    match_id: str,
    rofl: Path | None,
    gameplay_repo: object,
) -> str | None:
    """Prefer an existing linked source; else import --rofl or default Documents path."""
    existing = await _latest_source_id(gameplay_repo, match_id=match_id)
    if existing is not None:
        print(f"Using existing gameplay source {existing}")
        return existing
    path = rofl or _default_vladimir_rofl(match_id)
    if path is None or not path.is_file():
        print(
            "FAIL: no gameplay source and .rofl not found.\n"
            "Pass --rofl /path/to/NA1-5620410094.rofl "
            "or place it under Documents/League of Legends/Replays/",
            file=sys.stderr,
        )
        return None
    print("IMPORT", path)
    imported = await service.import_rofl(  # type: ignore[attr-defined]
        str(path),
        now_ms=int(time.time() * 1000),
        match_id=match_id,
    )
    print("IMPORT", imported.ok, imported.source_id, imported.error)
    if not imported.ok or imported.source_id is None:
        return None
    return str(imported.source_id)


async def _latest_source_id(gameplay_repo: object, *, match_id: str) -> str | None:
    """Best-effort lookup via SQL repo list API if present; else None."""
    list_fn = getattr(gameplay_repo, "list_for_match", None)
    if callable(list_fn):
        rows = await list_fn(match_id)
        if rows:
            first = rows[0]
            return str(getattr(first, "id", first))
    # Fallback: direct sqlite on configured DB.
    from riftlens.config import get_settings

    settings = get_settings()
    import sqlite3

    con = sqlite3.connect(settings.db_path)
    row = con.execute(
        """
        SELECT id FROM gameplay_source WHERE match_id = ?
        ORDER BY rowid DESC LIMIT 1
        """,
        (match_id,),
    ).fetchone()
    con.close()
    return None if row is None else str(row[0])


def _default_vladimir_rofl(match_id: str) -> Path | None:
    needle = match_id.replace("_", "-")
    for key in ("RIFTLENS_R6_ROFL", "RIFTLENS_REPLAY_ROFL", "RIFTLENS_RP1_ROFL"):
        raw = os.environ.get(key)
        if raw:
            path = Path(raw)
            return path if path.is_file() else None
    candidates = (
        Path.home() / "Documents" / "League of Legends" / "Replays",
        Path.home() / "OneDrive" / "Documents" / "League of Legends" / "Replays",
    )
    for folder in candidates:
        if not folder.is_dir():
            continue
        hits = sorted(folder.glob(f"*{needle}*.rofl"))
        if hits:
            return hits[0]
    return None


def _cmd_inspect(args: argparse.Namespace) -> int:
    from riftlens.perception.assemble import assemble_rich_state
    from riftlens.perception.debug import default_debug_root, write_debug_bundle
    from riftlens.perception.report import render_rich_state
    from riftlens.perception.validation import validate_capture_dir

    if args.capture_dir is not None:
        validate_capture_dir(Path(args.capture_dir))
    frames = _load_frames(args, sequence=False)
    state = assemble_rich_state(frames, requested_game_t_ms=args.timestamp)
    if args.json:
        print(json.dumps(state.to_dict(), indent=2, sort_keys=True))
    else:
        print(render_rich_state(state), end="")
    if args.debug:
        out = args.debug_dir or default_debug_root()
        dest = write_debug_bundle(state, frames, out_dir=out, label="inspect")
        print(f"debug artifacts: {dest}", file=sys.stderr)
    return 0


def _cmd_sequence(args: argparse.Namespace) -> int:
    from riftlens.perception.assemble import assemble_rich_state
    from riftlens.perception.debug import default_debug_root, write_debug_bundle
    from riftlens.perception.report import render_rich_state
    from riftlens.perception.validation import validate_capture_dir

    if args.capture_dir is not None:
        validate_capture_dir(Path(args.capture_dir))
    frames = _load_frames(args, sequence=True)
    state = assemble_rich_state(frames, requested_game_t_ms=args.timestamp)
    if args.json:
        print(json.dumps(state.to_dict(), indent=2, sort_keys=True))
    else:
        print(render_rich_state(state), end="")
    if args.debug:
        out = args.debug_dir or default_debug_root()
        dest = write_debug_bundle(state, frames, out_dir=out, label="sequence")
        print(f"debug artifacts: {dest}", file=sys.stderr)
    return 0


def _load_frames(
    args: argparse.Namespace,
    *,
    sequence: bool,
) -> tuple[CapturedFrame, ...]:
    from riftlens.perception.capture import (
        frame_from_image_path,
        nearest_sampled_frame,
        sample_capture_dir,
        sequence_around,
    )

    if args.image is not None:
        frame = frame_from_image_path(
            Path(args.image),
            requested_game_t_ms=args.timestamp,
        )
        return (frame,)
    samples = sample_capture_dir(Path(args.capture_dir), fps=args.fps)
    if sequence:
        return sequence_around(
            samples,
            requested_game_t_ms=args.timestamp,
            pre_ms=args.pre_ms,
            post_ms=args.post_ms,
        )
    return (nearest_sampled_frame(samples, requested_game_t_ms=args.timestamp),)


if __name__ == "__main__":
    sys.exit(main())
