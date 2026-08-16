"""Run production H.10 auto-sync against a catalogued VOD + independent checkpoints."""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from riftlens.domain.clock_reading import ClockReading
from riftlens.domain.sync_map import SyncMap
from riftlens.pipeline.sync.errors import AutoSyncError
from riftlens.pipeline.sync.filter import filter_readings
from riftlens.pipeline.sync.service import AutoSyncService
from riftlens.validation.vod_corpus.checkpoints import (
    Checkpoint,
    CheckpointSet,
    error_stats,
    errors_against_map,
    load_checkpoints,
)
from riftlens.validation.vod_corpus.kinds import FailureClass
from riftlens.validation.vod_corpus.manifest import VodEntry
from riftlens.validation.vod_corpus.resolve import resolve_media_ref
from riftlens.vision.pipeline import collect_clock_readings

_CODE_TO_FAILURE: dict[str, FailureClass] = {
    "INSUFFICIENT_READINGS": FailureClass.OCR_INSUFFICIENT,
    "INCONSISTENT_OCR": FailureClass.OCR_CONFIDENTLY_WRONG,
    "NO_STABLE_MODEL": FailureClass.OTHER,
    "MULTIPLE_GAMES": FailureClass.MULTI_GAME_DETECTION,
    "INSUFFICIENT_COVERAGE": FailureClass.INSUFFICIENT_COVERAGE,
    "VERIFICATION_FAILED": FailureClass.VERIFICATION_FAILURE,
    "UNSUPPORTED_SOURCE": FailureClass.INCORRECT_MATCH_PAIRING,
    "MEDIA_UNAVAILABLE": FailureClass.OTHER,
}


