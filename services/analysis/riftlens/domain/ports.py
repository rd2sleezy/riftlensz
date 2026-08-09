from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PlayerRecord:
    id: str
    display_name: str
    is_local_user: int
    created_at: int


@dataclass(frozen=True)
class PlayerAccountRecord:
    id: str
    player_id: str
    puuid: str
    game_name: str
    tag_line: str
    platform: str
    region: str
    summoner_level: int | None
    tier: str | None
    rank_division: str | None
    league_points: int | None
    rank_updated_at: int | None


@dataclass(frozen=True)
class MatchRecord:
    match_id: str
    platform: str
    region: str
    queue_id: int
    map_id: int
    game_version: str
    patch: str
    game_creation: int
    game_start: int
    game_duration_ms: int
    game_end_ts: int | None
    winning_team: int | None
    raw_match_blob: str | None
    raw_timeline_blob: str | None
    ingested_at: int


@dataclass(frozen=True)
class MatchParticipationRecord:
    id: str
    match_id: str
    participant_id: int
    puuid: str
    team_id: int
    champion_id: int
    champion_name: str
    team_position: str | None
    individual_position: str | None
    lane_opponent_participant_id: int | None
    win: int
    kills: int | None
    deaths: int | None
    assists: int | None
    total_cs: int | None
    gold_earned: int | None
    gold_spent: int | None
    vision_score: int | None
    summoner1_id: int | None
    summoner2_id: int | None
    items: str | None
    perks: str | None
    challenges: str | None
    stats_json: str


@dataclass(frozen=True)
class TimelineEventRecord:
    match_id: str
    t_ms: int
    type: str
    participant_id: int | None
    victim_id: int | None
    killer_id: int | None
    pos_x: int | None
    pos_y: int | None
    payload: str
    id: int | None = None


@dataclass(frozen=True)
class ParticipantFrameRecord:
    match_id: str
    t_ms: int
    participant_id: int
    pos_x: int | None
    pos_y: int | None
    current_gold: int | None
    total_gold: int | None
    gold_per_second: int | None
    xp: int | None
    level: int | None
    minions_killed: int | None
    jungle_minions_killed: int | None
    health: int | None
    health_max: int | None
    power: int | None
    power_max: int | None
    total_damage_done_to_champions: int | None
    total_damage_taken: int | None
    champion_stats: str | None
    damage_stats: str | None


@dataclass(frozen=True)
class MediaAssetRecord:
    id: str
    content_hash: str
    original_path: str
    playable_path: str | None
    proxy_path: str | None
    thumbnail_sheet_path: str | None
    container: str | None
    codec: str | None
    pix_fmt: str | None
    width: int | None
    height: int | None
    fps_num: int | None
    fps_den: int | None
    duration_ms: int
    size_bytes: int
    source_kind: str
    layout_profile_id: str | None
    quality_score: float | None
    imported_at: int
    last_accessed_at: int


@dataclass(frozen=True)
class LayoutProfileRecord:
    id: str
    width: int | None
    height: int | None
    ui_scale_estimate: float | None
    minimap_flipped: int
    minimap_rect: str
    clock_rect: str
    regions: str
    occluded_regions: str | None
    world_to_minimap_affine: str | None
    created_at: int


@dataclass(frozen=True)
class SyncMapRecord:
    id: str
    media_asset_id: str
    match_id: str
    method: str
    segments: str
    pauses: str
    quality: str
    verified: int
    created_at: int


@dataclass(frozen=True)
class ReviewRecord:
    id: str
    player_id: str
    match_id: str
    participant_id: int
    media_asset_id: str | None
    sync_map_id: str | None
    rule_pack_version: str
    engine_version: str
    analysis_tiers: str
    status: str
    summary_text: str | None
    overall_scores: str | None
    llm_provider: str | None
    llm_model: str | None
    llm_prompt_version: str | None
    created_at: int
    completed_at: int | None


@dataclass(frozen=True)
class FindingRecord:
    id: str
    review_id: str
    rule_id: str
    rule_version: int
    concept_id: str
    t_ms: int
    t_end_ms: int | None
    severity: str
    confidence: float
    gold_equivalent: float | None
    outcome: str | None
    map_x: int | None
    map_y: int | None
    title: str
    explanation: str | None
    alternative: str | None
    explanation_source: str
    suppressed: int
    suppressed_by: str | None


@dataclass(frozen=True)
class EvidenceRecord:
    finding_id: str
    kind: str
    label: str
    value_json: str
    t_ms: int | None
    source: str
    confidence: float | None
    provenance_json: str | None
    id: int | None = None


@dataclass(frozen=True)
class FindingFeedbackRecord:
    finding_id: str
    verdict: str
    note: str | None
    created_at: int
    id: int | None = None


@dataclass(frozen=True)
class MetricValueRecord:
    review_id: str
    metric_id: str
    phase: str | None
    value: float
    unit: str | None
    confidence: float
    baseline_key: str | None
    baseline_p50: float | None
    baseline_percentile: float | None
    detail_json: str | None
    id: int | None = None


@dataclass(frozen=True)
class CoachingItemRecord:
    id: str
    review_id: str
    root_concept_id: str
    rank: int
    is_focus: int
    is_strength: int
    issue_type: str
    impact_score: float
    gold_equivalent: float | None
    occurrences: int
    confidence: float
    title: str
    body: str
    the_fix: str | None
    next_game_check: str | None
    exemplar_finding_id: str | None
    finding_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlayerTrendRecord:
    id: str
    player_id: str
    concept_id: str | None
    metric_id: str | None
    window_start: int
    window_end: int
    n_matches: int
    value: float
    prev_value: float | None
    direction: str | None
    significance: float | None


@dataclass(frozen=True)
class FocusCommitmentRecord:
    id: str
    player_id: str
    review_id: str
    concept_id: str
    metric_id: str | None
    target_value: float | None
    comparison: str | None
    created_at: int
    resolved_review_id: str | None
    outcome: str | None


@dataclass(frozen=True)
class PlayerChampionProfileRecord:
    id: str
    player_id: str
    champion_id: int
    role: str
    games: int
    aggregates_json: str
    updated_at: int


@dataclass(frozen=True)
class ChampionProfileRecord:
    champion_id: int
    patch: str
    name: str
    class_tags: str
    behavior_tags: str
    power_spikes: str
    win_condition: str
    typical_build: str | None
    abilities: str


@dataclass(frozen=True)
class BaselineStatRecord:
    metric_id: str
    tier: str
    role: str
    champion_class: str
    patch: str
    phase: str
    n: int
    p10: float | None
    p25: float | None
    p50: float | None
    p75: float | None
    p90: float | None
    mean: float | None
    stddev: float | None
    updated_at: int


class PlayerRepository(Protocol):
    async def upsert_player(self, row: PlayerRecord) -> None:
        """Insert or replace a player row. Assumes ``row.id`` is a ULID."""

    async def get_player(self, player_id: str) -> PlayerRecord | None:
        """Return the player or None. Assumes ``player_id`` is the local PK."""

    async def upsert_account(self, row: PlayerAccountRecord) -> None:
        """Insert or replace a linked Riot account. Assumes ``puuid`` is unique."""

    async def get_account_by_puuid(self, puuid: str) -> PlayerAccountRecord | None:
        """Return the account for ``puuid`` or None. Assumes PUUID is Riot-canonical."""

    async def upsert_trend(self, row: PlayerTrendRecord) -> None:
        """Insert or replace a cross-game trend row. Assumes player exists."""

    async def get_trend(self, trend_id: str) -> PlayerTrendRecord | None:
        """Return a trend row or None. Assumes ``trend_id`` is the local PK."""

    async def upsert_champion_profile(self, row: PlayerChampionProfileRecord) -> None:
        """Insert or replace a per-champion aggregate. Assumes player exists."""

    async def get_champion_profile(
        self, player_id: str, champion_id: int, role: str
    ) -> PlayerChampionProfileRecord | None:
        """Return the player+champion+role profile or None. Assumes role is a stored string."""


class MatchRepository(Protocol):
    async def upsert_match(self, row: MatchRecord) -> None:
        """Insert or replace the match header. Assumes ``match_id`` is Riot-native."""

    async def get_match(self, match_id: str) -> MatchRecord | None:
        """Return the match header or None. Assumes ``match_id`` is Riot-native."""

    async def replace_participations(
        self, match_id: str, rows: Sequence[MatchParticipationRecord]
    ) -> None:
        """Replace all participation rows for a match. Assumes ``match_id`` already exists."""

    async def list_participations(self, match_id: str) -> Sequence[MatchParticipationRecord]:
        """Return participations ordered by participant_id. Assumes the match may be missing."""

    async def replace_timeline_events(
        self, match_id: str, rows: Sequence[TimelineEventRecord]
    ) -> None:
        """Replace timeline events for a match. Assumes ``match_id`` already exists."""

    async def list_timeline_events(self, match_id: str) -> Sequence[TimelineEventRecord]:
        """Return events ordered by t_ms then id. Assumes the match may be missing."""

    async def replace_participant_frames(
        self, match_id: str, rows: Sequence[ParticipantFrameRecord]
    ) -> None:
        """Replace frame rows for a match. Assumes ``match_id`` already exists."""

    async def list_participant_frames(self, match_id: str) -> Sequence[ParticipantFrameRecord]:
        """Return frames ordered by t_ms, participant_id. Assumes the match may be missing."""


class MediaRepository(Protocol):
    async def upsert_asset(self, row: MediaAssetRecord) -> None:
        """Insert or replace a media asset. Assumes ``content_hash`` is unique."""

    async def get_asset(self, media_id: str) -> MediaAssetRecord | None:
        """Return a media asset or None. Assumes ``media_id`` is a ULID."""

    async def upsert_layout_profile(self, row: LayoutProfileRecord) -> None:
        """Insert or replace a layout profile. Assumes ``row.id`` is a ULID."""

    async def get_layout_profile(self, profile_id: str) -> LayoutProfileRecord | None:
        """Return a layout profile or None. Assumes ``profile_id`` is a ULID."""


class SyncRepository(Protocol):
    async def upsert(self, row: SyncMapRecord) -> None:
        """Insert or replace a sync map. Assumes media and match rows exist."""

    async def get(self, sync_id: str) -> SyncMapRecord | None:
        """Return a sync map or None. Assumes ``sync_id`` is a ULID."""

    async def get_by_media_and_match(self, media_id: str, match_id: str) -> SyncMapRecord | None:
        """Return the unique sync map for a VOD+match pair, or None. Assumes FKs are valid."""


class ReviewRepository(Protocol):
    async def upsert(self, row: ReviewRecord) -> None:
        """Insert or replace a review. Assumes player and match rows exist."""

    async def get(self, review_id: str) -> ReviewRecord | None:
        """Return a review or None. Assumes ``review_id`` is a ULID."""

    async def list_for_player(self, player_id: str) -> Sequence[ReviewRecord]:
        """Return reviews for a player, newest first. Assumes ``player_id`` is a ULID."""


class FindingRepository(Protocol):
    async def add(self, finding: FindingRecord, evidence: Sequence[EvidenceRecord]) -> None:
        """Insert a finding and its evidence. Assumes review and concept rows exist."""

    async def get(self, finding_id: str) -> FindingRecord | None:
        """Return a finding or None. Assumes ``finding_id`` is a ULID."""

    async def list_for_review(self, review_id: str) -> Sequence[FindingRecord]:
        """Return findings ordered by t_ms. Assumes the review may be missing."""

    async def list_evidence(self, finding_id: str) -> Sequence[EvidenceRecord]:
        """Return evidence rows for a finding. Assumes the finding may be missing."""

    async def add_feedback(self, row: FindingFeedbackRecord) -> None:
        """Insert user feedback. Assumes the finding exists."""

    async def list_feedback(self, finding_id: str) -> Sequence[FindingFeedbackRecord]:
        """Return feedback rows for a finding. Assumes the finding may be missing."""


class MetricRepository(Protocol):
    async def replace_for_review(self, review_id: str, rows: Sequence[MetricValueRecord]) -> None:
        """Replace metric values for a review. Assumes the review exists."""

    async def list_for_review(self, review_id: str) -> Sequence[MetricValueRecord]:
        """Return metric values for a review. Assumes the review may be missing."""

    async def upsert_baseline(self, row: BaselineStatRecord) -> None:
        """Insert or replace a corpus baseline cell. Assumes keys match the PK."""

    async def get_baseline(
        self,
        metric_id: str,
        tier: str,
        role: str,
        champion_class: str,
        patch: str,
        phase: str,
    ) -> BaselineStatRecord | None:
        """Return one baseline cell or None. Assumes the six-part PK is complete."""

    async def upsert_champion_profile(self, row: ChampionProfileRecord) -> None:
        """Insert or replace patch-scoped champion reference data. Assumes PK is set."""

    async def get_champion_profile(
        self, champion_id: int, patch: str
    ) -> ChampionProfileRecord | None:
        """Return champion reference data or None. Assumes ``patch`` is normalized."""


class CoachingRepository(Protocol):
    async def replace_for_review(self, review_id: str, rows: Sequence[CoachingItemRecord]) -> None:
        """Replace coaching items and their finding links. Assumes review/findings exist."""

    async def list_for_review(self, review_id: str) -> Sequence[CoachingItemRecord]:
        """Return coaching items ordered by rank. Assumes the review may be missing."""

    async def upsert_focus_commitment(self, row: FocusCommitmentRecord) -> None:
        """Insert or replace a focus commitment. Assumes player, review, and concept exist."""

    async def get_focus_commitment(self, commitment_id: str) -> FocusCommitmentRecord | None:
        """Return a focus commitment or None. Assumes ``commitment_id`` is a ULID."""
