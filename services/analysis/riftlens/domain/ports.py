from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from riftlens.domain.clock_map import ClockMap
from riftlens.domain.gameplay_source import GameplaySource, PlaybackState, SourceCapability


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
class GameplaySourceRecord:
    id: str
    match_id: str
    source_type: str
    source_uri: str
    content_hash: str | None
    display_name: str
    duration_ms: int
    status: str
    platform_scope: str
    created_at: int
    updated_at: int
    media_asset_id: str | None = None


@dataclass(frozen=True)
class RoflSourceDetailRecord:
    gameplay_source_id: str
    platform_id: str | None
    game_id: int | None
    declared_patch: str | None
    declared_length_ms: int | None
    identify_method: str
    header_parse_status: str
    file_size_bytes: int | None
    magic: str | None
    raw_metadata_json: str | None = None


@dataclass(frozen=True)
class ClockCalibrationRecord:
    id: str
    gameplay_source_id: str
    kind: str
    offset_ms: int
    rate: float
    confidence: str
    method: str
    anchor_count: int | None
    residual_ms: int | None
    is_active: int
    created_at: int
    clock: ClockMap
    stdev_ms: float | None = None
    warning: str | None = None
    media_asset_id: str | None = None


@dataclass(frozen=True)
class ReplaySessionAuditRecord:
    id: str
    gameplay_source_id: str
    replay_api_base: str | None
    replay_api_port: int | None
    state: str
    last_error: str | None
    started_at: int
    ended_at: int | None


@dataclass(frozen=True)
class CaptureIntervalRecord:
    """One R.10 capture row. Game times are canonical ms; source times are Replay API ms."""

    id: str
    gameplay_source_id: str
    match_id: str | None
    clock_map_id: str | None
    t_start_ms: int
    t_end_ms: int
    reason: str
    mode: str
    fps: float | None
    status: str
    progress: float
    retention_class: str
    created_at: int
    t_start_source_ms: int | None = None
    t_end_source_ms: int | None = None
    review_id: str | None = None
    error_code: str | None = None
    artifact_count: int = 0
    total_bytes: int = 0
    completed_at: int | None = None
    manifest_json: str | None = None


@dataclass(frozen=True)
class MediaArtifactRecord:
    """One captured file on disk. ``path`` is absolute; ``game_t_ms`` is authoritative."""

    id: str
    capture_interval_id: str
    kind: str
    path: str
    content_hash: str | None
    created_at: int
    game_t_ms: int | None = None
    source_t_ms: int | None = None
    frame_index: int | None = None
    retention_class: str = "review"
    bytes: int | None = None
    width: int | None = None
    height: int | None = None
    expires_at: int | None = None


@dataclass(frozen=True)
class GameplaySourceSnapshot:
    source: GameplaySourceRecord
    rofl: RoflSourceDetailRecord | None
    clock: ClockCalibrationRecord | None
    file_present: bool


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


class GameplayRepository(Protocol):
    async def upsert_source(
        self,
        row: GameplaySourceRecord,
        *,
        rofl: RoflSourceDetailRecord | None = None,
    ) -> str:
        """Insert or update a gameplay source. Assumes the match row exists."""

    async def get_source(self, source_id: str) -> GameplaySourceSnapshot | None:
        """Return a source snapshot or None. Revalidates path existence at read time."""

    async def list_sources_for_match(self, match_id: str) -> Sequence[GameplaySourceSnapshot]:
        """Return sources for a match, newest first. Missing matches yield an empty list."""

    async def replace_clock(
        self,
        source_id: str,
        clock: ClockMap,
        *,
        method: str,
        created_at: int,
        anchor_count: int | None = None,
        residual_ms: int | None = None,
        stdev_ms: float | None = None,
        warning: str | None = None,
        calibration_id: str | None = None,
        media_asset_id: str | None = None,
    ) -> ClockCalibrationRecord:
        """Append a clock_map row and mark it active. Assumes the source exists."""

    async def get_active_clock(self, source_id: str) -> ClockCalibrationRecord | None:
        """Return the active ClockMap calibration, or None when none is stored."""

    async def update_source_status(
        self, source_id: str, status: str, *, updated_at: int
    ) -> None:
        """Update cached source status. Does not imply the file or session is live."""

    async def revalidate_source(self, source_id: str, *, updated_at: int) -> GameplaySourceSnapshot:
        """Refresh the unavailable/linked hint from disk. Assumes the source exists."""

    async def record_session(self, row: ReplaySessionAuditRecord) -> None:
        """Append a historical replay-session audit row. Does not restore liveness."""

    async def list_sessions(self, source_id: str) -> Sequence[ReplaySessionAuditRecord]:
        """Return audit rows for a source, newest first. Missing sources yield []."""