@dataclass(frozen=True)
class VodH10Result:
    """Per-recording production H.10 outcome plus independent checkpoint errors."""

    corpus_id: str
    kind: str
    counts_toward_acceptance: bool
    media_resolved: bool
    match_id: str | None
    ocr_attempted: int
    ocr_readable: int
    ocr_abstentions: int
    filter_accepted: int
    filter_rejected: int
    sync_ok: bool
    sync_error_code: str | None
    quality: str | None
    verified: bool | None
    n_segments: int | None
    coverage: float | None
    residual_p50_ms: float | None
    residual_p95_ms: float | None
    residual_max_ms: float | None
    checkpoint_n: int
    checkpoint_n_covered: int
    checkpoint_p50_ms: float | None
    checkpoint_p95_ms: float | None
    checkpoint_max_ms: float | None
    runtime_ocr_ms: int
    runtime_fit_ms: int
    runtime_total_ms: int
    failure_class: str | None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready row. Assumes the result was already computed."""
        return asdict(self)


def evaluate_entry(
    entry: VodEntry,
    *,
    checkpoints: CheckpointSet | None = None,
    corpus_root: Path | None = None,
    hz: float = 1.0,
    allow_absolute: bool = False,
    persist: bool = False,
) -> VodH10Result:
    """Run H.9.1 sampling + production ``AutoSyncService`` (no spike fitter)."""
    started = time.perf_counter()
    try:
        path = resolve_media_ref(entry.media_ref, allow_absolute=allow_absolute)
    except ValueError as exc:
        return _unavailable(entry, notes=str(exc), started=started)
    if not path.is_file():
        return _unavailable(entry, notes=f"media not found: {path}", started=started)
    labels = checkpoints or _load_entry_checkpoints(entry, corpus_root)
    ocr_started = time.perf_counter()
    _layout, readings = collect_clock_readings(path, hz=hz)
    ocr_ms = _elapsed_ms(ocr_started)
    readable = [item for item in readings if item.is_readable]
    _accepted, filt = filter_readings(readings)
    fit_started = time.perf_counter()
    try:
        outcome = _fit(entry, readings, path)
    except AutoSyncError as exc:
        fit_ms = _elapsed_ms(fit_started)
        return _from_error(
            entry,
            readings=readings,
            readable=readable,
            filt_accepted=filt.accepted,
            filt_rejected=filt.rejected,
            exc=exc,
            labels=labels,
            ocr_ms=ocr_ms,
            fit_ms=fit_ms,
            started=started,
        )
    fit_ms = _elapsed_ms(fit_started)
    return _from_success(
        entry,
        readings=readings,
        readable=readable,
        outcome=outcome,
        labels=labels,
        ocr_ms=ocr_ms,
        fit_ms=fit_ms,
        started=started,
        persist=persist,
    )


def classify_failure(
    *,
    sync_ok: bool,
    sync_error_code: str | None,
    checkpoint_p95_ms: float | None,
    checkpoint_n_covered: int,
    checkpoint_n: int,
) -> FailureClass | None:
    """Prefer abstention over a plausible-looking wrong SyncMap."""
    if not sync_ok:
        if sync_error_code and sync_error_code in _CODE_TO_FAILURE:
            return _CODE_TO_FAILURE[sync_error_code]
        return FailureClass.OTHER
    if checkpoint_n > 0 and checkpoint_n_covered == 0:
        return FailureClass.INSUFFICIENT_COVERAGE
    if checkpoint_p95_ms is not None and checkpoint_p95_ms > 500:
        return FailureClass.WRONG_SYNC
    return None


def _fit(entry: VodEntry, readings: Sequence[ClockReading], path: Path) -> Any:
    service = AutoSyncService()
    import asyncio

    return asyncio.run(
        service.run(
            match_id=entry.match_id or entry.id,
            readings=list(readings),
            video_path=str(path),
            persist=False,
            force=True,
        )
    )


def _from_success(
    entry: VodEntry,
    *,
    readings: Sequence[ClockReading],
    readable: Sequence[ClockReading],
    outcome: Any,
    labels: CheckpointSet | None,
    ocr_ms: int,
    fit_ms: int,
    started: float,
    persist: bool,
) -> VodH10Result:
    del persist
    sync: SyncMap = outcome.sync_map
    quality = sync.quality
    ck = _checkpoint_block(labels, sync)
    failure = classify_failure(
        sync_ok=True,
        sync_error_code=None,
        checkpoint_p95_ms=ck["p95_ms"] if isinstance(ck["p95_ms"], float) else None,
        checkpoint_n_covered=int(ck["n_covered"] or 0),
        checkpoint_n=int(ck["n"] or 0),
    )
    residuals = _segment_max_residual(sync)
    return VodH10Result(
        corpus_id=entry.id,
        kind=entry.kind.value,
        counts_toward_acceptance=entry.counts_toward_h10_acceptance,
        media_resolved=True,
        match_id=entry.match_id,
        ocr_attempted=len(readings),
        ocr_readable=len(readable),
        ocr_abstentions=len(readings) - len(readable),
        filter_accepted=outcome.filter_accepted,
        filter_rejected=outcome.filter_rejected,
        sync_ok=True,
        sync_error_code=None,
        quality=quality.verdict,
        verified=sync.verified,
        n_segments=len(sync.segments),
        coverage=quality.coverage,
        residual_p50_ms=quality.residual_p50_ms,
        residual_p95_ms=quality.residual_p95_ms,
        residual_max_ms=residuals,
        checkpoint_n=int(ck["n"] or 0),
        checkpoint_n_covered=int(ck["n_covered"] or 0),
        checkpoint_p50_ms=_as_float(ck["p50_ms"]),
        checkpoint_p95_ms=_as_float(ck["p95_ms"]),
        checkpoint_max_ms=_as_float(ck["max_ms"]),
        runtime_ocr_ms=ocr_ms,
        runtime_fit_ms=fit_ms,
        runtime_total_ms=_elapsed_ms(started),
        failure_class=None if failure is None else failure.value,
        notes=entry.notes,
    )


def _from_error(
    entry: VodEntry,
    *,
    readings: Sequence[ClockReading],
    readable: Sequence[ClockReading],
    filt_accepted: int,
    filt_rejected: int,
    exc: AutoSyncError,
    labels: CheckpointSet | None,
    ocr_ms: int,
    fit_ms: int,
    started: float,
) -> VodH10Result:
    ck = _checkpoint_block(labels, None)
    failure = classify_failure(
        sync_ok=False,
        sync_error_code=exc.code,
        checkpoint_p95_ms=None,
        checkpoint_n_covered=0,
        checkpoint_n=int(ck["n"] or 0),
    )
    return VodH10Result(
        corpus_id=entry.id,
        kind=entry.kind.value,
        counts_toward_acceptance=entry.counts_toward_h10_acceptance,
        media_resolved=True,
        match_id=entry.match_id,
        ocr_attempted=len(readings),
        ocr_readable=len(readable),
        ocr_abstentions=len(readings) - len(readable),
        filter_accepted=filt_accepted,
        filter_rejected=filt_rejected,
        sync_ok=False,
        sync_error_code=exc.code,
        quality=None,
        verified=None,
        n_segments=None,
        coverage=None,
        residual_p50_ms=None,
        residual_p95_ms=None,
        residual_max_ms=None,
        checkpoint_n=int(ck["n"] or 0),
        checkpoint_n_covered=int(ck["n_covered"] or 0),
        checkpoint_p50_ms=None,
        checkpoint_p95_ms=None,
        checkpoint_max_ms=None,
        runtime_ocr_ms=ocr_ms,
        runtime_fit_ms=fit_ms,
        runtime_total_ms=_elapsed_ms(started),
        failure_class=None if failure is None else failure.value,
        notes=f"{entry.notes} | {exc.message}".strip(" |"),
    )


def _unavailable(entry: VodEntry, *, notes: str, started: float) -> VodH10Result:
    return VodH10Result(
        corpus_id=entry.id,
        kind=entry.kind.value,
        counts_toward_acceptance=entry.counts_toward_h10_acceptance,
        media_resolved=False,
        match_id=entry.match_id,
        ocr_attempted=0,
        ocr_readable=0,
        ocr_abstentions=0,
        filter_accepted=0,
        filter_rejected=0,
        sync_ok=False,
        sync_error_code="MEDIA_UNAVAILABLE",
        quality=None,
        verified=None,
        n_segments=None,
        coverage=None,
        residual_p50_ms=None,
        residual_p95_ms=None,
        residual_max_ms=None,
        checkpoint_n=0,
        checkpoint_n_covered=0,
        checkpoint_p50_ms=None,
        checkpoint_p95_ms=None,
        checkpoint_max_ms=None,
        runtime_ocr_ms=0,
        runtime_fit_ms=0,
        runtime_total_ms=_elapsed_ms(started),
        failure_class=FailureClass.OTHER.value,
        notes=notes,
    )


def _load_entry_checkpoints(entry: VodEntry, corpus_root: Path | None) -> CheckpointSet | None:
    if not entry.checkpoint_file:
        return None
    root = corpus_root or Path()
    path = root / entry.checkpoint_file
    if not path.is_file():
        return None
    return load_checkpoints(path)


def _checkpoint_block(
    labels: CheckpointSet | None, sync: SyncMap | None
) -> dict[str, float | int | None]:
    empty: dict[str, float | int | None] = {
        "n": 0,
        "n_covered": 0,
        "n_uncovered": 0,
        "p50_ms": None,
        "p95_ms": None,
        "max_ms": None,
    }
    if labels is None or not labels.checkpoints:
        return empty
    if sync is None:
        return {
            "n": len(labels.checkpoints),
            "n_covered": 0,
            "n_uncovered": len(labels.checkpoints),
            "p50_ms": None,
            "p95_ms": None,
            "max_ms": None,
        }
    rows = errors_against_map(labels.checkpoints, video_to_game=sync.video_to_game)
    return error_stats(rows)


def _segment_max_residual(sync: SyncMap) -> float | None:
    if not sync.segments:
        return None
    return max(float(item.residual_p95_ms) for item in sync.segments)


def _elapsed_ms(started: float) -> int:
    return max(0, int(round((time.perf_counter() - started) * 1000.0)))


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    return float(str(value))


def evaluate_readings_only(
    entry: VodEntry,
    readings: Sequence[ClockReading],
    checkpoints: Sequence[Checkpoint],
    *,
    video_duration_ms: int,
) -> VodH10Result:
    """Deterministic H.10 fit used by unit tests (no video I/O)."""
    started = time.perf_counter()
    readable = [item for item in readings if item.is_readable]
    _accepted, filt = filter_readings(readings)
    from types import SimpleNamespace

    from riftlens.pipeline.sync.fitter import fit_auto_sync

    labels = CheckpointSet(
        corpus_id=entry.id, label_basis="manual_visual", checkpoints=tuple(checkpoints)
    )
    try:
        result = fit_auto_sync(
            readings,
            match_id=entry.match_id or entry.id,
            video_duration_ms=video_duration_ms,
        )
    except AutoSyncError as exc:
        return _from_error(
            entry,
            readings=readings,
            readable=readable,
            filt_accepted=filt.accepted,
            filt_rejected=filt.rejected,
            exc=exc,
            labels=labels,
            ocr_ms=0,
            fit_ms=_elapsed_ms(started),
            started=started,
        )

    outcome = SimpleNamespace(
        sync_map=result.sync_map,
        filter_accepted=result.filter_report.accepted,
        filter_rejected=result.filter_report.rejected,
    )
    return _from_success(
        entry,
        readings=readings,
        readable=readable,
        outcome=outcome,
        labels=labels,
        ocr_ms=0,
        fit_ms=result.fit_ms,
        started=started,
        persist=False,
    )
