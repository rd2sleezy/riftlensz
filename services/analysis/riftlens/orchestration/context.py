from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.orm import Session, sessionmaker

from riftlens.config import Settings
from riftlens.orchestration.cache import StageCache
from riftlens.orchestration.job import AnalysisJob, CancellationToken
from riftlens.orchestration.pool import CancellablePool
from riftlens.orchestration.progress import ProgressBus, ProgressEvent, now_ms

DEFAULT_STAGE_VERSIONS: dict[str, str] = {
    "ingest_riot": "1",
    "ingest_video": "1",
    "synchronize": "1",
    "build_facts": "1",
    "compute_metrics": "1",
    "run_rules": "1",
    "prioritize": "1",
    "compose_coaching": "1",
    "persist": "1",
}

STAGE_ORDER = (
    "ingest_riot",
    "ingest_video",
    "synchronize",
    "build_facts",
    "compute_metrics",
    "run_rules",
    "prioritize",
    "compose_coaching",
    "persist",
)

VIDEO_STAGES = frozenset({"ingest_video", "synchronize"})
DOWNSTREAM_FROM_SYNC = frozenset(
    {
        "synchronize",
        "build_facts",
        "compute_metrics",
        "run_rules",
        "prioritize",
        "compose_coaching",
        "persist",
    }
)
STAGE_UPSTREAM: dict[str, tuple[str, ...]] = {
    "ingest_riot": (),
    "ingest_video": (),
    "synchronize": ("ingest_riot", "ingest_video"),
    "build_facts": ("ingest_riot",),
    "compute_metrics": ("build_facts",),
    "run_rules": ("compute_metrics",),
    "prioritize": ("run_rules",),
    "compose_coaching": ("prioritize",),
    "persist": ("compose_coaching",),
}


@dataclass
class StageResult:
    outputs: dict[str, Any]
    cache_hit: bool = False
    skipped: bool = False
    message: str = ""


class Stage(Protocol):
    name: str
    version: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    cacheable: bool

    async def run(self, ctx: StageContext) -> StageResult:
        """Execute the stage. Assumes ``ctx.artifacts`` holds declared inputs."""
        ...


@dataclass
class StageContext:
    job: AnalysisJob
    settings: Settings
    session_factory: sessionmaker[Session] | None
    cache: StageCache
    bus: ProgressBus
    artifacts: dict[str, Any] = field(default_factory=dict)
    stage_versions: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_STAGE_VERSIONS))
    pool: CancellablePool = field(default_factory=CancellablePool)
    api_key: str | None = None
    last_stage_pct: int = 0

    @property
    def cancel(self) -> CancellationToken:
        """Return the job cancellation token."""
        return self.job.cancel

    def version_for(self, name: str) -> str:
        """Return the configured version for ``name``."""
        return self.stage_versions.get(name, DEFAULT_STAGE_VERSIONS[name])

    def has_video(self) -> bool:
        """Return True when this job requested VIDEO media (not ROFL)."""
        return bool(self.job.inputs.media_asset_id)

    async def tick(self, stage: str, pct: int, message: str) -> None:
        """Emit a monotonic within-stage progress event and check cancellation."""
        self.cancel.raise_if_set()
        clamped = max(self.last_stage_pct, min(100, max(0, pct)))
        if clamped >= 5 and clamped // 5 > self.last_stage_pct // 5:
            self.cancel.raise_if_set()
        self.last_stage_pct = clamped
        overall = _overall_pct(stage, clamped, self.has_video())
        self.job.current_stage = stage
        self.job.progress_pct = overall
        self.job.progress_message = message
        self.bus.emit(
            ProgressEvent(
                job_id=self.job.id,
                stage=stage,
                pct=overall,
                message=message,
                ts=now_ms(),
                status=self.job.status,
            )
        )
        await asyncio.sleep(0)

    def input_refs(self, names: tuple[str, ...], *, stage_name: str) -> dict[str, Any]:
        """Return JSON-safe refs for cache keys. Never uses object identity."""
        refs: dict[str, Any] = {}
        for name in names:
            value = self.artifacts.get(name)
            refs[name] = _ref_value(value)
        refs["match_id"] = self.job.inputs.match_id
        refs["participant_id"] = self.job.inputs.participant_id
        refs["_upstream_versions"] = _transitive_upstream_versions(stage_name, self.stage_versions)
        return refs


def _ref_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    digest = getattr(value, "content_hash", None)
    if isinstance(digest, str):
        return digest
    ident = getattr(value, "id", None)
    if isinstance(ident, str):
        return ident
    if isinstance(value, Mapping):
        return {str(key): _ref_value(item) for key, item in value.items()}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _ref_value(to_dict())
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        return json.loads(json.dumps(dumped, sort_keys=True, default=str))
    return str(value)


def _overall_pct(stage: str, within: int, has_video: bool) -> int:
    active = [name for name in STAGE_ORDER if has_video or name not in VIDEO_STAGES]
    if stage not in active:
        return min(99, max(0, within))
    index = active.index(stage)
    span = 100 / len(active)
    return min(99, int(index * span + (within / 100.0) * span))


def _transitive_upstream_versions(stage_name: str, versions: Mapping[str, str]) -> dict[str, str]:
    """Return versions of stages this stage depends on, transitively."""
    seen: dict[str, str] = {}
    stack = list(STAGE_UPSTREAM.get(stage_name, ()))
    while stack:
        dep = stack.pop()
        if dep in seen:
            continue
        seen[dep] = versions.get(dep, DEFAULT_STAGE_VERSIONS.get(dep, "1"))
        stack.extend(STAGE_UPSTREAM.get(dep, ()))
    return dict(sorted(seen.items()))


def fixture_root() -> Path:
    """Return the committed Riot fixture directory. Assumes the analysis package layout."""
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "riot"
