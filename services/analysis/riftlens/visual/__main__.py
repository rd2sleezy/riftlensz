from __future__ import annotations

import argparse
import json
from pathlib import Path

from riftlens.config import default_captures_dir
from riftlens.visual.analyze import DEFAULT_SAMPLE_FPS, analyze_capture_dir
from riftlens.visual.report import (
    StructuredClaim,
    classify_against_claim,
    format_timeline,
    temporal_change_notes,
)


def main() -> None:
    """Run the V.0 spike against an R.10 capture directory. Local only."""
    parser = argparse.ArgumentParser(description="V.0 visual clip analysis spike")
    parser.add_argument("--capture-dir", type=Path, help="Directory containing manifest.json")
    parser.add_argument("--capture-id", help="Lookup capture_id under the capture root")
    parser.add_argument("--capture-root", type=Path, default=None)
    parser.add_argument("--fps", type=float, default=DEFAULT_SAMPLE_FPS)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--claim-rule", default="R-012")
    parser.add_argument("--claim-t-ms", type=int, default=None)
    parser.add_argument(
        "--claim-summary",
        default="Fought into unaccounted-for enemies (structured GST claim)",
    )
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()
    capture_dir = _resolve_dir(args.capture_dir, args.capture_id, args.capture_root)
    result = analyze_capture_dir(capture_dir, fps=args.fps, max_frames=args.max_frames)
    print(format_timeline(result), end="")
    print("temporal changes:")
    for note in temporal_change_notes(result):
        print(f"  {note}")
    claim = StructuredClaim(
        rule_id=args.claim_rule, t_ms=args.claim_t_ms, summary=args.claim_summary
    )
    diagnostic = classify_against_claim(result, claim)
    print(f"visual-vs-rule diagnostic: {diagnostic.value} for {claim.rule_id}")
    print(
        f"perf extract={result.extract_ms:.0f}ms analyze={result.analyze_ms:.0f}ms "
        f"frames={result.sequence.sample_count}/{result.sequence.expected_sample_count}"
    )
    if args.json_out is not None:
        args.json_out.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")


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
