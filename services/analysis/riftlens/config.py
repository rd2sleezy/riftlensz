from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from riftlens.domain.capture import DEFAULT_CAPTURE_BUDGET, CaptureBudget


def default_data_dir() -> Path:
    """Return the platform data directory. Assumes HOME/APPDATA is set."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "RiftLens"
        return Path.home() / "AppData" / "Roaming" / "RiftLens"
    return Path.home() / ".riftlens"


def default_captures_dir() -> Path:
    """Return the R.10 capture root. Captures are machine-local, never roaming (§7.4)."""
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "RiftLens" / "captures"
        return Path.home() / "AppData" / "Local" / "RiftLens" / "captures"
    return Path.home() / ".riftlens" / "captures"


class Settings(BaseSettings):
    """Process settings. Assumes env vars use the RIFTLENS_ prefix when present."""

    model_config = SettingsConfigDict(env_prefix="RIFTLENS_", extra="ignore")

    data_dir: Path = Field(default_factory=default_data_dir)
    riot_api_key: str = ""
    llm_provider: str = "null"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = ""
    ingest_video_hold_ms: int = 0
    capture_root: Path | None = None
    capture_max_seconds: float = DEFAULT_CAPTURE_BUDGET.max_seconds
    capture_max_artifacts: int = DEFAULT_CAPTURE_BUDGET.max_artifacts
    capture_max_bytes: int = DEFAULT_CAPTURE_BUDGET.max_bytes

    @property
    def db_path(self) -> Path:
        """Return the SQLite path under data_dir. Assumes data_dir is writable later."""
        return self.data_dir / "riftlens.db"

    @property
    def cache_dir(self) -> Path:
        """Return the on-disk cache root. Assumes data_dir is writable later."""
        return self.data_dir / "cache"

    @property
    def captures_dir(self) -> Path:
        """Return the capture root. ``capture_root`` wins; otherwise LOCALAPPDATA (§7.4)."""
        return self.capture_root if self.capture_root is not None else default_captures_dir()

    @property
    def capture_budget(self) -> CaptureBudget:
        """Return the per-review capture ceilings assembled from settings."""
        return CaptureBudget(
            max_seconds=self.capture_max_seconds,
            max_artifacts=self.capture_max_artifacts,
            max_bytes=self.capture_max_bytes,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton. Assumes env is already loaded."""
    return Settings()
