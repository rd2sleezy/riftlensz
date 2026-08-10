"""Phase 1 persistence schema from design doc §9.2–9.5.

Revision ID: 0001_phase1
Revises:
Create Date: 2026-08-09

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001_phase1"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_STATEMENTS = [
    """
    CREATE TABLE player (
      id              TEXT PRIMARY KEY,
      display_name    TEXT NOT NULL,
      is_local_user   INTEGER NOT NULL DEFAULT 0,
      created_at      INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE player_account (
      id              TEXT PRIMARY KEY,
      player_id       TEXT NOT NULL REFERENCES player(id) ON DELETE CASCADE,
      puuid           TEXT NOT NULL UNIQUE,
      game_name       TEXT NOT NULL,
      tag_line        TEXT NOT NULL,
      platform        TEXT NOT NULL,
      region          TEXT NOT NULL,
      summoner_level  INTEGER,
      tier            TEXT,
      rank_division   TEXT,
      league_points   INTEGER,
      rank_updated_at INTEGER,
      UNIQUE(puuid)
    )
    """,
    """
    CREATE TABLE match (
      match_id        TEXT PRIMARY KEY,
      platform        TEXT NOT NULL,
      region          TEXT NOT NULL,
      queue_id        INTEGER NOT NULL,
      map_id          INTEGER NOT NULL,
      game_version    TEXT NOT NULL,
      patch           TEXT NOT NULL,
      game_creation   INTEGER NOT NULL,
      game_start      INTEGER NOT NULL,
      game_duration_ms INTEGER NOT NULL,
      game_end_ts     INTEGER,
      winning_team    INTEGER,
      raw_match_blob  TEXT,
      raw_timeline_blob TEXT,
      ingested_at     INTEGER NOT NULL
    )
    """,
    "CREATE INDEX ix_match_patch ON match(patch)",
    "CREATE INDEX ix_match_creation ON match(game_creation DESC)",
    """
    CREATE TABLE match_participation (
      id              TEXT PRIMARY KEY,
      match_id        TEXT NOT NULL REFERENCES match(match_id) ON DELETE CASCADE,
      participant_id  INTEGER NOT NULL,
      puuid           TEXT NOT NULL,
      team_id         INTEGER NOT NULL,
      champion_id     INTEGER NOT NULL,
      champion_name   TEXT NOT NULL,
      team_position   TEXT,
      individual_position TEXT,
      lane_opponent_participant_id INTEGER,
      win             INTEGER NOT NULL,
      kills INTEGER, deaths INTEGER, assists INTEGER,
      total_cs        INTEGER,
      gold_earned     INTEGER, gold_spent INTEGER,
      vision_score    INTEGER,
      summoner1_id INTEGER, summoner2_id INTEGER,
      items           TEXT,
      perks           TEXT,
      challenges      TEXT,
      stats_json      TEXT NOT NULL,
      UNIQUE(match_id, participant_id)
    )
    """,
    "CREATE INDEX ix_participation_puuid ON match_participation(puuid)",
    """
    CREATE TABLE timeline_event (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      match_id        TEXT NOT NULL REFERENCES match(match_id) ON DELETE CASCADE,
      t_ms            INTEGER NOT NULL,
      type            TEXT NOT NULL,
      participant_id  INTEGER,
      victim_id       INTEGER,
      killer_id       INTEGER,
      pos_x INTEGER, pos_y INTEGER,
      payload         TEXT NOT NULL
    )
    """,
    "CREATE INDEX ix_tl_match_t ON timeline_event(match_id, t_ms)",
    "CREATE INDEX ix_tl_match_type ON timeline_event(match_id, type)",
    """
    CREATE TABLE participant_frame (
      match_id        TEXT NOT NULL REFERENCES match(match_id) ON DELETE CASCADE,
      t_ms            INTEGER NOT NULL,
      participant_id  INTEGER NOT NULL,
      pos_x INTEGER, pos_y INTEGER,
      current_gold INTEGER, total_gold INTEGER, gold_per_second INTEGER,
      xp INTEGER, level INTEGER,
      minions_killed INTEGER, jungle_minions_killed INTEGER,
      health INTEGER, health_max INTEGER, power INTEGER, power_max INTEGER,
      total_damage_done_to_champions INTEGER,
      total_damage_taken INTEGER,
      champion_stats  TEXT,
      damage_stats    TEXT,
      PRIMARY KEY (match_id, t_ms, participant_id)
    )
    """,
    """
    CREATE TABLE media_asset (
      id              TEXT PRIMARY KEY,
      content_hash    TEXT NOT NULL UNIQUE,
      original_path   TEXT NOT NULL,
      playable_path   TEXT,
      proxy_path      TEXT,
      thumbnail_sheet_path TEXT,
      container TEXT, codec TEXT, pix_fmt TEXT,
      width INTEGER, height INTEGER,
      fps_num INTEGER, fps_den INTEGER,
      duration_ms     INTEGER NOT NULL,
      size_bytes      INTEGER NOT NULL,
      source_kind     TEXT NOT NULL,
      layout_profile_id TEXT,
      quality_score   REAL,
      imported_at     INTEGER NOT NULL,
      last_accessed_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE layout_profile (
      id              TEXT PRIMARY KEY,
      width INTEGER, height INTEGER,
      ui_scale_estimate REAL,
      minimap_flipped INTEGER NOT NULL DEFAULT 0,
      minimap_rect    TEXT NOT NULL,
      clock_rect      TEXT NOT NULL,
      regions         TEXT NOT NULL,
      occluded_regions TEXT,
      world_to_minimap_affine TEXT,
      created_at      INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE sync_map (
      id              TEXT PRIMARY KEY,
      media_asset_id  TEXT NOT NULL REFERENCES media_asset(id) ON DELETE CASCADE,
      match_id        TEXT NOT NULL REFERENCES match(match_id) ON DELETE CASCADE,
      method          TEXT NOT NULL,
      segments        TEXT NOT NULL,
      pauses          TEXT NOT NULL,
      quality         TEXT NOT NULL,
      verified        INTEGER NOT NULL DEFAULT 0,
      created_at      INTEGER NOT NULL,
      UNIQUE(media_asset_id, match_id)
    )
    """,
    """
    CREATE TABLE review (
      id              TEXT PRIMARY KEY,
      player_id       TEXT NOT NULL REFERENCES player(id),
      match_id        TEXT NOT NULL REFERENCES match(match_id),
      participant_id  INTEGER NOT NULL,
      media_asset_id  TEXT REFERENCES media_asset(id),
      sync_map_id     TEXT REFERENCES sync_map(id),
      rule_pack_version TEXT NOT NULL,
      engine_version  TEXT NOT NULL,
      analysis_tiers  TEXT NOT NULL,
      status          TEXT NOT NULL,
      summary_text    TEXT,
      overall_scores  TEXT,
      llm_provider    TEXT, llm_model TEXT, llm_prompt_version TEXT,
      created_at      INTEGER NOT NULL,
      completed_at    INTEGER
    )
    """,
    "CREATE INDEX ix_review_player ON review(player_id, created_at DESC)",
    """
    CREATE TABLE concept (
      id              TEXT PRIMARY KEY,
      parent_id       TEXT REFERENCES concept(id),
      domain          TEXT NOT NULL,
      label           TEXT NOT NULL,
      description     TEXT,
      data_tier       TEXT NOT NULL,
      teachability    REAL NOT NULL,
      roles           TEXT NOT NULL,
      phases          TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE rule_definition (
      id              TEXT NOT NULL,
      version         INTEGER NOT NULL,
      name            TEXT NOT NULL,
      concept_id      TEXT NOT NULL REFERENCES concept(id),
      category        TEXT NOT NULL,
      severity_base   TEXT NOT NULL,
      data_tier       TEXT NOT NULL,
      patch_range     TEXT,
      definition_json TEXT NOT NULL,
      PRIMARY KEY (id, version)
    )
    """,
    """
    CREATE TABLE finding (
      id              TEXT PRIMARY KEY,
      review_id       TEXT NOT NULL REFERENCES review(id) ON DELETE CASCADE,
      rule_id         TEXT NOT NULL,
      rule_version    INTEGER NOT NULL,
      concept_id      TEXT NOT NULL REFERENCES concept(id),
      t_ms            INTEGER NOT NULL,
      t_end_ms        INTEGER,
      severity        TEXT NOT NULL,
      confidence      REAL NOT NULL,
      gold_equivalent REAL,
      outcome         TEXT,
      map_x INTEGER, map_y INTEGER,
      title           TEXT NOT NULL,
      explanation     TEXT,
      alternative     TEXT,
      explanation_source TEXT NOT NULL,
      suppressed      INTEGER NOT NULL DEFAULT 0,
      suppressed_by   TEXT
    )
    """,
    "CREATE INDEX ix_finding_review_t ON finding(review_id, t_ms)",
    "CREATE INDEX ix_finding_concept ON finding(concept_id)",
    """
    CREATE TABLE evidence (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      finding_id      TEXT NOT NULL REFERENCES finding(id) ON DELETE CASCADE,
      kind            TEXT NOT NULL,
      label           TEXT NOT NULL,
      value_json      TEXT NOT NULL,
      t_ms            INTEGER,
      source          TEXT NOT NULL,
      confidence      REAL,
      provenance_json TEXT
    )
    """,
    """
    CREATE TABLE metric_value (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      review_id       TEXT NOT NULL REFERENCES review(id) ON DELETE CASCADE,
      metric_id       TEXT NOT NULL,
      phase           TEXT,
      value           REAL NOT NULL,
      unit            TEXT,
      confidence      REAL NOT NULL,
      baseline_key    TEXT,
      baseline_p50    REAL,
      baseline_percentile REAL,
      detail_json     TEXT
    )
    """,
    "CREATE INDEX ix_metric_review ON metric_value(review_id, metric_id)",
    """
    CREATE TABLE coaching_item (
      id              TEXT PRIMARY KEY,
      review_id       TEXT NOT NULL REFERENCES review(id) ON DELETE CASCADE,
      root_concept_id TEXT NOT NULL REFERENCES concept(id),
      rank            INTEGER NOT NULL,
      is_focus        INTEGER NOT NULL DEFAULT 0,
      is_strength     INTEGER NOT NULL DEFAULT 0,
      issue_type      TEXT NOT NULL,
      impact_score    REAL NOT NULL,
      gold_equivalent REAL,
      occurrences     INTEGER NOT NULL,
      confidence      REAL NOT NULL,
      title           TEXT NOT NULL,
      body            TEXT NOT NULL,
      the_fix         TEXT,
      next_game_check TEXT,
      exemplar_finding_id TEXT REFERENCES finding(id)
    )
    """,
    """
    CREATE TABLE coaching_item_finding (
      coaching_item_id TEXT NOT NULL REFERENCES coaching_item(id) ON DELETE CASCADE,
      finding_id       TEXT NOT NULL REFERENCES finding(id) ON DELETE CASCADE,
      PRIMARY KEY (coaching_item_id, finding_id)
    )
    """,
    """
    CREATE TABLE finding_feedback (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      finding_id      TEXT NOT NULL REFERENCES finding(id) ON DELETE CASCADE,
      verdict         TEXT NOT NULL,
      note            TEXT,
      created_at      INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE player_trend (
      id              TEXT PRIMARY KEY,
      player_id       TEXT NOT NULL REFERENCES player(id) ON DELETE CASCADE,
      concept_id      TEXT REFERENCES concept(id),
      metric_id       TEXT,
      window_start    INTEGER NOT NULL,
      window_end      INTEGER NOT NULL,
      n_matches       INTEGER NOT NULL,
      value           REAL NOT NULL,
      prev_value      REAL,
      direction       TEXT,
      significance    REAL,
      UNIQUE(player_id, concept_id, metric_id, window_start)
    )
    """,
    """
    CREATE TABLE focus_commitment (
      id              TEXT PRIMARY KEY,
      player_id       TEXT NOT NULL REFERENCES player(id),
      review_id       TEXT NOT NULL REFERENCES review(id),
      concept_id      TEXT NOT NULL REFERENCES concept(id),
      metric_id       TEXT,
      target_value    REAL,
      comparison      TEXT,
      created_at      INTEGER NOT NULL,
      resolved_review_id TEXT REFERENCES review(id),
      outcome         TEXT
    )
    """,
    """
    CREATE TABLE player_champion_profile (
      id              TEXT PRIMARY KEY,
      player_id       TEXT NOT NULL REFERENCES player(id),
      champion_id     INTEGER NOT NULL,
      role            TEXT NOT NULL,
      games           INTEGER NOT NULL,
      aggregates_json TEXT NOT NULL,
      updated_at      INTEGER NOT NULL,
      UNIQUE(player_id, champion_id, role)
    )
    """,
    """
    CREATE TABLE champion_profile (
      champion_id     INTEGER NOT NULL,
      patch           TEXT NOT NULL,
      name            TEXT NOT NULL,
      class_tags      TEXT NOT NULL,
      behavior_tags   TEXT NOT NULL,
      power_spikes    TEXT NOT NULL,
      win_condition   TEXT NOT NULL,
      typical_build   TEXT,
      abilities       TEXT NOT NULL,
      PRIMARY KEY (champion_id, patch)
    )
    """,
    """
    CREATE TABLE baseline_stat (
      metric_id       TEXT NOT NULL,
      tier            TEXT NOT NULL,
      role            TEXT NOT NULL,
      champion_class  TEXT NOT NULL DEFAULT 'ALL',
      patch           TEXT NOT NULL,
      phase           TEXT NOT NULL,
      n               INTEGER NOT NULL,
      p10 REAL, p25 REAL, p50 REAL, p75 REAL, p90 REAL, mean REAL, stddev REAL,
      updated_at      INTEGER NOT NULL,
      PRIMARY KEY (metric_id, tier, role, champion_class, patch, phase)
    )
    """,
]

_DOWNGRADE_TABLES = [
    "baseline_stat",
    "champion_profile",
    "player_champion_profile",
    "focus_commitment",
    "player_trend",
    "finding_feedback",
    "coaching_item_finding",
    "coaching_item",
    "metric_value",
    "evidence",
    "finding",
    "rule_definition",
    "concept",
    "review",
    "sync_map",
    "layout_profile",
    "media_asset",
    "participant_frame",
    "timeline_event",
    "match_participation",
    "match",
    "player_account",
    "player",
]


def upgrade() -> None:
    """Create every §9.2–9.5 table. Assumes the database is empty or at base."""
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Drop every §9.2–9.5 table. Assumes no application writers are connected."""
    for table in _DOWNGRADE_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")
