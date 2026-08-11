"""Capture retention and GC (§7.4). PINNED artifacts are never evicted by size pressure."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from riftlens.domain.capture import (
    PARTIAL_STATUSES,
    CaptureStatus,
    RetentionClass,
)
from riftlens.domain.ports import CaptureIntervalRecord, CaptureRepository
from riftlens.replay_host.capture import artifact_store

DEFAULT_MAX_TOTAL_BYTES = 8 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class RetentionPolicy:
    """Size ceiling for the capture root. LRU eviction skips PINNED captures."""

    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES


@dataclass
class CleanupReport:
    """What one cleanup pass removed. Empty lists mean nothing matched."""

    deleted_capture_ids: list[str] = field(default_factory=list)
    deleted_directories: list[str] = field(default_factory=list)
    freed_bytes: int = 0

    def merge(self, other: CleanupReport) -> CleanupReport:
        """Return the union of two passes. Assumes ids do not overlap."""
        return CleanupReport(
            deleted_capture_ids=[*self.deleted_capture_ids, *other.deleted_capture_ids],
            deleted_directories=[*self.deleted_directories, *other.deleted_directories],
            freed_bytes=self.freed_bytes + other.freed_bytes,
        )


class RetentionService:
    """Deletes capture rows and their directories. Owns the only file-deleting code path."""

    def __init__(
        self,
        *,
        captures: CaptureRepository,
        captures_dir: Path,
        policy: RetentionPolicy | None = None,
    ) -> None:
        self._captures = captures
        self._root = Path(captures_dir)
        self._policy = policy if policy is not None else RetentionPolicy()

    async def cleanup_ephemeral(self) -> CleanupReport:
        """Delete EPHEMERAL captures. Called at session teardown, never mid-capture."""
        rows = await self._captures.list_ephemeral()
        return await self._delete_all(rows)

    async def cleanup_review(self, review_id: str) -> CleanupReport:
        """Delete every capture charged to ``review_id``. Used when a review is deleted."""
        rows = await self._captures.list_for_review(review_id)
        return await self._delete_all(rows)

    async def cleanup_partials(self) -> CleanupReport:
        """Delete failed/cancelled captures and their leftover directories."""
        rows = await self._captures.list_by_status(
            sorted(status.value for status in PARTIAL_STATUSES)
        )
        return await self._delete_all(rows)

    async def enforce_size_ceiling(self) -> CleanupReport:
        """Evict oldest non-PINNED captures until the root fits the policy ceiling."""
        total = artifact_store.directory_size(self._root)
        if total <= self._policy.max_total_bytes:
            return CleanupReport()
        rows = list(await self._captures.list_all())
        evictable = [
            row
            for row in rows
            if row.retention_class != RetentionClass.PINNED.value
        ]
        report = CleanupReport()
        for row in evictable:
            if total <= self._policy.max_total_bytes:
                break
            single = await self._delete_one(row)
            total -= single.freed_bytes
            report = report.merge(single)
        return report

    async def startup_gc(self) -> CleanupReport:
        """Remove partials, then orphan directories, then enforce the size ceiling."""
        report = await self.cleanup_partials()
        report = report.merge(await self.remove_orphan_directories())
        return report.merge(await self.enforce_size_ceiling())

    async def remove_orphan_directories(self) -> CleanupReport:
        """Delete capture directories with no matching row. Never touches unknown roots."""
        if not self._root.is_dir():
            return CleanupReport()
        known = {row.id for row in await self._captures.list_all()}
        report = CleanupReport()
        for match_dir in sorted(self._root.iterdir()):
            if not match_dir.is_dir():
                continue
            for capture_dir in sorted(match_dir.iterdir()):
                if not capture_dir.is_dir() or capture_dir.name in known:
                    continue
                report.freed_bytes += artifact_store.directory_size(capture_dir)
                artifact_store.delete_capture_dir(capture_dir)
                report.deleted_directories.append(str(capture_dir))
            artifact_store.prune_empty_parents(match_dir, stop_at=self._root)
        return report

    def directory_for(self, record: CaptureIntervalRecord) -> Path:
        """Return the on-disk directory for ``record``. Does not create it."""
        return artifact_store.capture_dir(
            self._root, record.match_id or "unknown", record.id
        )

    async def _delete_all(self, rows: Sequence[CaptureIntervalRecord]) -> CleanupReport:
        report = CleanupReport()
        for row in rows:
            report = report.merge(await self._delete_one(row))
        return report

    async def _delete_one(self, record: CaptureIntervalRecord) -> CleanupReport:
        directory = self.directory_for(record)
        freed = artifact_store.directory_size(directory)
        artifact_store.delete_capture_dir(directory)
        artifact_store.prune_empty_parents(directory.parent, stop_at=self._root)
        await self._captures.delete_interval(record.id)
        return CleanupReport(
            deleted_capture_ids=[record.id],
            deleted_directories=[str(directory)],
            freed_bytes=freed,
        )


def is_partial(status: str) -> bool:
    """Return True when ``status`` names a failed or cancelled capture."""
    try:
        return CaptureStatus(status) in PARTIAL_STATUSES
    except ValueError:
        return False
