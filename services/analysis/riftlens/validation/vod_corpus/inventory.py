"""Scan local disks for League-looking VIDEO / ROFL. Does not download anything."""

from __future__ import annotations

import gzip
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from riftlens.validation.vod_corpus.kinds import MediaKind

VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".webm"}
ROFL_SUFFIXES = {".rofl"}
_LEAGUE_TOKENS = (
    "league",
    "riftlens",
    "na1_",
    "na1-",
    "euw1",
    "kr_",
    "kr-",
    "captures",
)
_SKIP_DIR_NAMES = {
    "node_modules",
    ".git",
    "Library",
    "Applications",
    "CapCut",
    "iMovie.app",
}


@dataclass(frozen=True)
class InventoryHit:
    """One local file that might be relevant to VIDEO/ROFL validation."""

    path: str
    suffix: str
    size_bytes: int
    kind_guess: MediaKind | None
    league_looking: bool
    notes: str = ""


@dataclass(frozen=True)
class InventoryReport:
    """Result of a local scan. Media is never copied into the repo."""

    video_hits: tuple[InventoryHit, ...]
    rofl_hits: tuple[InventoryHit, ...]
    r10_clips: tuple[InventoryHit, ...]
    riot_match_ids: tuple[str, ...]
    clock_crop_counts: dict[str, int]
    notes: tuple[str, ...]


def default_search_roots() -> list[Path]:
    """Return typical user-media locations on this machine."""
    home = Path.home()
    return [
        home / "Movies",
        home / "Videos",
        home / "Documents",
        home / "Desktop",
        home / "Downloads",
        home / ".riftlens",
        home / "Documents" / "League of Legends",
    ]


def guess_kind(path: Path) -> tuple[MediaKind | None, bool, str]:
    """Classify a path without decoding. Unrelated stock footage is not League."""
    text = str(path).lower()
    name = path.name.lower()
    if path.suffix.lower() in ROFL_SUFFIXES:
        return None, True, "native_rofl"
    if "/.riftlens/captures/" in text.replace("\\", "/") or "r10" in name:
        return MediaKind.R10_CLIP, True, "r10_capture_tree"
    league = any(token in text for token in _LEAGUE_TOKENS)
    if league and path.suffix.lower() in VIDEO_SUFFIXES:
        if "replay" in text or "generated" in text:
            return MediaKind.REPLAY_GENERATED, True, "filename_replay_generated"
        return MediaKind.REAL, True, "filename_league_token"
    return None, False, "not_league_looking"


def scan_roots(
    roots: Sequence[Path] | None = None,
    *,
    max_depth: int = 6,
) -> InventoryReport:
    """Walk ``roots`` for video/ROFL. Skips Application bundles and node_modules."""
    hits: list[InventoryHit] = []
    for root in roots or default_search_roots():
        if not root.exists():
            continue
        hits.extend(_walk(root, max_depth=max_depth))
    unique: dict[str, InventoryHit] = {}
    for hit in hits:
        unique[hit.path] = hit
    hits = list(unique.values())
    videos = tuple(
        h for h in hits if h.suffix in VIDEO_SUFFIXES and h.kind_guess != MediaKind.R10_CLIP
    )
    r10 = tuple(h for h in hits if h.kind_guess is MediaKind.R10_CLIP)
    rofl = tuple(h for h in hits if h.suffix in ROFL_SUFFIXES)
    notes = []
    real_full = [h for h in videos if h.kind_guess is MediaKind.REAL]
    if len(real_full) < 10:
        notes.append(
            f"REAL league-looking videos found: {len(real_full)} (need ≥10 for H.10 acceptance)"
        )
    return InventoryReport(
        video_hits=videos,
        rofl_hits=rofl,
        r10_clips=r10,
        riot_match_ids=tuple(_riot_match_ids()),
        clock_crop_counts=_clock_crop_counts(),
        notes=tuple(notes),
    )


def report_to_dict(report: InventoryReport) -> dict[str, Any]:
    """JSON-ready inventory. Paths stay local and are not a committed fixture."""

    def _hit(item: InventoryHit) -> dict[str, Any]:
        return {
            "path": item.path,
            "suffix": item.suffix,
            "size_bytes": item.size_bytes,
            "kind_guess": None if item.kind_guess is None else item.kind_guess.value,
            "league_looking": item.league_looking,
            "notes": item.notes,
        }

    return {
        "video_hits": [_hit(item) for item in report.video_hits],
        "rofl_hits": [_hit(item) for item in report.rofl_hits],
        "r10_clips": [_hit(item) for item in report.r10_clips],
        "riot_match_ids": list(report.riot_match_ids),
        "clock_crop_counts": dict(report.clock_crop_counts),
        "notes": list(report.notes),
        "n_real_looking_videos": sum(
            1 for item in report.video_hits if item.kind_guess is MediaKind.REAL
        ),
        "n_r10_clips": len(report.r10_clips),
        "n_rofl": len(report.rofl_hits),
    }


def _walk(root: Path, *, max_depth: int) -> list[InventoryHit]:
    out: list[InventoryHit] = []
    root = root.expanduser()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if len(rel.parts) > max_depth:
            continue
        if any(part in _SKIP_DIR_NAMES for part in path.parts):
            continue
        suffix = path.suffix.lower()
        if suffix not in VIDEO_SUFFIXES and suffix not in ROFL_SUFFIXES:
            continue
        kind, league, notes = guess_kind(path)
        out.append(
            InventoryHit(
                path=str(path),
                suffix=suffix,
                size_bytes=path.stat().st_size,
                kind_guess=kind,
                league_looking=league,
                notes=notes,
            )
        )
    return out


def _riot_match_ids() -> list[str]:
    cache = Path.home() / ".riftlens" / "cache" / "riot"
    if not cache.is_dir():
        return []
    found: set[str] = set()
    for path in cache.rglob("*.json.gz"):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        meta = payload.get("metadata")
        if isinstance(meta, dict) and meta.get("matchId"):
            found.add(str(meta["matchId"]))
    return sorted(found)


def _clock_crop_counts() -> dict[str, int]:
    root = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "vision" / "clock_corpus"
    manifest = root / "manifest.json"
    if not manifest.is_file():
        return {}
    data = json.loads(manifest.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    if not isinstance(data, list):
        return counts
    for sample in data:
        if not isinstance(sample, dict):
            continue
        key = str(sample.get("source_type") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts
