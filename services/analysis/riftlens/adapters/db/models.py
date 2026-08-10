from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PlayerRow(Base):
    __tablename__ = "player"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_local_user: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class PlayerAccountRow(Base):
    __tablename__ = "player_account"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    player_id: Mapped[str] = mapped_column(
        Text, ForeignKey("player.id", ondelete="CASCADE"), nullable=False
    )
    puuid: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    game_name: Mapped[str] = mapped_column(Text, nullable=False)
    tag_line: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str] = mapped_column(Text, nullable=False)
    summoner_level: Mapped[int | None] = mapped_column(Integer)
    tier: Mapped[str | None] = mapped_column(Text)
    rank_division: Mapped[str | None] = mapped_column(Text)
    league_points: Mapped[int | None] = mapped_column(Integer)
    rank_updated_at: Mapped[int | None] = mapped_column(Integer)


class MatchRow(Base):
    __tablename__ = "match"
    __table_args__ = (
        Index("ix_match_patch", "patch"),
        Index("ix_match_creation", "game_creation"),
    )

    match_id: Mapped[str] = mapped_column(Text, primary_key=True)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str] = mapped_column(Text, nullable=False)
    queue_id: Mapped[int] = mapped_column(Integer, nullable=False)
    map_id: Mapped[int] = mapped_column(Integer, nullable=False)
    game_version: Mapped[str] = mapped_column(Text, nullable=False)
    patch: Mapped[str] = mapped_column(Text, nullable=False)
    game_creation: Mapped[int] = mapped_column(Integer, nullable=False)
    game_start: Mapped[int] = mapped_column(Integer, nullable=False)
    game_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    game_end_ts: Mapped[int | None] = mapped_column(Integer)
    winning_team: Mapped[int | None] = mapped_column(Integer)
    raw_match_blob: Mapped[str | None] = mapped_column(Text)
    raw_timeline_blob: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[int] = mapped_column(Integer, nullable=False)


