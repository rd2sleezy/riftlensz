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

R7_TABLES = {
    "gameplay_source",
    "rofl_source_detail",
    "clock_map",
    "replay_session",
    "capture_interval",
    "media_artifact",
}

HEAD_TABLES = PHASE1_TABLES | R7_TABLES


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
    missing = HEAD_TABLES - tables
    assert not missing, f"missing tables: {sorted(missing)}"
    assert "alembic_version" in tables


def test_alembic_downgrade_base_then_upgrade_head(tmp_path: Path) -> None:
    db_path = tmp_path / "cycle.db"
    _run_alembic(db_path, "upgrade", "head")
    _run_alembic(db_path, "downgrade", "base")
    after_down = _table_names(db_path)
    assert HEAD_TABLES.isdisjoint(after_down)
    _run_alembic(db_path, "upgrade", "head")
    after_up = _table_names(db_path)
    assert HEAD_TABLES <= after_up


def test_alembic_upgrade_phase1_then_r7(tmp_path: Path) -> None:
    db_path = tmp_path / "step.db"
    _run_alembic(db_path, "upgrade", "0001_phase1")
    after_phase1 = _table_names(db_path)
    assert PHASE1_TABLES <= after_phase1
    assert R7_TABLES.isdisjoint(after_phase1)
    _run_alembic(db_path, "upgrade", "0002_gameplay")
    after_r7 = _table_names(db_path)
    assert HEAD_TABLES <= after_r7


def test_alembic_downgrade_r7_keeps_phase1(tmp_path: Path) -> None:
    db_path = tmp_path / "down.db"
    _run_alembic(db_path, "upgrade", "head")
    _run_alembic(db_path, "downgrade", "0001_phase1")
    tables = _table_names(db_path)
    assert PHASE1_TABLES <= tables
    assert R7_TABLES.isdisjoint(tables)


def test_r7_backfill_copies_h9_sync_map(tmp_path: Path) -> None:
    db_path = tmp_path / "backfill.db"
    _run_alembic(db_path, "upgrade", "0001_phase1")
    engine = create_engine(sqlite_url(db_path))
    apply_sqlite_pragmas(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO match (
                  match_id, platform, region, queue_id, map_id, game_version, patch,
                  game_creation, game_start, game_duration_ms, ingested_at
                ) VALUES (
                  'NA1_backfill', 'na1', 'americas', 420, 11, '12.4.1', '12.4',
                  1, 1, 1200000, 2
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO media_asset (
                  id, content_hash, original_path, duration_ms, size_bytes,
                  source_kind, imported_at, last_accessed_at
                ) VALUES (
                  'media1', 'hashhashhashhashhashhashhashhashhashhashhashhashhashhashhashhash',
                  'C:/Users/someone/Videos/game.mp4', 1200000, 100,
                  'PLAYER_POV', 3, 3
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO sync_map (
                  id, media_asset_id, match_id, method, segments, pauses, quality,
                  verified, created_at
                ) VALUES (
                  'sync1', 'media1', 'NA1_backfill', 'manual', '[]', '[]', '{}', 0, 4
                )
                """
            )
        )
    engine.dispose()
    _run_alembic(db_path, "upgrade", "head")
    engine = create_engine(sqlite_url(db_path))
    apply_sqlite_pragmas(engine)
    with engine.connect() as connection:
        source = connection.execute(
            text(
                "SELECT source_type, display_name, status "
                "FROM gameplay_source WHERE match_id = 'NA1_backfill'"
            )
        ).one()
        clocks = connection.execute(text("SELECT COUNT(*) FROM clock_map")).scalar_one()
        phase1_sync = connection.execute(text("SELECT COUNT(*) FROM sync_map")).scalar_one()
    engine.dispose()
    assert source[0] == "video"
    assert source[1] == "game.mp4"
    assert source[2] == "linked"
    assert int(clocks) == 1
    assert int(phase1_sync) == 1


def test_r7_upgrade_empty_phase1_has_no_replay_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "empty_r7.db"
    _run_alembic(db_path, "upgrade", "0001_phase1")
    _run_alembic(db_path, "upgrade", "head")
    engine = create_engine(sqlite_url(db_path))
    apply_sqlite_pragmas(engine)
    with engine.connect() as connection:
        sources = connection.execute(text("SELECT COUNT(*) FROM gameplay_source")).scalar_one()
        clocks = connection.execute(text("SELECT COUNT(*) FROM clock_map")).scalar_one()
    engine.dispose()
    assert int(sources) == 0
    assert int(clocks) == 0


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
