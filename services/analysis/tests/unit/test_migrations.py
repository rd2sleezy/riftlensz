from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest
from riftlens.adapters.db.engine import (
    ANALYSIS_ROOT,
    SchemaTooNewError,
    alembic_config,
    apply_sqlite_pragmas,
    assert_schema_compatible,
    create_sqlite_engine,
    sqlite_url,
)
from riftlens.config import Settings
from sqlalchemy import create_engine, inspect, text

PHASE1_TABLES = {
    "player",
    "player_account",
    "match",
    "match_participation",
    "timeline_event",
    "participant_frame",
    "media_asset",
    "layout_profile",
    "sync_map",
    "review",
    "rule_definition",
    "concept",
    "finding",
    "evidence",
    "metric_value",
    "coaching_item",
    "coaching_item_finding",
    "finding_feedback",
    "player_trend",
    "focus_commitment",
    "player_champion_profile",
    "champion_profile",
    "baseline_stat",
}


def _alembic_env(db_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["RIFTLENS_DATABASE_URL"] = sqlite_url(db_path)
    return env


def _run_alembic(db_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ANALYSIS_ROOT,
        env=_alembic_env(db_path),
        check=True,
        capture_output=True,
        text=True,
    )


def _table_names(db_path: Path) -> set[str]:
    engine = create_engine(sqlite_url(db_path))
    try:
        apply_sqlite_pragmas(engine)
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_alembic_upgrade_head_creates_every_table(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    _run_alembic(db_path, "upgrade", "head")
    tables = _table_names(db_path)
    missing = PHASE1_TABLES - tables
    assert not missing, f"missing tables: {sorted(missing)}"
    assert "alembic_version" in tables


def test_alembic_downgrade_base_then_upgrade_head(tmp_path: Path) -> None:
    db_path = tmp_path / "cycle.db"
    _run_alembic(db_path, "upgrade", "head")
    _run_alembic(db_path, "downgrade", "base")
    after_down = _table_names(db_path)
    assert PHASE1_TABLES.isdisjoint(after_down)
    _run_alembic(db_path, "upgrade", "head")
    after_up = _table_names(db_path)
    assert PHASE1_TABLES <= after_up


def test_schema_version_refuses_newer_head(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    engine = create_sqlite_engine(settings.db_path)
    apply_sqlite_pragmas(engine)
    from alembic import command

    cfg = alembic_config(sqlite_url(settings.db_path))
    with engine.connect() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
        connection.commit()
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'zzzz_future'"))
    with pytest.raises(SchemaTooNewError, match="newer than this RiftLens binary"):
        assert_schema_compatible(engine)
    engine.dispose()


def test_pragmas_are_applied(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "pragma.db")
    with engine.connect() as connection:
        values: Mapping[str, object] = {
            "journal_mode": connection.execute(text("PRAGMA journal_mode")).scalar(),
            "foreign_keys": connection.execute(text("PRAGMA foreign_keys")).scalar(),
            "synchronous": connection.execute(text("PRAGMA synchronous")).scalar(),
            "busy_timeout": connection.execute(text("PRAGMA busy_timeout")).scalar(),
        }
    engine.dispose()
    assert str(values["journal_mode"]).lower() == "wal"
    assert int(values["foreign_keys"] or 0) == 1
    assert int(values["synchronous"] or 0) == 1
    assert int(values["busy_timeout"] or 0) == 5000
