from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from riftlens.config import Settings
from riftlens.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Return Settings rooted at a temp dir. Assumes tmp_path is writable."""
    return Settings(data_dir=tmp_path)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Return a TestClient with lifespan running. Assumes create_app wires /health without auth."""
    app = create_app(settings=settings, token="test-token")
    with TestClient(app) as test_client:
        yield test_client
