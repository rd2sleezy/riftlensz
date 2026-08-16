"""Lightweight REAL VIDEO corpus manifest. Media files are never stored here."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from riftlens.validation.vod_corpus.kinds import (
    ACCEPTANCE_KINDS,
    ATLAS_TRAIN_MATCH_IDS,
    CoverageKind,
    MediaKind,
)
from riftlens.validation.vod_corpus.resolve import is_absolute_ref, is_portable_ref

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class VodEntry:
    """One catalogued recording. ``media_ref`` is portable in committed fixtures."""

    id: str
    kind: MediaKind
    media_ref: str
    match_id: str | None = None
    source_recorder: str | None = None
    resolution_width: int | None = None
    resolution_height: int | None = None
    fps: float | None = None
    duration_ms: int | None = None
    coverage: CoverageKind = CoverageKind.PARTIAL
    recording_starts_mid_game: bool | None = None
    known_pause: bool | None = None
    hud_scale: float | None = None
    checkpoint_file: str | None = None
    content_hash: str | None = None
    notes: str = ""

    @property
    def counts_toward_h10_acceptance(self) -> bool:
        """True only for REAL user gameplay VIDEO (full or partial)."""
        return self.kind in ACCEPTANCE_KINDS

    @property
    def counts_toward_h12_video(self) -> bool:
        """H.12 VIDEO gates use the same REAL-only rule as H.10 acceptance."""
        return self.counts_toward_h10_acceptance

    @property
    def resolution_label(self) -> str | None:
        if self.resolution_width is None or self.resolution_height is None:
            return None
        return f"{self.resolution_width}x{self.resolution_height}"


@dataclass(frozen=True)
class VodCorpus:
    """Committed (and optional local-overlay) catalog."""

    schema_version: int
    entries: tuple[VodEntry, ...]
    atlas_train_match_ids: frozenset[str] = field(default_factory=lambda: ATLAS_TRAIN_MATCH_IDS)
    notes: str = ""
    source_path: Path | None = None

    def by_id(self) -> dict[str, VodEntry]:
        """Return entries keyed by corpus id. Assumes ids are unique."""
        return {item.id: item for item in self.entries}

    def real_entries(self) -> tuple[VodEntry, ...]:
        """Return REAL user-gameplay entries only."""
        return tuple(item for item in self.entries if item.counts_toward_h10_acceptance)


def default_corpus_root() -> Path:
    """Return the committed vod_corpus fixture directory."""
    return Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "vision" / "vod_corpus"


def default_local_overlay() -> Path:
    """Return ``~/.riftlens/vod_corpus/local.yaml`` (uncommitted)."""
    return Path.home() / ".riftlens" / "vod_corpus" / "local.yaml"


def load_corpus(
    path: Path | None = None,
    *,
    overlay: Path | None | bool = None,
    require_portable: bool = True,
) -> VodCorpus:
    """Load YAML catalog. Overlay entries replace/extend by id.

    Pass ``overlay=False`` to skip ``~/.riftlens/vod_corpus/local.yaml``.
    """
    root = path or (default_corpus_root() / "manifest.yaml")
    payload = _read_yaml(root)
    corpus = corpus_from_mapping(payload, source_path=root, require_portable=require_portable)
    if overlay is False:
        return corpus
    overlay_path = overlay if isinstance(overlay, Path) else default_local_overlay()
    if overlay_path.is_file():
        extra = corpus_from_mapping(
            _read_yaml(overlay_path),
            source_path=overlay_path,
            require_portable=False,
        )
        corpus = merge_corpus(corpus, extra)
    return corpus


def corpus_from_mapping(
    payload: Mapping[str, Any],
    *,
    source_path: Path | None = None,
    require_portable: bool = True,
) -> VodCorpus:
    """Parse a mapping produced by the YAML catalog."""
    version = int(payload.get("schema_version") or SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise ValueError(f"unsupported vod corpus schema_version: {version}")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("vod corpus entries must be a list")
    entries = tuple(
        _entry_from_mapping(item, require_portable=require_portable) for item in raw_entries
    )
    ids = [item.id for item in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("vod corpus ids must be unique")
    atlas_raw = payload.get("atlas_train_match_ids")
    atlas = (
        frozenset(str(item) for item in atlas_raw)
        if isinstance(atlas_raw, list)
        else ATLAS_TRAIN_MATCH_IDS
    )
    return VodCorpus(
        schema_version=version,
        entries=entries,
        atlas_train_match_ids=atlas,
        notes=str(payload.get("notes") or ""),
        source_path=source_path,
    )


def merge_corpus(base: VodCorpus, overlay: VodCorpus) -> VodCorpus:
    """Replace or append overlay entries by id. Overlay atlas ids are unioned."""
    merged = dict(base.by_id())
    merged.update(overlay.by_id())
    return VodCorpus(
        schema_version=base.schema_version,
        entries=tuple(merged.values()),
        atlas_train_match_ids=base.atlas_train_match_ids | overlay.atlas_train_match_ids,
        notes=base.notes,
        source_path=base.source_path,
    )


def validate_committed_portable(corpus: VodCorpus) -> list[str]:
    """Return errors when committed entries use machine-specific paths."""
    errors: list[str] = []
    for entry in corpus.entries:
        if not is_portable_ref(entry.media_ref):
            errors.append(f"{entry.id}: media_ref is not portable: {entry.media_ref}")
        if is_absolute_ref(entry.media_ref):
            errors.append(f"{entry.id}: absolute media_ref is forbidden in committed fixtures")
    return errors


def _entry_from_mapping(raw: object, *, require_portable: bool) -> VodEntry:
    if not isinstance(raw, Mapping):
        raise ValueError("vod corpus entry must be a mapping")
    media_ref = str(raw["media_ref"])
    if require_portable and not is_portable_ref(media_ref):
        raise ValueError(f"committed media_ref must be r10:// or vod://: {media_ref}")
    return VodEntry(
        id=str(raw["id"]),
        kind=MediaKind(str(raw["kind"])),
        media_ref=media_ref,
        match_id=_optional_str(raw.get("match_id")),
        source_recorder=_optional_str(raw.get("source_recorder")),
        resolution_width=_optional_int(raw.get("resolution_width")),
        resolution_height=_optional_int(raw.get("resolution_height")),
        fps=_optional_float(raw.get("fps")),
        duration_ms=_optional_int(raw.get("duration_ms")),
        coverage=CoverageKind(str(raw.get("coverage") or CoverageKind.PARTIAL)),
        recording_starts_mid_game=_optional_bool(raw.get("recording_starts_mid_game")),
        known_pause=_optional_bool(raw.get("known_pause")),
        hud_scale=_optional_float(raw.get("hud_scale")),
        checkpoint_file=_optional_str(raw.get("checkpoint_file")),
        content_hash=_optional_str(raw.get("content_hash")),
        notes=str(raw.get("notes") or ""),
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"corpus YAML must be a mapping: {path}")
    return data


def _optional_str(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(str(value))


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(str(value))


def _optional_bool(value: object) -> bool | None:
    if value is None or value == "":
        return None
    return bool(value)


def dump_corpus(corpus: VodCorpus) -> dict[str, Any]:
    """Return a YAML-serializable mapping. Assumes entries were already validated."""
    return {
        "schema_version": corpus.schema_version,
        "atlas_train_match_ids": sorted(corpus.atlas_train_match_ids),
        "notes": corpus.notes,
        "entries": [_dump_entry(item) for item in corpus.entries],
    }


def _dump_entry(entry: VodEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "kind": entry.kind.value,
        "media_ref": entry.media_ref,
        "match_id": entry.match_id,
        "source_recorder": entry.source_recorder,
        "resolution_width": entry.resolution_width,
        "resolution_height": entry.resolution_height,
        "fps": entry.fps,
        "duration_ms": entry.duration_ms,
        "coverage": entry.coverage.value,
        "recording_starts_mid_game": entry.recording_starts_mid_game,
        "known_pause": entry.known_pause,
        "hud_scale": entry.hud_scale,
        "checkpoint_file": entry.checkpoint_file,
        "content_hash": entry.content_hash,
        "notes": entry.notes,
        "counts_toward_h10_acceptance": entry.counts_toward_h10_acceptance,
    }