class CaptureRepository(Protocol):
    """R.10 capture_interval/media_artifact persistence. Never deletes files itself."""

    async def upsert_interval(self, row: CaptureIntervalRecord) -> None:
        """Insert or replace a capture row. Assumes the gameplay source exists."""

    async def get_interval(self, capture_id: str) -> CaptureIntervalRecord | None:
        """Return one capture row or None. Assumes ``capture_id`` is a ULID."""

    async def list_for_source(self, source_id: str) -> Sequence[CaptureIntervalRecord]:
        """Return captures for a source, newest first. Missing sources yield []."""

    async def list_for_review(self, review_id: str) -> Sequence[CaptureIntervalRecord]:
        """Return captures charged to a review, newest first. Missing reviews yield []."""

    async def list_by_retention(self, retention_class: str) -> Sequence[CaptureIntervalRecord]:
        """Return captures in one retention class, oldest first (LRU order)."""

    async def list_ephemeral(self) -> Sequence[CaptureIntervalRecord]:
        """Return EPHEMERAL captures, oldest first. Deleted at session teardown."""

    async def list_by_status(self, statuses: Sequence[str]) -> Sequence[CaptureIntervalRecord]:
        """Return captures in any of ``statuses``, oldest first."""

    async def list_all(self) -> Sequence[CaptureIntervalRecord]:
        """Return every capture row, oldest first. Used by startup GC."""

    async def update_status(
        self,
        capture_id: str,
        status: str,
        *,
        progress: float | None = None,
        error_code: str | None = None,
        completed_at: int | None = None,
        artifact_count: int | None = None,
        total_bytes: int | None = None,
        manifest_json: str | None = None,
    ) -> None:
        """Patch lifecycle fields. Omitted arguments leave the stored value unchanged."""

    async def replace_artifacts(
        self, capture_id: str, rows: Sequence[MediaArtifactRecord]
    ) -> None:
        """Delete then insert artifact rows so re-runs stay idempotent."""

    async def list_artifacts(self, capture_id: str) -> Sequence[MediaArtifactRecord]:
        """Return artifacts ordered by frame index then id. Missing captures yield []."""

    async def sum_usage_for_review(self, review_id: str) -> tuple[float, int, int]:
        """Return ``(seconds, artifacts, bytes)`` already charged to ``review_id``."""

    async def delete_interval(self, capture_id: str) -> None:
        """Delete a capture row; artifacts cascade. Callers delete the files."""


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


@runtime_checkable
class PatchData(Protocol):
    """Patch-scoped game constants. Metrics/features must not hardcode these values."""

    def item_gold(self, item_id: int) -> int:
        """Return total item cost, or 0 when unknown. Assumes load() or load_bundled() ran."""

    def item_purchase_cost(self, item_id: int) -> int | None:
        """Return incremental buy gold (Data Dragon ``gold.base``), or None if missing."""

    def item_sell_value(self, item_id: int) -> int | None:
        """Return sell refund gold, or None if missing."""

    def average_cs_gold(self, *, jungle: bool = False) -> float | None:
        """Return average gold per CS tick. Assumes patch constants were loaded."""

    def passive_gold(self, start_ms: int, end_ms: int) -> float:
        """Return passive gold accrued on ``[start_ms, end_ms)``. Assumes ms game clock."""

    def gold_per_second_rate(self, raw: int) -> float | None:
        """Return gold/ms implied by timeline ``goldPerSecond``, or None if unverified."""

    def respawn_ms(self, level: int, death_t_ms: int) -> int | None:
        """Return respawn duration in ms for ``level`` at ``death_t_ms``, or None."""

    def health_regen_per_ms(self, regen_stat: float) -> float:
        """Return HP/ms from timeline ``healthRegen``, or 0 when the unit is unverified."""

    def item_ids_named(self, *names: str) -> frozenset[int]:
        """Return item ids whose Data Dragon name matches any of ``names`` (casefold)."""

    def item_ids_name_contains(self, *needles: str) -> frozenset[int]:
        """Return item ids whose name contains any needle (casefold). Assumes bundled items."""

    def named_constant(self, key: str) -> object:
        """Return a patch-constants.yaml value, or None. Assumes load_bundled/load ran."""


@runtime_checkable
class PlaybackControl(Protocol):
    """Transport control for a GameplaySource. Implementations live outside domain."""

    def read_state(self) -> PlaybackState:
        """Return the current playback snapshot. Assumes the source is open."""

    def pause(self) -> PlaybackState:
        """Pause playback and return the resulting state. Assumes PAUSE is supported."""

    def resume(self) -> PlaybackState:
        """Resume playback and return the resulting state. Assumes RESUME is supported."""

    def seek_to_game_ms(self, t_game_ms: int) -> PlaybackState:
        """Seek to canonical game time. Assumes SEEK is supported and ``t_game_ms`` is int ms."""


@runtime_checkable
class LiveClientDataPort(Protocol):
    """Optional live-client reads during replay. Absence must not fail Replay API proof."""

    def is_available(self) -> bool:
        """Return True when any live-client snapshot can be read. Assumes replay is running."""

    def active_player_available(self) -> bool:
        """Return True when activeplayer is readable. R.0 observed this may be false."""


@runtime_checkable
class GameplaySourcePort(Protocol):
    """Resolves the current gameplay source. Does not launch or persist anything."""

    def current_source(self) -> GameplaySource:
        """Return the active GameplaySource. Assumes a review session selected one."""

    def capabilities(self) -> frozenset[SourceCapability]:
        """Return advertised capabilities. Assumes ``current_source`` would succeed."""
