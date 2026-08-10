"""R.7 native replay + ClockMap persistence (amendment §12).

Revision ID: 0002_gameplay
Revises: 0001_phase1
Create Date: 2026-08-09

"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from alembic import op
from sqlalchemy import text

from riftlens.domain.clock_map import ClockMap
from riftlens.domain.clock_store import (
    SOURCE_STATUS_LINKED,
    encode_clock_payload,
    local_display_name,
)
from riftlens.domain.sync_map import SyncMap

revision: str = "0002_gameplay"
down_revision: str | None = "0001_phase1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_STATEMENTS = [
    """
    CREATE TABLE gameplay_source (
      id              TEXT PRIMARY KEY,
      match_id        TEXT NOT NULL REFERENCES match(match_id),
      source_type     TEXT NOT NULL,
      source_uri      TEXT NOT NULL,
      content_hash    TEXT,
      display_name    TEXT NOT NULL,
      duration_ms     INTEGER NOT NULL,
      status          TEXT NOT NULL,
      platform_scope  TEXT NOT NULL,
      media_asset_id  TEXT REFERENCES media_asset(id),
      created_at      INTEGER NOT NULL,
      updated_at      INTEGER NOT NULL,
      UNIQUE(match_id, source_uri)
    )
    """,
    "CREATE INDEX ix_gameplay_source_match ON gameplay_source(match_id)",
    """
    CREATE TABLE rofl_source_detail (
      gameplay_source_id  TEXT PRIMARY KEY REFERENCES gameplay_source(id) ON DELETE CASCADE,
      platform_id         TEXT,
      game_id             INTEGER,
      declared_patch      TEXT,
      declared_length_ms  INTEGER,
      identify_method     TEXT NOT NULL,
      header_parse_status TEXT NOT NULL,
      file_size_bytes     INTEGER,
      magic               TEXT,
      raw_metadata_json   TEXT
    )
    """,
    """
    CREATE TABLE clock_map (
      id                  TEXT PRIMARY KEY,
      gameplay_source_id  TEXT NOT NULL REFERENCES gameplay_source(id) ON DELETE CASCADE,
      kind                TEXT NOT NULL,
      offset_ms           INTEGER NOT NULL DEFAULT 0,
      rate                REAL NOT NULL DEFAULT 1.0,
      confidence          TEXT NOT NULL,
      method              TEXT NOT NULL,
      anchor_count        INTEGER,
      residual_ms         INTEGER,
      is_active           INTEGER NOT NULL DEFAULT 0,
      created_at          INTEGER NOT NULL,
      payload_json        TEXT NOT NULL
    )
    """,
    "CREATE INDEX ix_clock_map_source ON clock_map(gameplay_source_id)",
    """
    CREATE UNIQUE INDEX uq_clock_map_one_active
      ON clock_map(gameplay_source_id) WHERE is_active = 1
    """,
    """
    CREATE TABLE replay_session (
      id                  TEXT PRIMARY KEY,
      gameplay_source_id  TEXT NOT NULL REFERENCES gameplay_source(id) ON DELETE CASCADE,
      replay_api_base     TEXT,
      replay_api_port     INTEGER,
      state               TEXT NOT NULL,
      last_error          TEXT,
      started_at          INTEGER NOT NULL,
      ended_at            INTEGER
    )
    """,
    "CREATE INDEX ix_replay_session_source ON replay_session(gameplay_source_id)",
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

_DOWNGRADE_STATEMENTS = [
    "DROP TABLE IF EXISTS media_artifact",
    "DROP TABLE IF EXISTS capture_interval",
    "DROP TABLE IF EXISTS replay_session",
    "DROP TABLE IF EXISTS clock_map",
    "DROP TABLE IF EXISTS rofl_source_detail",
    "DROP TABLE IF EXISTS gameplay_source",
]


def upgrade() -> None:
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)
    _backfill_h9_attachments()


def downgrade() -> None:
    for statement in _DOWNGRADE_STATEMENTS:
        op.execute(statement)


def _backfill_h9_attachments() -> None:
    """Copy existing H.9 video attachments into gameplay_source. Leaves H.9 tables intact."""
    bind = op.get_bind()
    sync_rows = bind.execute(
        text(
            """
            SELECT sm.id, sm.match_id, sm.method, sm.segments, sm.pauses, sm.quality,
                   sm.verified, sm.created_at, sm.media_asset_id,
                   ma.original_path, ma.content_hash, ma.duration_ms
            FROM sync_map sm
            JOIN media_asset ma ON ma.id = sm.media_asset_id
            """
        )
    ).mappings()
    for row in sync_rows:
        source_id = str(row["id"])
        uri = str(row["original_path"])
        if _source_exists(bind, str(row["match_id"]), uri):
            continue
        bind.execute(
            text(
                """
                INSERT INTO gameplay_source (
                  id, match_id, source_type, source_uri, content_hash, display_name,
                  duration_ms, status, platform_scope, media_asset_id, created_at, updated_at
                ) VALUES (
                  :id, :match_id, 'video', :source_uri, :content_hash, :display_name,
                  :duration_ms, :status, 'any', :media_asset_id, :created_at, :updated_at
                )
                """
            ),
            {
                "id": source_id,
                "match_id": row["match_id"],
                "source_uri": uri,
                "content_hash": row["content_hash"],
                "display_name": local_display_name(uri),
                "duration_ms": int(row["duration_ms"]),
                "status": SOURCE_STATUS_LINKED,
                "media_asset_id": row["media_asset_id"],
                "created_at": int(row["created_at"]),
                "updated_at": int(row["created_at"]),
            },
        )
        clock = _clock_from_sync_row(row, duration_ms=int(row["duration_ms"]))
        bind.execute(
            text(
                """
                INSERT INTO clock_map (
                  id, gameplay_source_id, kind, offset_ms, rate, confidence, method,
                  anchor_count, residual_ms, is_active, created_at, payload_json
                ) VALUES (
                  :id, :source_id, :kind, :offset_ms, 1.0, :confidence, :method,
                  NULL, NULL, 1, :created_at, :payload_json
                )
                """
            ),
            {
                "id": f"cm_{source_id}",
                "source_id": source_id,
                "kind": "linear_offset" if clock.mode.value == "SYNC_MAP" else "identity",
                "offset_ms": clock.offset_ms,
                "confidence": (
                    "manual"
                    if clock.verified or clock.mode.value == "SYNC_MAP"
                    else "unknown"
                ),
                "method": "manual",
                "created_at": int(row["created_at"]),
                "payload_json": encode_clock_payload(
                    clock, media_asset_id=str(row["media_asset_id"])
                ),
            },
        )

    review_rows = bind.execute(
        text(
            """
            SELECT r.id AS review_id, r.match_id, r.media_asset_id, r.created_at,
                   ma.original_path, ma.content_hash, ma.duration_ms
            FROM review r
            JOIN media_asset ma ON ma.id = r.media_asset_id
            WHERE r.media_asset_id IS NOT NULL
            """
        )
    ).mappings()
    for row in review_rows:
        uri = str(row["original_path"])
        if _source_exists(bind, str(row["match_id"]), uri):
            continue
        bind.execute(
            text(
                """
                INSERT INTO gameplay_source (
                  id, match_id, source_type, source_uri, content_hash, display_name,
                  duration_ms, status, platform_scope, media_asset_id, created_at, updated_at
                ) VALUES (
                  :id, :match_id, 'video', :source_uri, :content_hash, :display_name,
                  :duration_ms, :status, 'any', :media_asset_id, :created_at, :updated_at
                )
                """
            ),
            {
                "id": f"gs_{row['review_id']}",
                "match_id": row["match_id"],
                "source_uri": uri,
                "content_hash": row["content_hash"],
                "display_name": local_display_name(uri),
                "duration_ms": int(row["duration_ms"]),
                "status": SOURCE_STATUS_LINKED,
                "media_asset_id": row["media_asset_id"],
                "created_at": int(row["created_at"]),
                "updated_at": int(row["created_at"]),
            },
        )


def _source_exists(bind: object, match_id: str, source_uri: str) -> bool:
    row = bind.execute(  # type: ignore[attr-defined]
        text(
            """
            SELECT 1 FROM gameplay_source
            WHERE match_id = :match_id AND source_uri = :source_uri
            """
        ),
        {"match_id": match_id, "source_uri": source_uri},
    ).first()
    return row is not None


def _clock_from_sync_row(row: Mapping[str, object], *, duration_ms: int) -> ClockMap:
    try:
        payload = {
            "segments": json.loads(str(row["segments"])),
            "pauses": json.loads(str(row["pauses"])),
            "quality": json.loads(str(row["quality"])),
            "media_asset_id": str(row["media_asset_id"]),
            "match_id": str(row["match_id"]),
            "version": 1,
            "verified": bool(row["verified"]),
        }
        return ClockMap.from_sync_map(SyncMap.from_dict(payload))
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return ClockMap.unmapped(duration_ms=duration_ms)
