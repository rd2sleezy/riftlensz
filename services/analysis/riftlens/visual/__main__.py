from __future__ import annotations

import argparse
import json
from pathlib import Path

from riftlens.config import default_captures_dir
from riftlens.visual.analyze import DEFAULT_SAMPLE_FPS, analyze_capture_dir
from riftlens.visual.report import (
    StructuredClaim,
    classify_against_claim,
    classify_v1_against_claim,
    format_timeline,
    format_v1_timeline,
    temporal_change_notes,
)
from riftlens.visual.v1_analyze import DEFAULT_V1_SAMPLE_FPS, analyze_capture_dir_v1
from riftlens.visual.v2_analyze import DEFAULT_V2_SAMPLE_FPS, analyze_capture_dir_v2
from riftlens.visual.v4_analyze import DEFAULT_V4_SAMPLE_FPS, analyze_capture_dir_v4
from riftlens.visual.v5_analyze import DEFAULT_V5_SAMPLE_FPS, analyze_capture_dir_v5


def main() -> None:
    """Run V.0–V.5 against an R.10 capture directory. Local only."""
    parser = argparse.ArgumentParser(description="Visual clip analysis spike")
    parser.add_argument("--capture-dir", type=Path, help="Directory containing manifest.json")
    parser.add_argument("--capture-id", help="Lookup capture_id under the capture root")
    parser.add_argument("--capture-root", type=Path, default=None)
    parser.add_argument("--mode", choices=("v0", "v1", "v2", "v4", "v5"), default="v0")
    parser.add_argument("--fps", type=float, default=None)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--subject-pid", type=int, default=None)
    parser.add_argument("--subject-champion", default=None)
    parser.add_argument("--claim-rule", default="R-012")
    parser.add_argument("--claim-t-ms", type=int, default=None)
    parser.add_argument(
        "--claim-summary",
        default="Fought into unaccounted-for enemies (structured GST claim)",
    )
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()
    capture_dir = _resolve_dir(args.capture_dir, args.capture_id, args.capture_root)
    claim = StructuredClaim(
        rule_id=args.claim_rule, t_ms=args.claim_t_ms, summary=args.claim_summary
    )
    if args.mode in {"v1", "v2", "v4", "v5"}:
        defaults = {
            "v1": DEFAULT_V1_SAMPLE_FPS,
            "v2": DEFAULT_V2_SAMPLE_FPS,
            "v4": DEFAULT_V4_SAMPLE_FPS,
            "v5": DEFAULT_V5_SAMPLE_FPS,
        }
        fps = defaults[args.mode] if args.fps is None else args.fps
        analyze = {
            "v1": analyze_capture_dir_v1,
            "v2": analyze_capture_dir_v2,
            "v4": analyze_capture_dir_v4,
            "v5": analyze_capture_dir_v5,
        }[args.mode]
        result = analyze(
            capture_dir,
            fps=fps,
            max_frames=args.max_frames,
            subject_pid=args.subject_pid,
            subject_champion=args.subject_champion,
            capture_review_pid=args.subject_pid,
        )
        print(format_v1_timeline(result), end="")
        diagnostic = classify_v1_against_claim(result, claim)
        print(f"visual-vs-rule diagnostic: {diagnostic.value} for {claim.rule_id}")
        calib = getattr(result, "calibration", None)
        if calib is not None:
            print(
                f"calibration {calib.confidence.value} anchors={len(calib.anchors)} "
                f"version={calib.version}"
            )
        v5 = getattr(result, "v5", None)
        if v5 is not None:
            print(
                f"v5 identity_change={v5.identity_change} "
                f"base={v5.base.status.value}/{v5.base.confidence} "
                f"refined={v5.refined.status.value}/{v5.refined.confidence} "
                f"continuity_ms={getattr(result, 'continuity_ms', 0):.1f}"
            )
        print(
            f"perf total={result.timing.total_ms:.0f}ms extract={result.timing.extract_ms:.0f}ms "
            f"detect={result.timing.detect_ms:.0f}ms track={result.timing.track_ms:.0f}ms "
            f"align={result.timing.align_ms:.0f}ms "
            f"frames={result.timing.analyzed_frames}/{result.sequence.expected_sample_count}"
        )
        if args.json_out is not None:
            args.json_out.write_text(
                json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8"
            )
        return
    fps = DEFAULT_SAMPLE_FPS if args.fps is None else args.fps
    v0 = analyze_capture_dir(capture_dir, fps=fps, max_frames=args.max_frames)
    print(format_timeline(v0), end="")
    print("temporal changes:")
    for note in temporal_change_notes(v0):
        print(f"  {note}")
    diagnostic = classify_against_claim(v0, claim)
    print(f"visual-vs-rule diagnostic: {diagnostic.value} for {claim.rule_id}")
    print(
        f"perf extract={v0.extract_ms:.0f}ms analyze={v0.analyze_ms:.0f}ms "
        f"frames={v0.sequence.sample_count}/{v0.sequence.expected_sample_count}"
    )
    if args.json_out is not None:
        args.json_out.write_text(json.dumps(v0.to_dict(), indent=2) + "\n", encoding="utf-8")


def _resolve_dir(
    capture_dir: Path | None, capture_id: str | None, capture_root: Path | None
) -> Path:
    if capture_dir is not None:
        return capture_dir
    if not capture_id:
        raise SystemExit("provide --capture-dir or --capture-id")
    root = capture_root if capture_root is not None else default_captures_dir()
    matches = [path for path in root.glob(f"*/{capture_id}") if path.is_dir()]
    if len(matches) != 1:
        raise SystemExit(f"expected one capture dir for {capture_id}, found {len(matches)}")
    return matches[0]


if __name__ == "__main__":
    main()