class MatchParticipationRow(Base):
    __tablename__ = "match_participation"
    __table_args__ = (
        UniqueConstraint("match_id", "participant_id"),
        Index("ix_participation_puuid", "puuid"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    match_id: Mapped[str] = mapped_column(
        Text, ForeignKey("match.match_id", ondelete="CASCADE"), nullable=False
    )
    participant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    puuid: Mapped[str] = mapped_column(Text, nullable=False)
    team_id: Mapped[int] = mapped_column(Integer, nullable=False)
    champion_id: Mapped[int] = mapped_column(Integer, nullable=False)
    champion_name: Mapped[str] = mapped_column(Text, nullable=False)
    team_position: Mapped[str | None] = mapped_column(Text)
    individual_position: Mapped[str | None] = mapped_column(Text)
    lane_opponent_participant_id: Mapped[int | None] = mapped_column(Integer)
    win: Mapped[int] = mapped_column(Integer, nullable=False)
    kills: Mapped[int | None] = mapped_column(Integer)
    deaths: Mapped[int | None] = mapped_column(Integer)
    assists: Mapped[int | None] = mapped_column(Integer)
    total_cs: Mapped[int | None] = mapped_column(Integer)
    gold_earned: Mapped[int | None] = mapped_column(Integer)
    gold_spent: Mapped[int | None] = mapped_column(Integer)
    vision_score: Mapped[int | None] = mapped_column(Integer)
    summoner1_id: Mapped[int | None] = mapped_column(Integer)
    summoner2_id: Mapped[int | None] = mapped_column(Integer)
    items: Mapped[str | None] = mapped_column(Text)
    perks: Mapped[str | None] = mapped_column(Text)
    challenges: Mapped[str | None] = mapped_column(Text)
    stats_json: Mapped[str] = mapped_column(Text, nullable=False)


class TimelineEventRow(Base):
    __tablename__ = "timeline_event"
    __table_args__ = (
        Index("ix_tl_match_t", "match_id", "t_ms"),
        Index("ix_tl_match_type", "match_id", "type"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(
        Text, ForeignKey("match.match_id", ondelete="CASCADE"), nullable=False
    )
    t_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    participant_id: Mapped[int | None] = mapped_column(Integer)
    victim_id: Mapped[int | None] = mapped_column(Integer)
    killer_id: Mapped[int | None] = mapped_column(Integer)
    pos_x: Mapped[int | None] = mapped_column(Integer)
    pos_y: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


class ParticipantFrameRow(Base):
    __tablename__ = "participant_frame"

    match_id: Mapped[str] = mapped_column(
        Text, ForeignKey("match.match_id", ondelete="CASCADE"), primary_key=True
    )
    t_ms: Mapped[int] = mapped_column(Integer, primary_key=True)
    participant_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pos_x: Mapped[int | None] = mapped_column(Integer)
    pos_y: Mapped[int | None] = mapped_column(Integer)
    current_gold: Mapped[int | None] = mapped_column(Integer)
    total_gold: Mapped[int | None] = mapped_column(Integer)
    gold_per_second: Mapped[int | None] = mapped_column(Integer)
    xp: Mapped[int | None] = mapped_column(Integer)
    level: Mapped[int | None] = mapped_column(Integer)
    minions_killed: Mapped[int | None] = mapped_column(Integer)
    jungle_minions_killed: Mapped[int | None] = mapped_column(Integer)
    health: Mapped[int | None] = mapped_column(Integer)
    health_max: Mapped[int | None] = mapped_column(Integer)
    power: Mapped[int | None] = mapped_column(Integer)
    power_max: Mapped[int | None] = mapped_column(Integer)
    total_damage_done_to_champions: Mapped[int | None] = mapped_column(Integer)
    total_damage_taken: Mapped[int | None] = mapped_column(Integer)
    champion_stats: Mapped[str | None] = mapped_column(Text)
    damage_stats: Mapped[str | None] = mapped_column(Text)


class MediaAssetRow(Base):
    __tablename__ = "media_asset"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    original_path: Mapped[str] = mapped_column(Text, nullable=False)
    playable_path: Mapped[str | None] = mapped_column(Text)
    proxy_path: Mapped[str | None] = mapped_column(Text)
    thumbnail_sheet_path: Mapped[str | None] = mapped_column(Text)
    container: Mapped[str | None] = mapped_column(Text)
    codec: Mapped[str | None] = mapped_column(Text)
    pix_fmt: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps_num: Mapped[int | None] = mapped_column(Integer)
    fps_den: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    layout_profile_id: Mapped[str | None] = mapped_column(Text)
    quality_score: Mapped[float | None] = mapped_column(Float)
    imported_at: Mapped[int] = mapped_column(Integer, nullable=False)
    last_accessed_at: Mapped[int] = mapped_column(Integer, nullable=False)


class LayoutProfileRow(Base):
    __tablename__ = "layout_profile"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    ui_scale_estimate: Mapped[float | None] = mapped_column(Float)
    minimap_flipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    minimap_rect: Mapped[str] = mapped_column(Text, nullable=False)
    clock_rect: Mapped[str] = mapped_column(Text, nullable=False)
    regions: Mapped[str] = mapped_column(Text, nullable=False)
    occluded_regions: Mapped[str | None] = mapped_column(Text)
    world_to_minimap_affine: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class SyncMapRow(Base):
    __tablename__ = "sync_map"
    __table_args__ = (UniqueConstraint("media_asset_id", "match_id"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    media_asset_id: Mapped[str] = mapped_column(
        Text, ForeignKey("media_asset.id", ondelete="CASCADE"), nullable=False
    )
    match_id: Mapped[str] = mapped_column(
        Text, ForeignKey("match.match_id", ondelete="CASCADE"), nullable=False
    )
    method: Mapped[str] = mapped_column(Text, nullable=False)
    segments: Mapped[str] = mapped_column(Text, nullable=False)
    pauses: Mapped[str] = mapped_column(Text, nullable=False)
    quality: Mapped[str] = mapped_column(Text, nullable=False)
    verified: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class ReviewRow(Base):
    __tablename__ = "review"
    __table_args__ = (Index("ix_review_player", "player_id", "created_at"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    player_id: Mapped[str] = mapped_column(Text, ForeignKey("player.id"), nullable=False)
    match_id: Mapped[str] = mapped_column(Text, ForeignKey("match.match_id"), nullable=False)
    participant_id: Mapped[int] = mapped_column(Integer, nullable=False)
    media_asset_id: Mapped[str | None] = mapped_column(Text, ForeignKey("media_asset.id"))
    sync_map_id: Mapped[str | None] = mapped_column(Text, ForeignKey("sync_map.id"))
    rule_pack_version: Mapped[str] = mapped_column(Text, nullable=False)
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_tiers: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    summary_text: Mapped[str | None] = mapped_column(Text)
    overall_scores: Mapped[str | None] = mapped_column(Text)
    llm_provider: Mapped[str | None] = mapped_column(Text)
    llm_model: Mapped[str | None] = mapped_column(Text)
    llm_prompt_version: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_at: Mapped[int | None] = mapped_column(Integer)


class ConceptRow(Base):
    __tablename__ = "concept"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(Text, ForeignKey("concept.id"))
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    data_tier: Mapped[str] = mapped_column(Text, nullable=False)
    teachability: Mapped[float] = mapped_column(Float, nullable=False)
    roles: Mapped[str] = mapped_column(Text, nullable=False)
    phases: Mapped[str] = mapped_column(Text, nullable=False)


class RuleDefinitionRow(Base):
    __tablename__ = "rule_definition"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    concept_id: Mapped[str] = mapped_column(Text, ForeignKey("concept.id"), nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    severity_base: Mapped[str] = mapped_column(Text, nullable=False)
    data_tier: Mapped[str] = mapped_column(Text, nullable=False)
    patch_range: Mapped[str | None] = mapped_column(Text)
    definition_json: Mapped[str] = mapped_column(Text, nullable=False)


class FindingRow(Base):
    __tablename__ = "finding"
    __table_args__ = (
        Index("ix_finding_review_t", "review_id", "t_ms"),
        Index("ix_finding_concept", "concept_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    review_id: Mapped[str] = mapped_column(
        Text, ForeignKey("review.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    concept_id: Mapped[str] = mapped_column(Text, ForeignKey("concept.id"), nullable=False)
    t_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    t_end_ms: Mapped[int | None] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    gold_equivalent: Mapped[float | None] = mapped_column(Float)
    outcome: Mapped[str | None] = mapped_column(Text)
    map_x: Mapped[int | None] = mapped_column(Integer)
    map_y: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text)
    alternative: Mapped[str | None] = mapped_column(Text)
    explanation_source: Mapped[str] = mapped_column(Text, nullable=False)
    suppressed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    suppressed_by: Mapped[str | None] = mapped_column(Text)


class EvidenceRow(Base):
    __tablename__ = "evidence"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_id: Mapped[str] = mapped_column(
        Text, ForeignKey("finding.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    t_ms: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    provenance_json: Mapped[str | None] = mapped_column(Text)


class MetricValueRow(Base):
    __tablename__ = "metric_value"
    __table_args__ = (
        Index("ix_metric_review", "review_id", "metric_id"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[str] = mapped_column(
        Text, ForeignKey("review.id", ondelete="CASCADE"), nullable=False
    )
    metric_id: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str | None] = mapped_column(Text)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    baseline_key: Mapped[str | None] = mapped_column(Text)
    baseline_p50: Mapped[float | None] = mapped_column(Float)
    baseline_percentile: Mapped[float | None] = mapped_column(Float)
    detail_json: Mapped[str | None] = mapped_column(Text)


class CoachingItemRow(Base):
    __tablename__ = "coaching_item"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    review_id: Mapped[str] = mapped_column(
        Text, ForeignKey("review.id", ondelete="CASCADE"), nullable=False
    )
    root_concept_id: Mapped[str] = mapped_column(Text, ForeignKey("concept.id"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    is_focus: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_strength: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    issue_type: Mapped[str] = mapped_column(Text, nullable=False)
    impact_score: Mapped[float] = mapped_column(Float, nullable=False)
    gold_equivalent: Mapped[float | None] = mapped_column(Float)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    the_fix: Mapped[str | None] = mapped_column(Text)
    next_game_check: Mapped[str | None] = mapped_column(Text)
    exemplar_finding_id: Mapped[str | None] = mapped_column(Text, ForeignKey("finding.id"))


class CoachingItemFindingRow(Base):
    __tablename__ = "coaching_item_finding"

    coaching_item_id: Mapped[str] = mapped_column(
        Text, ForeignKey("coaching_item.id", ondelete="CASCADE"), primary_key=True
    )
    finding_id: Mapped[str] = mapped_column(
        Text, ForeignKey("finding.id", ondelete="CASCADE"), primary_key=True
    )


class FindingFeedbackRow(Base):
    __tablename__ = "finding_feedback"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_id: Mapped[str] = mapped_column(
        Text, ForeignKey("finding.id", ondelete="CASCADE"), nullable=False
    )
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class PlayerTrendRow(Base):
    __tablename__ = "player_trend"
    __table_args__ = (
        UniqueConstraint("player_id", "concept_id", "metric_id", "window_start"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    player_id: Mapped[str] = mapped_column(
        Text, ForeignKey("player.id", ondelete="CASCADE"), nullable=False
    )
    concept_id: Mapped[str | None] = mapped_column(Text, ForeignKey("concept.id"))
    metric_id: Mapped[str | None] = mapped_column(Text)
    window_start: Mapped[int] = mapped_column(Integer, nullable=False)
    window_end: Mapped[int] = mapped_column(Integer, nullable=False)
    n_matches: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    prev_value: Mapped[float | None] = mapped_column(Float)
    direction: Mapped[str | None] = mapped_column(Text)
    significance: Mapped[float | None] = mapped_column(Float)


class FocusCommitmentRow(Base):
    __tablename__ = "focus_commitment"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    player_id: Mapped[str] = mapped_column(Text, ForeignKey("player.id"), nullable=False)
    review_id: Mapped[str] = mapped_column(Text, ForeignKey("review.id"), nullable=False)
    concept_id: Mapped[str] = mapped_column(Text, ForeignKey("concept.id"), nullable=False)
    metric_id: Mapped[str | None] = mapped_column(Text)
    target_value: Mapped[float | None] = mapped_column(Float)
    comparison: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    resolved_review_id: Mapped[str | None] = mapped_column(Text, ForeignKey("review.id"))
    outcome: Mapped[str | None] = mapped_column(Text)


class PlayerChampionProfileRow(Base):
    __tablename__ = "player_champion_profile"
    __table_args__ = (UniqueConstraint("player_id", "champion_id", "role"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    player_id: Mapped[str] = mapped_column(Text, ForeignKey("player.id"), nullable=False)
    champion_id: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    games: Mapped[int] = mapped_column(Integer, nullable=False)
    aggregates_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)


class ChampionProfileRow(Base):
    __tablename__ = "champion_profile"

    champion_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patch: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    class_tags: Mapped[str] = mapped_column(Text, nullable=False)
    behavior_tags: Mapped[str] = mapped_column(Text, nullable=False)
    power_spikes: Mapped[str] = mapped_column(Text, nullable=False)
    win_condition: Mapped[str] = mapped_column(Text, nullable=False)
    typical_build: Mapped[str | None] = mapped_column(Text)
    abilities: Mapped[str] = mapped_column(Text, nullable=False)


class BaselineStatRow(Base):
    __tablename__ = "baseline_stat"

    metric_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tier: Mapped[str] = mapped_column(Text, primary_key=True)
    role: Mapped[str] = mapped_column(Text, primary_key=True)
    champion_class: Mapped[str] = mapped_column(Text, primary_key=True, default="ALL")
    patch: Mapped[str] = mapped_column(Text, primary_key=True)
    phase: Mapped[str] = mapped_column(Text, primary_key=True)
    n: Mapped[int] = mapped_column(Integer, nullable=False)
    p10: Mapped[float | None] = mapped_column(Float)
    p25: Mapped[float | None] = mapped_column(Float)
    p50: Mapped[float | None] = mapped_column(Float)
    p75: Mapped[float | None] = mapped_column(Float)
    p90: Mapped[float | None] = mapped_column(Float)
    mean: Mapped[float | None] = mapped_column(Float)
    stddev: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)


class GameplaySourceRow(Base):
    __tablename__ = "gameplay_source"
    __table_args__ = (
        UniqueConstraint("match_id", "source_uri", name="uq_gameplay_source_match_uri"),
        Index("ix_gameplay_source_match", "match_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    match_id: Mapped[str] = mapped_column(Text, ForeignKey("match.match_id"), nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_uri: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    platform_scope: Mapped[str] = mapped_column(Text, nullable=False)
    media_asset_id: Mapped[str | None] = mapped_column(Text, ForeignKey("media_asset.id"))
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)


class RoflSourceDetailRow(Base):
    __tablename__ = "rofl_source_detail"

    gameplay_source_id: Mapped[str] = mapped_column(
        Text, ForeignKey("gameplay_source.id", ondelete="CASCADE"), primary_key=True
    )
    platform_id: Mapped[str | None] = mapped_column(Text)
    game_id: Mapped[int | None] = mapped_column(Integer)
    declared_patch: Mapped[str | None] = mapped_column(Text)
    declared_length_ms: Mapped[int | None] = mapped_column(Integer)
    identify_method: Mapped[str] = mapped_column(Text, nullable=False)
    header_parse_status: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
    magic: Mapped[str | None] = mapped_column(Text)
    raw_metadata_json: Mapped[str | None] = mapped_column(Text)


class ClockMapRow(Base):
    __tablename__ = "clock_map"
    __table_args__ = (Index("ix_clock_map_source", "gameplay_source_id"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    gameplay_source_id: Mapped[str] = mapped_column(
        Text, ForeignKey("gameplay_source.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    offset_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rate: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    confidence: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    anchor_count: Mapped[int | None] = mapped_column(Integer)
    residual_ms: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class ReplaySessionRow(Base):
    __tablename__ = "replay_session"
    __table_args__ = (Index("ix_replay_session_source", "gameplay_source_id"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    gameplay_source_id: Mapped[str] = mapped_column(
        Text, ForeignKey("gameplay_source.id", ondelete="CASCADE"), nullable=False
    )
    replay_api_base: Mapped[str | None] = mapped_column(Text)
    replay_api_port: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[int] = mapped_column(Integer, nullable=False)
    ended_at: Mapped[int | None] = mapped_column(Integer)


class CaptureIntervalRow(Base):
    __tablename__ = "capture_interval"
    __table_args__ = (Index("ix_capture_interval_source_t", "gameplay_source_id", "t_start_ms"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    gameplay_source_id: Mapped[str] = mapped_column(
        Text, ForeignKey("gameplay_source.id", ondelete="CASCADE"), nullable=False
    )
    t_start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    t_end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class MediaArtifactRow(Base):
    __tablename__ = "media_artifact"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    capture_interval_id: Mapped[str] = mapped_column(
        Text, ForeignKey("capture_interval.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
