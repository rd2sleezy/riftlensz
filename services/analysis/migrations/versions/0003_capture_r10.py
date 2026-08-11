"""R.10 frame capture columns on capture_interval/media_artifact (amendment §7, §12.1).

Revision ID: 0003_capture
Revises: 0002_gameplay
Create Date: 2026-08-10

Downgrade recreates both tables empty: capture artifacts are regenerable render output,
so R.10 rows are not carried backwards.

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_capture"
down_revision: str | None = "0002_gameplay"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_STATEMENTS = [
    "ALTER TABLE capture_interval ADD COLUMN clock_map_id TEXT REFERENCES clock_map(id)",
    "ALTER TABLE capture_interval ADD COLUMN match_id TEXT",
    "ALTER TABLE capture_interval ADD COLUMN mode TEXT NOT NULL DEFAULT 'CLIP'",
    "ALTER TABLE capture_interval ADD COLUMN fps REAL",
    "ALTER TABLE capture_interval ADD COLUMN status TEXT NOT NULL DEFAULT 'requested'",
    "ALTER TABLE capture_interval ADD COLUMN progress REAL NOT NULL DEFAULT 0",
    "ALTER TABLE capture_interval ADD COLUMN t_start_source_ms INTEGER",
    "ALTER TABLE capture_interval ADD COLUMN t_end_source_ms INTEGER",
    "ALTER TABLE capture_interval ADD COLUMN retention_class TEXT NOT NULL DEFAULT 'review'",
    "ALTER TABLE capture_interval ADD COLUMN review_id TEXT",
    "ALTER TABLE capture_interval ADD COLUMN error_code TEXT",
    "ALTER TABLE capture_interval ADD COLUMN artifact_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE capture_interval ADD COLUMN total_bytes INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE capture_interval ADD COLUMN completed_at INTEGER",
    "ALTER TABLE capture_interval ADD COLUMN manifest_json TEXT",
    "CREATE INDEX ix_capture_interval_status ON capture_interval(status)",
    "CREATE INDEX ix_capture_interval_review ON capture_interval(review_id)",
    "CREATE INDEX ix_capture_interval_retention ON capture_interval(retention_class)",
    "ALTER TABLE media_artifact ADD COLUMN game_t_ms INTEGER",
    "ALTER TABLE media_artifact ADD COLUMN source_t_ms INTEGER",
    "ALTER TABLE media_artifact ADD COLUMN frame_index INTEGER",
    "ALTER TABLE media_artifact ADD COLUMN retention_class TEXT NOT NULL DEFAULT 'review'",
    "ALTER TABLE media_artifact ADD COLUMN bytes INTEGER",
    "ALTER TABLE media_artifact ADD COLUMN expires_at INTEGER",
    "CREATE INDEX ix_media_artifact_capture ON media_artifact(capture_interval_id)",
]

_DOWNGRADE_STATEMENTS = [
    "DROP INDEX IF EXISTS ix_media_artifact_capture",
    "DROP INDEX IF EXISTS ix_capture_interval_retention",
    "DROP INDEX IF EXISTS ix_capture_interval_review",
    "DROP INDEX IF EXISTS ix_capture_interval_status",
    "DROP INDEX IF EXISTS ix_capture_interval_source_t",
    "DROP TABLE IF EXISTS media_artifact",
    "DROP TABLE IF EXISTS capture_interval",
    """
    CREATE TABLE capture_interval (
      id                  TEXT PRIMARY KEY,
      gameplay_source_id  TEXT NOT NULL REFERENCES gameplay_source(id) ON DELETE CASCADE,
      t_start_ms          INTEGER NOT NULL,
      t_end_ms            INTEGER NOT NULL,
      reason              TEXT NOT NULL,
      created_at          INTEGER NOT NULL
    )
    """,
    "CREATE INDEX ix_capture_interval_source_t ON capture_interval(gameplay_source_id, t_start_ms)",
    """
    CREATE TABLE media_artifact (
      id                  TEXT PRIMARY KEY,
      capture_interval_id TEXT NOT NULL REFERENCES capture_interval(id) ON DELETE CASCADE,
      kind                TEXT NOT NULL,
      path                TEXT NOT NULL,
      content_hash        TEXT,
      width               INTEGER,
      height              INTEGER,
      created_at          INTEGER NOT NULL
    )
    """,
]


def upgrade() -> None:
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE_STATEMENTS:
        op.execute(statement)
