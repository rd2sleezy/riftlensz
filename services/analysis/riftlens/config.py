from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_data_dir() -> Path:
    """Return the platform data directory. Assumes HOME/APPDATA is set."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "RiftLens"
        return Path.home() / "AppData" / "Roaming" / "RiftLens"
    return Path.home() / ".riftlens"


class Settings(BaseSettings):
    """Process settings. Assumes env vars use the RIFTLENS_ prefix when present."""

    model_config = SettingsConfigDict(env_prefix="RIFTLENS_", extra="ignore")

    data_dir: Path = Field(default_factory=default_data_dir)
    riot_api_key: str = ""

    @property
    def db_path(self) -> Path:
        """Return the SQLite path under data_dir. Assumes data_dir is writable later."""
        return self.data_dir / "riftlens.db"

    @property
    def cache_dir(self) -> Path:
        """Return the on-disk cache root. Assumes data_dir is writable later."""
        return self.data_dir / "cache"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton. Assumes env is already loaded."""
    return Settings()
