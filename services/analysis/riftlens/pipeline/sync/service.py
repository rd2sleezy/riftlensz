"""VIDEO auto-sync orchestration: ClockReading[] → fit → optional persist/cache.

Does not OCR-calibrate ROFL sources. Does not run RANSAC in the UI.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from riftlens.domain.clock_map import ClockMap
from riftlens.domain.clock_reading import ClockReading
from riftlens.domain.clock_store import SOURCE_TYPE_ROFL
from riftlens.domain.ids import new_ulid
from riftlens.domain.ports import (
    GameplayRepository,
    MatchRepository,
    MediaRepository,
    SyncMapRecord,
    SyncRepository,
)
from riftlens.domain.sync_map import SyncMap
from riftlens.pipeline.sync.cache import (
    lookup_cached,
    media_stub,
    persist_auto,
    sync_from_record,
)
from riftlens.pipeline.sync.errors import AutoSyncError, MediaUnavailable, UnsupportedSource
from riftlens.pipeline.sync.filter import CONFIDENCE_GATE
from riftlens.pipeline.sync.fitter import ALGO_VERSION, AutoFitResult, fit_auto_sync


@dataclass(frozen=True)
class AutoSyncOutcome:
    """API/desktop payload for a successful auto-sync, including cache hits."""

    sync_id: str | None
    sync_map: SyncMap
    clock_map: ClockMap
    cached: bool
    cache_hit_ms: int
    fit_ms: int
    verify_ms: int
    filter_accepted: int
    filter_rejected: int
    filter_reasons: dict[str, int]
    verify_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready success body. Assumes the SyncMap is valid."""
        return {
            "ok": True,
            "id": self.sync_id,
            "sync_map": self.sync_map.to_dict(),
            "clock_map": self.clock_map.to_dict(),
            "quality": self.sync_map.quality.verdict,
            "verified": self.sync_map.verified,
            "coverage": self.sync_map.quality.coverage,
            "cached": self.cached,
            "algo_version": ALGO_VERSION,
            "metrics": {
                "fit_ms": self.fit_ms,
                "verify_ms": self.verify_ms,
                "cache_hit_ms": self.cache_hit_ms,
                "n_readings": self.sync_map.quality.n_readings,
                "n_inliers": self.sync_map.quality.n_inliers,
                "residual_p95_ms": self.sync_map.quality.residual_p95_ms,
                "inlier_ratio": self.sync_map.quality.inlier_ratio,
            },
            "filter": {
                "accepted": self.filter_accepted,
                "rejected": self.filter_rejected,
                "reasons": self.filter_reasons,
            },
            "verify_reasons": list(self.verify_reasons),
        }


