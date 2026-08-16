"""H.11 analysis job persistence.

Revision ID: 0004_h11_jobs
Revises: 0003_capture
Create Date: 2026-08-16

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_h11_jobs"
down_revision: str | None = "0003_capture"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_STATEMENTS = [
    """
    CREATE TABLE analysis_job (
      id                 TEXT PRIMARY KEY,
      status             TEXT NOT NULL,
      match_id           TEXT NOT NULL,
      participant_id     INTEGER NOT NULL,
      media_asset_id     TEXT,
      current_stage      TEXT,
      progress_pct       INTEGER NOT NULL DEFAULT 0,
      progress_message   TEXT,
      created_at         INTEGER NOT NULL,
      started_at         INTEGER,
      completed_at       INTEGER,
      failure_stage      TEXT,
      error_code         TEXT,
      error_message      TEXT,
      review_id          TEXT,
      stage_timings_json TEXT,
      cache_hits         INTEGER NOT NULL DEFAULT 0,
      cache_misses       INTEGER NOT NULL DEFAULT 0,
      inputs_json        TEXT NOT NULL,
      llm_provider       TEXT,
      llm_model          TEXT,
      llm_fallback       INTEGER NOT NULL DEFAULT 0,
      fact_count         INTEGER,
      finding_count      INTEGER,
      sync_quality_json  TEXT
    )
    """,
    "CREATE INDEX ix_analysis_job_status ON analysis_job(status)",
    "CREATE INDEX ix_analysis_job_completed ON analysis_job(completed_at)",
]

_DOWNGRADE_STATEMENTS = [
    "DROP INDEX IF EXISTS ix_analysis_job_completed",
    "DROP INDEX IF EXISTS ix_analysis_job_status",
    "DROP TABLE IF EXISTS analysis_job",
]


def upgrade() -> None:
    """Add analysis_job. Assumes 0003_capture is the current head."""
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Drop analysis_job. Job rows are regenerable orchestration state."""
    for statement in _DOWNGRADE_STATEMENTS:
        op.execute(statement)
