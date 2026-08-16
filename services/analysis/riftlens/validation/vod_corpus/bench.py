"""H.12-style 30-minute VIDEO performance measurement. Excludes LLM latency."""

from __future__ import annotations

import os
import platform
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from riftlens.pipeline.ingest_video.probe import probe
from riftlens.pipeline.sync.errors import AutoSyncError
from riftlens.pipeline.sync.service import AutoSyncService
from riftlens.validation.vod_corpus.kinds import MediaKind
from riftlens.validation.vod_corpus.manifest import VodEntry
from riftlens.validation.vod_corpus.resolve import resolve_media_ref
from riftlens.vision.pipeline import collect_clock_readings

APPROX_30_MIN_MS = 25 * 60 * 1000
TARGET_TOTAL_MS = 90 * 1000


@dataclass(frozen=True)
class BenchResult:
    """One 30-minute-class run, or a blocked skip."""

    runnable: bool
    blocked_reason: str | None
    machine: str
    cpu: str
    cpu_count: int | None
    media_duration_ms: int | None
    resolution: str | None
    fps: str | None
    video_ocr_ms: int | None
    h10_fit_ms: int | None
    deterministic_ms: int | None
    total_excluding_llm_ms: int | None
    under_90s: bool | None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready bench row."""
        return asdict(self)


def machine_info() -> dict[str, Any]:
    """Return host identifiers for the performance report."""
    return {
        "machine": platform.platform(),
        "cpu": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
    }


def is_suitable_30min(entry: VodEntry, *, duration_ms: int | None) -> bool:
    """True when this is REAL user VIDEO of approximately 30 minutes."""
    if entry.kind is not MediaKind.REAL:
        return False
    if duration_ms is None:
        duration_ms = entry.duration_ms
    if duration_ms is None:
        return False
    return int(duration_ms) >= APPROX_30_MIN_MS


def blocked_30min(reason: str) -> BenchResult:
    """Return a blocked bench row. Does not invent a 17s substitute."""
    info = machine_info()
    return BenchResult(
        runnable=False,
        blocked_reason=reason,
        machine=str(info["machine"]),
        cpu=str(info["cpu"]),
        cpu_count=info["cpu_count"] if isinstance(info["cpu_count"], int) else None,
        media_duration_ms=None,
        resolution=None,
        fps=None,
        video_ocr_ms=None,
        h10_fit_ms=None,
        deterministic_ms=None,
        total_excluding_llm_ms=None,
        under_90s=None,
        notes="R.10 clips and synthetic videos are not evidence for the 30-minute gate.",
    )


def run_30min_bench(
    entry: VodEntry,
    *,
    allow_absolute: bool = False,
    hz: float = 1.0,
    deterministic_fn: Any | None = None,
) -> BenchResult:
    """Time OCR + H.10 + optional deterministic analysis. Skips LLM."""
    info = machine_info()
    try:
        path = resolve_media_ref(entry.media_ref, allow_absolute=allow_absolute)
    except ValueError as exc:
        return blocked_30min(str(exc))
    if not path.is_file():
        return blocked_30min(f"media not found: {path}")
    probed = probe(path)
    if not is_suitable_30min(entry, duration_ms=probed.duration_ms):
        return blocked_30min(
            f"{entry.id} is {entry.kind.value} duration_ms={probed.duration_ms}; "
            f"need REAL ≥{APPROX_30_MIN_MS} ms"
        )
    ocr_started = time.perf_counter()
    _layout, readings = collect_clock_readings(path, hz=hz)
    ocr_ms = _ms(ocr_started)
    fit_started = time.perf_counter()
    fit_ms = 0
    try:
        import asyncio

        asyncio.run(
            AutoSyncService().run(
                match_id=entry.match_id or entry.id,
                readings=readings,
                video_path=str(path),
                persist=False,
                force=True,
            )
        )
        fit_ms = _ms(fit_started)
    except AutoSyncError as exc:
        fit_ms = _ms(fit_started)
        det_ms = _run_deterministic(deterministic_fn)
        total = ocr_ms + fit_ms + det_ms
        return BenchResult(
            runnable=True,
            blocked_reason=None,
            machine=str(info["machine"]),
            cpu=str(info["cpu"]),
            cpu_count=info["cpu_count"] if isinstance(info["cpu_count"], int) else None,
            media_duration_ms=probed.duration_ms,
            resolution=f"{probed.width}x{probed.height}",
            fps=probed.avg_frame_rate,
            video_ocr_ms=ocr_ms,
            h10_fit_ms=fit_ms,
            deterministic_ms=det_ms,
            total_excluding_llm_ms=total,
            under_90s=total < TARGET_TOTAL_MS,
            notes=f"H.10 failed: {exc.code} {exc.message}",
        )
    det_ms = _run_deterministic(deterministic_fn)
    total = ocr_ms + fit_ms + det_ms
    return BenchResult(
        runnable=True,
        blocked_reason=None,
        machine=str(info["machine"]),
        cpu=str(info["cpu"]),
        cpu_count=info["cpu_count"] if isinstance(info["cpu_count"], int) else None,
        media_duration_ms=probed.duration_ms,
        resolution=f"{probed.width}x{probed.height}",
        fps=probed.avg_frame_rate,
        video_ocr_ms=ocr_ms,
        h10_fit_ms=fit_ms,
        deterministic_ms=det_ms,
        total_excluding_llm_ms=total,
        under_90s=total < TARGET_TOTAL_MS,
        notes="",
    )


def _run_deterministic(fn: Any | None) -> int:
    if fn is None:
        return 0
    started = time.perf_counter()
    fn()
    return _ms(started)


def _ms(started: float) -> int:
    return max(0, int(round((time.perf_counter() - started) * 1000.0)))


def pick_30min_entry(entries: list[VodEntry], *, resolved: dict[str, Path]) -> VodEntry | None:
    """Return the first REAL entry with resolved duration ≥ approx 30 minutes."""
    for entry in entries:
        path = resolved.get(entry.id)
        duration = entry.duration_ms
        if path is not None and path.is_file():
            try:
                duration = probe(path).duration_ms
            except Exception:  # noqa: BLE001 — bench skip path
                duration = entry.duration_ms
        if is_suitable_30min(entry, duration_ms=duration):
            return entry
    return None
