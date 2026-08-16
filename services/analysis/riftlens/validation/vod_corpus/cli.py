"""CLI: inventory, manifest check, checkpoint stubs, OCR/H.10 eval, summary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml

from riftlens.validation.vod_corpus.bench import blocked_30min, pick_30min_entry, run_30min_bench
from riftlens.validation.vod_corpus.checkpoints import extract_checkpoint_stub, load_checkpoints
from riftlens.validation.vod_corpus.h10_eval import VodH10Result, evaluate_entry
from riftlens.validation.vod_corpus.inventory import report_to_dict, scan_roots
from riftlens.validation.vod_corpus.manifest import (
    default_corpus_root,
    dump_corpus,
    load_corpus,
    validate_committed_portable,
)
from riftlens.validation.vod_corpus.ocr_eval import clock_corpus_diversity, evaluate_clock_corpus
from riftlens.validation.vod_corpus.resolve import resolve_media_ref
from riftlens.validation.vod_corpus.verdicts import compute_verdicts

corpus_app = typer.Typer(add_completion=False, no_args_is_help=True)


def register(app: typer.Typer) -> None:
    """Attach ``vod-corpus`` subcommands to the main CLI."""
    app.add_typer(corpus_app, name="vod-corpus")


@corpus_app.command("inventory")
def inventory_cmd() -> None:
    """Scan local disks for League-looking VIDEO / ROFL. Does not download."""
    report = scan_roots()
    print(json.dumps(report_to_dict(report), indent=2))


@corpus_app.command("validate-manifest")
def validate_manifest_cmd(
    path: Annotated[Path | None, typer.Option("--path")] = None,
) -> None:
    """Load the committed catalog and reject absolute media refs."""
    corpus = load_corpus(path, overlay=False)
    errors = validate_committed_portable(corpus)
    print(json.dumps({"entries": len(corpus.entries), "errors": errors}, indent=2))
    if errors:
        raise typer.Exit(code=1)


@corpus_app.command("extract-checkpoints")
def extract_checkpoints_cmd(
    media_ref: Annotated[str, typer.Argument(help="r10:// or vod:// ref, or local overlay path")],
    corpus_id: Annotated[str, typer.Option("--id")],
    times: Annotated[
        str, typer.Option("--times", help="Comma-separated video_t_ms")
    ] = "0,5000,10000",
    out: Annotated[Path, typer.Option("--out")] = Path("checkpoint_stubs"),
    allow_absolute: Annotated[bool, typer.Option("--allow-absolute")] = False,
) -> None:
    """Dump clock crops + YAML stub. Human fills visible_clock; do not copy H.10."""
    path = resolve_media_ref(media_ref, allow_absolute=allow_absolute)
    times_ms = [int(item.strip()) for item in times.split(",") if item.strip()]
    stub = extract_checkpoint_stub(path, times_ms, out, corpus_id=corpus_id)
    print(str(stub))


@corpus_app.command("eval-ocr")
def eval_ocr_cmd() -> None:
    """Evaluate labelled clock crops with atlas-match vs held-out split."""
    report = evaluate_clock_corpus()
    slim = {key: value for key, value in report.items() if key != "results"}
    print(json.dumps(slim, indent=2))


@corpus_app.command("eval-h10")
def eval_h10_cmd(
    allow_absolute: Annotated[bool, typer.Option("--allow-absolute")] = False,
) -> None:
    """Run production H.10 on every catalogued recording whose media resolves."""
    root = default_corpus_root()
    corpus = load_corpus()
    rows: list[VodH10Result] = []
    for entry in corpus.entries:
        rows.append(
            evaluate_entry(
                entry,
                corpus_root=root,
                allow_absolute=allow_absolute,
            )
        )
    print(json.dumps([row.to_dict() for row in rows], indent=2))


@corpus_app.command("summary")
def summary_cmd() -> None:
    """Print inventory + OCR split + H.10 rows + the three verdicts."""
    root = default_corpus_root()
    corpus = load_corpus()
    inventory = report_to_dict(scan_roots())
    ocr = evaluate_clock_corpus()
    diversity = clock_corpus_diversity()
    h10_rows = [
        evaluate_entry(entry, corpus_root=root, allow_absolute=True) for entry in corpus.entries
    ]
    resolved = {}
    for entry in corpus.entries:
        try:
            resolved[entry.id] = resolve_media_ref(entry.media_ref, allow_absolute=True)
        except ValueError:
            continue
    thirty = pick_30min_entry(list(corpus.entries), resolved=resolved)
    bench = (
        run_30min_bench(thirty, allow_absolute=True)
        if thirty is not None
        else blocked_30min("no REAL ~30-minute VOD in the catalog")
    )
    held = ocr["held_out_clean"]
    atlas = ocr["atlas_match_clean"]
    verdicts = compute_verdicts(
        entries=corpus.entries,
        h10_results=h10_rows,
        n_real_clean=int(diversity["n_real_clean"]),
        n_held_out_clean=int(held["total"]),
        n_matches=int(diversity["n_matches"]),
        n_resolutions=int(diversity["n_resolutions"]),
        has_early=bool(diversity["has_early"]),
        has_late=bool(diversity["has_late"]),
        confident_wrong=int(atlas["confident_wrong"]) + int(held["confident_wrong"]),
        held_out_accuracy=held["accuracy"],
        has_30min=bench.runnable,
        bench_passed=bench.under_90s,
    )
    payload = {
        "inventory": {
            "n_real_looking_videos": inventory["n_real_looking_videos"],
            "n_r10_clips": inventory["n_r10_clips"],
            "n_rofl": inventory["n_rofl"],
            "riot_match_ids": inventory["riot_match_ids"],
            "clock_crop_counts": inventory["clock_crop_counts"],
            "notes": inventory["notes"],
        },
        "ocr": {key: ocr[key] for key in ocr if key != "results"},
        "ocr_diversity": diversity,
        "h10": [row.to_dict() for row in h10_rows],
        "bench_30min": bench.to_dict(),
        "verdicts": verdicts.to_dict(),
        "catalog": dump_corpus(corpus),
    }
    print(json.dumps(payload, indent=2))


@corpus_app.command("show-checkpoints")
def show_checkpoints_cmd(
    path: Annotated[Path, typer.Argument()],
) -> None:
    """Print a checkpoint YAML after validating it is not H.10-derived."""
    labels = load_checkpoints(path)
    print(yaml.safe_dump({"corpus_id": labels.corpus_id, "n": len(labels.checkpoints)}))