class AutoSyncService:
    """Fit and optionally persist VIDEO SyncMaps. Failed runs never upsert."""

    def __init__(
        self,
        *,
        syncs: SyncRepository | None = None,
        media: MediaRepository | None = None,
        matches: MatchRepository | None = None,
        gameplay: GameplayRepository | None = None,
    ) -> None:
        self._syncs = syncs
        self._media = media
        self._matches = matches
        self._gameplay = gameplay

    async def run(
        self,
        *,
        match_id: str,
        readings: Sequence[ClockReading] | None = None,
        video_path: str | None = None,
        video_duration_ms: int | None = None,
        match_duration_ms: int | None = None,
        media_asset_id: str = "",
        content_hash: str | None = None,
        gameplay_source_id: str | None = None,
        pause_end_game_ms: Sequence[int] = (),
        hz: float = 1.0,
        force: bool = False,
        persist: bool = True,
    ) -> AutoSyncOutcome:
        """Run H.9.1 (if needed) then H.10 fit. ROFL sources are rejected."""
        await self._reject_rofl(gameplay_source_id)
        hash_value = content_hash
        duration = video_duration_ms
        path = video_path
        asset_id = media_asset_id
        if path:
            hash_value, duration, asset_id = await self._ensure_media(
                path, duration_ms=duration, asset_id=asset_id
            )
        if not force and hash_value and self._syncs is not None and self._media is not None:
            cached = await self._cache_hit(hash_value, match_id)
            if cached is not None:
                return cached
        if readings is not None:
            resolved_readings = list(readings)
        else:
            resolved_readings = self._read_clocks(path, hz=hz)
        if duration is None or duration <= 0:
            duration = _duration_from_readings(resolved_readings)
        existing = await self._existing_row(asset_id, match_id)
        can_persist = persist and bool(asset_id) and self._syncs is not None
        if can_persist and self._matches is not None:
            match = await self._matches.get_match(match_id)
            can_persist = match is not None
        try:
            result = fit_auto_sync(
                resolved_readings,
                match_id=match_id,
                media_asset_id=asset_id,
                video_duration_ms=duration,
                match_duration_ms=match_duration_ms,
                pause_end_game_ms=pause_end_game_ms,
                confidence_gate=CONFIDENCE_GATE,
            )
        except AutoSyncError:
            raise
        sync_id = None
        if can_persist and self._syncs is not None:
            sync_id = await persist_auto(result, syncs=self._syncs, existing=existing)
        return _outcome_from_fit(result, sync_id=sync_id, cached=False, cache_hit_ms=0)

    async def get(self, sync_id: str) -> AutoSyncOutcome:
        """Load a persisted SyncMap. Assumes ``sync_id`` is a ULID."""
        if self._syncs is None:
            raise MediaUnavailable("Sync repository is not configured.")
        record = await self._syncs.get(sync_id)
        if record is None:
            raise MediaUnavailable(f"Sync map not found: {sync_id}")
        sync = sync_from_record(record)
        return AutoSyncOutcome(
            sync_id=record.id,
            sync_map=sync,
            clock_map=ClockMap.from_sync_map(sync),
            cached=True,
            cache_hit_ms=0,
            fit_ms=0,
            verify_ms=0,
            filter_accepted=sync.quality.n_inliers,
            filter_rejected=max(0, sync.quality.n_readings - sync.quality.n_inliers),
            filter_reasons={},
            verify_reasons=(),
        )

    async def _reject_rofl(self, gameplay_source_id: str | None) -> None:
        if not gameplay_source_id or self._gameplay is None:
            return
        snapshot = await self._gameplay.get_source(gameplay_source_id)
        if snapshot is None:
            return
        if snapshot.source.source_type == SOURCE_TYPE_ROFL:
            raise UnsupportedSource(
                "Automatic VIDEO sync does not apply to native League replay sources."
            )

    async def _cache_hit(self, content_hash: str, match_id: str) -> AutoSyncOutcome | None:
        assert self._syncs is not None and self._media is not None
        started = time.perf_counter()
        found = await lookup_cached(
            syncs=self._syncs, media=self._media, content_hash=content_hash, match_id=match_id
        )
        if found is None:
            return None
        sync, clock, sync_id = found
        hit_ms = max(0, int(round((time.perf_counter() - started) * 1000.0)))
        return AutoSyncOutcome(
            sync_id=sync_id,
            sync_map=sync,
            clock_map=clock,
            cached=True,
            cache_hit_ms=hit_ms,
            fit_ms=0,
            verify_ms=0,
            filter_accepted=sync.quality.n_inliers,
            filter_rejected=max(0, sync.quality.n_readings - sync.quality.n_inliers),
            filter_reasons={},
            verify_reasons=(),
        )

    async def _ensure_media(
        self, path: str, *, duration_ms: int | None, asset_id: str
    ) -> tuple[str, int, str]:
        resolved = Path(path).expanduser()
        if not resolved.is_file():
            raise MediaUnavailable(f"Video file not found: {resolved}")
        from riftlens.pipeline.ingest_video.probe import content_hash, probe

        hashed = content_hash(resolved)
        duration = duration_ms
        width = height = None
        codec = pix_fmt = None
        size_bytes = resolved.stat().st_size
        if duration is None:
            probed = probe(resolved)
            duration = probed.duration_ms
            width, height = probed.width, probed.height
            codec, pix_fmt = probed.codec_name, probed.pix_fmt
            hashed = probed.content_hash
            size_bytes = probed.size_bytes
        stored_id = asset_id
        if self._media is not None:
            existing = await self._media.get_by_content_hash(hashed)
            if existing is not None:
                stored_id = existing.id
                duration = existing.duration_ms
            else:
                stored_id = stored_id or new_ulid()
                await self._media.upsert_asset(
                    media_stub(
                        asset_id=stored_id,
                        content_hash=hashed,
                        path=str(resolved),
                        duration_ms=duration or 1,
                        size_bytes=size_bytes,
                        width=width,
                        height=height,
                        codec=codec,
                        pix_fmt=pix_fmt,
                    )
                )
        return hashed, int(duration or 0), stored_id

    async def _existing_row(self, asset_id: str, match_id: str) -> SyncMapRecord | None:
        if not asset_id or self._syncs is None:
            return None
        return await self._syncs.get_by_media_and_match(asset_id, match_id)

    def _read_clocks(self, path: str | None, *, hz: float) -> list[ClockReading]:
        if path is None:
            raise MediaUnavailable("VIDEO auto-sync needs clock readings or a video path.")
        from riftlens.vision.pipeline import collect_clock_readings

        _layout, readings = collect_clock_readings(path, hz=hz)
        return readings


def _outcome_from_fit(
    result: AutoFitResult, *, sync_id: str | None, cached: bool, cache_hit_ms: int
) -> AutoSyncOutcome:
    return AutoSyncOutcome(
        sync_id=sync_id,
        sync_map=result.sync_map,
        clock_map=result.clock_map,
        cached=cached,
        cache_hit_ms=cache_hit_ms,
        fit_ms=result.fit_ms,
        verify_ms=result.verify_ms,
        filter_accepted=result.filter_report.accepted,
        filter_rejected=result.filter_report.rejected,
        filter_reasons=dict(result.filter_report.reason_counts),
        verify_reasons=result.verify.reasons,
    )


def _duration_from_readings(readings: Sequence[ClockReading]) -> int:
    if not readings:
        return 1
    return max(item.t_video_ms for item in readings) + 1
