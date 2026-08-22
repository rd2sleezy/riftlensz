#!/usr/bin/env python3
"""Developer RP.1 perception CLI — not production UI.

Frames come from an existing R.10 capture directory or a still image.
Match-id alone cannot produce pixels (no live seek from this script).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

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

    args = parser.parse_args(argv)
    if args.cmd == "audit":
        return _cmd_audit(args.json)
    if args.cmd == "baseline-manifest":
        return _cmd_manifest(args.json)
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


def _cmd_inspect(args: argparse.Namespace) -> int:
    from riftlens.perception.assemble import assemble_rich_state
    from riftlens.perception.debug import default_debug_root, write_debug_bundle
    from riftlens.perception.report import render_rich_state

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
        CapturedFrame,
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
