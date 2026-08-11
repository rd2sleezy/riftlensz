import { z } from 'zod'

export const IPC = {
  getSidecarStatus: 'rift:sidecar:get-status',
  sidecarStatusEvent: 'rift:sidecar:status',
  health: 'rift:sidecar:health',
  restartSidecar: 'rift:sidecar:restart',
  listReviews: 'rift:reviews:list',
  getReview: 'rift:reviews:get',
  openFixtureReview: 'rift:reviews:from-fixture',
  pickVod: 'rift:media:pick',
  probeVod: 'rift:media:probe',
  buildManualSync: 'rift:sync:manual',
  getDesktopPlatform: 'rift:desktop:platform',
  pickRofl: 'rift:gameplay:pick-rofl',
  importReplay: 'rift:gameplay:import',
  getGameplayStatus: 'rift:gameplay:status',
  checkGameplayEnvironment: 'rift:gameplay:environment',
  openReplay: 'rift:gameplay:open',
  closeReplay: 'rift:gameplay:close',
  revealGameplay: 'rift:gameplay:reveal',
  overlayOpen: 'rift:overlay:open',
  overlayClose: 'rift:overlay:close',
  overlayHide: 'rift:overlay:hide',
  overlayGetPrefs: 'rift:overlay:get-prefs',
  overlaySetPrefs: 'rift:overlay:set-prefs',
  overlayGetContext: 'rift:overlay:get-context',
  overlaySetBounds: 'rift:overlay:set-bounds',
  overlayUpdateSession: 'rift:overlay:update-session'
} as const

export const IPC_RENDERER_ALLOWLIST = [
  'getSidecarStatus',
  'onSidecarStatus',
  'health',
  'restartSidecar',
  'listReviews',
  'getReview',
  'openFixtureReview',
  'pickVod',
  'probeVod',
  'buildManualSync',
  'getDesktopPlatform',
  'pickRofl',
  'importReplay',
  'getGameplayStatus',
  'checkGameplayEnvironment',
  'openReplay',
  'closeReplay',
  'revealGameplay',
  'overlayOpen',
  'overlayClose',
  'overlayHide',
  'overlayGetPrefs',
  'overlaySetPrefs',
  'overlayGetContext',
  'overlaySetBounds',
  'overlayUpdateSession'
] as const

export const SidecarStateSchema = z.enum([
  'starting',
  'ready',
  'unhealthy',
  'restarting',
  'failed'
])

export const SidecarStatusSchema = z.object({
  state: SidecarStateSchema,
  version: z.string().optional(),
  port: z.number().int().optional(),
  pid: z.number().int().optional(),
  dbPath: z.string().optional(),
  error: z.string().optional()
})

export const HealthSchema = z.object({
  status: z.literal('ok'),
  version: z.string(),
  python: z.string(),
  db_path: z.string(),
  uptime_ms: z.number().int()
})

export const ErrorResultSchema = z.object({
  ok: z.literal(false),
  code: z.enum([
    'SIDECAR_UNAVAILABLE',
    'NOT_FOUND',
    'INVALID_VOD',
    'UNSUPPORTED_CODEC',
    'SYNC_INVALID',
    'VALIDATION',
    'UNKNOWN'
  ]),
  message: z.string()
})

export const ProvenanceSchema = z.object({
  producer: z.string(),
  producer_version: z.number(),
  upstream: z.array(z.string())
})

export const EvidenceSchema = z.object({
  kind: z.string(),
  label: z.string(),
  value: z.unknown(),
  source: z.string(),
  t_ms: z.number().int().nullable(),
  confidence: z.number().nullable(),
  provenance: ProvenanceSchema.nullable(),
  quarantined: z.boolean()
})

export const FindingSchema = z.object({
  id: z.string(),
  rule_id: z.string(),
  rule_version: z.number().int(),
  concept_id: z.string(),
  t_ms: z.number().int(),
  t_end_ms: z.number().int().nullable(),
  t_mmss: z.string(),
  severity: z.string(),
  confidence: z.number(),
  title: z.string(),
  gold_equivalent: z.number().nullable(),
  outcome: z.string().nullable(),
  map_x: z.number().nullable(),
  map_y: z.number().nullable(),
  explanation: z.string().nullable(),
  alternative: z.string().nullable(),
  explanation_source: z.string(),
  suppressed: z.boolean(),
  suppressed_by: z.string().nullable(),
  evidence: z.array(EvidenceSchema).min(1)
})

export const TimestampMarkerSchema = z.object({
  t_ms: z.number().int(),
  t_mmss: z.string(),
  t_video_ms: z.number().int().nullable(),
  seek_video_ms: z.number().int().nullable(),
  covered: z.boolean(),
  uncertain: z.boolean(),
  reason: z.string().nullable()
})

export const CoachingItemSchema = z.object({
  id: z.string(),
  root_concept_id: z.string(),
  rank: z.number().int(),
  is_focus: z.boolean(),
  is_strength: z.boolean(),
  issue_type: z.string(),
  impact_score: z.number(),
  gold_equivalent: z.number().nullable(),
  occurrences: z.number().int(),
  confidence: z.number(),
  certainty: z.string(),
  title: z.string(),
  body: z.string(),
  the_fix: z.string().nullable(),
  next_game_check: z.string().nullable(),
  exemplar_finding_id: z.string().nullable(),
  finding_ids: z.array(z.string()),
  evidence_timestamps_ms: z.array(z.number().int()),
  timestamps: z.array(TimestampMarkerSchema),
  grouping_reason: z.string(),
  cluster_id: z.string(),
  cost_summary: z.string(),
  exemplar: z
    .object({
      id: z.string(),
      t_ms: z.number().int(),
      t_mmss: z.string(),
      severity: z.string(),
      confidence: z.number(),
      title: z.string()
    })
    .nullable()
})

export const MetricSchema = z.object({
  metric_id: z.string(),
  value: z.number(),
  unit: z.string(),
  phase: z.string().nullable(),
  confidence: z.number(),
  baseline_percentile: z.number().nullable(),
  sample_context: z.string(),
  detail: z.record(z.unknown()),
  quarantined: z.boolean()
})

export const SyncSegmentSchema = z.object({
  video_start_ms: z.number().int(),
  video_end_ms: z.number().int(),
  offset_ms: z.number().int(),
  n_anchors: z.number().int(),
  residual_p95_ms: z.number()
})

export const SyncQualitySchema = z.object({
  method: z.string(),
  n_readings: z.number().int(),
  n_inliers: z.number().int(),
  inlier_ratio: z.number(),
  residual_p50_ms: z.number(),
  residual_p95_ms: z.number(),
  coverage: z.number(),
  n_segments: z.number().int(),
  verdict: z.enum(['EXCELLENT', 'GOOD', 'DEGRADED', 'FAILED'])
})

export const SyncMapSchema = z.object({
  segments: z.array(SyncSegmentSchema),
  pauses: z.array(
    z.object({
      video_start_ms: z.number().int(),
      video_end_ms: z.number().int(),
      t_game_ms: z.number().int()
    })
  ),
  quality: SyncQualitySchema,
  media_asset_id: z.string(),
  match_id: z.string(),
  version: z.number().int(),
  verified: z.boolean()
})

export const MediaProbeSchema = z.object({
  path: z.string(),
  width: z.number().int(),
  height: z.number().int(),
  codec_name: z.string(),
  pix_fmt: z.string(),
  r_frame_rate: z.string(),
  avg_frame_rate: z.string(),
  duration_s: z.number(),
  duration_ms: z.number().int(),
  start_time_s: z.number(),
  nb_frames: z.number().int().nullable(),
  bit_rate: z.number().int().nullable(),
  size_bytes: z.number().int(),
  has_faststart: z.boolean(),
  content_hash: z.string(),
  aspect_ratio: z.number()
})

export const ReviewPresentationSchema = z.object({
  id: z.string(),
  player_id: z.string(),
  match_id: z.string(),
  participant_id: z.number().int(),
  champion: z.string(),
  role: z.string(),
  rank: z.string(),
  patch: z.string(),
  duration_ms: z.number().int(),
  result: z.string().nullable(),
  rule_pack_version: z.string(),
  engine_version: z.string(),
  llm_provider: z.string(),
  status: z.string(),
  summary_text: z.string().nullable(),
  unpaired_match_timeline: z.boolean(),
  fixture_warning: z.string().nullable(),
  fixture_id: z.string().nullable().optional(),
  created_at: z.number().int(),
  completed_at: z.number().int().nullable(),
  focus_items: z.array(CoachingItemSchema),
  secondary_items: z.array(CoachingItemSchema),
  strengths: z.array(CoachingItemSchema),
  metrics: z.array(MetricSchema),
  findings: z.array(FindingSchema),
  sync_map: SyncMapSchema.nullable(),
  media: z.record(z.unknown()).nullable(),
  overall_scores: z.record(z.number())
})

export const ReviewSummarySchema = z.object({
  id: z.string(),
  match_id: z.string(),
  participant_id: z.number().int(),
  champion: z.string(),
  role: z.string(),
  rank: z.string().nullable().optional(),
  patch: z.string().nullable().optional(),
  duration_ms: z.number().int(),
  result: z.string().nullable(),
  status: z.string().nullable().optional(),
  unpaired_match_timeline: z.boolean(),
  fixture_warning: z.string().nullable().optional(),
  fixture_id: z.string().nullable().optional(),
  created_at: z.number().int().nullable().optional(),
  focus_count: z.number().int(),
  has_sync: z.boolean()
})

export const ListReviewsResultSchema = z.discriminatedUnion('ok', [
  z.object({ ok: z.literal(true), reviews: z.array(ReviewSummarySchema) }),
  ErrorResultSchema
])

export const GetReviewResultSchema = z.discriminatedUnion('ok', [
  z.object({ ok: z.literal(true), review: ReviewPresentationSchema }),
  ErrorResultSchema
])

export const OpenFixtureInputSchema = z.object({
  fixtureId: z.enum(['NA1_fixture_a', 'NA1_fixture_b', 'NA1_fixture_c']),
  participantId: z.number().int().min(1).max(10),
  rank: z.string().optional()
})

export const ProbeVodInputSchema = z.object({
  path: z.string().min(1)
})

export const ProbeVodResultSchema = z.discriminatedUnion('ok', [
  z.object({
    ok: z.literal(true),
    playable: z.boolean(),
    handling: z.string(),
    ingest_errors: z.array(z.string()),
    message: z.string().nullable(),
    probe: MediaProbeSchema,
    mediaUrl: z.string()
  }),
  ErrorResultSchema
])

export const PickVodResultSchema = z.discriminatedUnion('ok', [
  z.object({ ok: z.literal(true), path: z.string().nullable() }),
  ErrorResultSchema
])

export const BuildManualSyncInputSchema = z.object({
  matchId: z.string().min(1),
  videoDurationMs: z.number().int().positive(),
  matchDurationMs: z.number().int().positive().nullable().optional(),
  mediaAssetId: z.string().optional(),
  anchors: z
    .array(
      z.object({
        t_video_ms: z.number().int(),
        t_game_ms: z.number().int()
      })
    )
    .min(1)
})

export const BuildManualSyncResultSchema = z.discriminatedUnion('ok', [
  z.object({ ok: z.literal(true), sync_map: SyncMapSchema }),
  ErrorResultSchema
])

export type SidecarState = z.infer<typeof SidecarStateSchema>
export type SidecarStatus = z.infer<typeof SidecarStatusSchema>
export type HealthPayload = z.infer<typeof HealthSchema>
export type ErrorResult = z.infer<typeof ErrorResultSchema>
export type ReviewPresentation = z.infer<typeof ReviewPresentationSchema>
export type ReviewSummary = z.infer<typeof ReviewSummarySchema>
export type CoachingItem = z.infer<typeof CoachingItemSchema>
export type Finding = z.infer<typeof FindingSchema>
export type Evidence = z.infer<typeof EvidenceSchema>
export type MediaProbe = z.infer<typeof MediaProbeSchema>
export type SyncMapPayload = z.infer<typeof SyncMapSchema>
export type ListReviewsResult = z.infer<typeof ListReviewsResultSchema>
export type GetReviewResult = z.infer<typeof GetReviewResultSchema>
export type ProbeVodResult = z.infer<typeof ProbeVodResultSchema>
export type PickVodResult = z.infer<typeof PickVodResultSchema>
export type BuildManualSyncResult = z.infer<typeof BuildManualSyncResultSchema>
export type OpenFixtureInput = z.infer<typeof OpenFixtureInputSchema>

export const ReplayErrorPayloadSchema = z.object({
  code: z.string().min(1),
  message: z.string().min(1),
  suggested_action: z.string().nullable(),
  recoverable: z.boolean(),
  severity: z.string()
})

export const GameplaySourceSummarySchema = z.object({
  id: z.string(),
  display_name: z.string().nullable(),
  capabilities: z.array(z.string()),
  status: z.string(),
  file_present: z.boolean(),
  declared_patch: z.string().nullable(),
  duration_ms: z.number().int(),
  available: z.boolean(),
  unavailable_error: ReplayErrorPayloadSchema.nullable()
})

export const GameplayPlaybackSchema = z.object({
  t_source_ms: z.number().int(),
  length_ms: z.number().int(),
  paused: z.boolean(),
  seeking: z.boolean(),
  speed_milli: z.number().int(),
  t_game_ms: z.number().int().nullable()
})

export const GameplayStatusSchema = z.object({
  native_replay_supported: z.boolean(),
  match_id: z.string(),
  sources: z.array(GameplaySourceSummarySchema),
  active_source_id: z.string().nullable(),
  capabilities: z.array(z.string()),
  source_status: z.string().nullable(),
  file_present: z.boolean(),
  display_name: z.string().nullable(),
  declared_patch: z.string().nullable(),
  session_phase: z.string(),
  session_reached_ready: z.boolean(),
  session_owns_process: z.boolean(),
  clock_confidence: z.string().nullable(),
  clock_verified: z.boolean().nullable(),
  clock_method: z.string().nullable(),
  offset_ms: z.number().int().nullable(),
  residual_ms: z.number().nullable(),
  anchor_count: z.number().int().nullable(),
  error: ReplayErrorPayloadSchema.nullable(),
  warnings: z.array(ReplayErrorPayloadSchema),
  playback: GameplayPlaybackSchema.nullable().optional()
})

export const DesktopPlatformSchema = z.object({
  platform: z.string(),
  nativeReplaySupported: z.boolean()
})

export const PickRoflResultSchema = z.discriminatedUnion('ok', [
  z.object({ ok: z.literal(true), path: z.string().nullable() }),
  ErrorResultSchema
])

export const ImportReplayInputSchema = z.object({
  path: z.string().min(1),
  matchId: z.string().min(1)
})

export const ImportReplayResultSchema = z.discriminatedUnion('ok', [
  z.object({
    ok: z.literal(true),
    source_id: z.string(),
    match_id: z.string(),
    identity: z
      .object({
        platform_id: z.string().nullable(),
        game_id: z.number().int().nullable(),
        declared_patch: z.string().nullable(),
        declared_length_ms: z.number().int().nullable(),
        match_id_hint: z.string().nullable(),
        identify_method: z.string()
      })
      .nullable(),
    warnings: z.array(ReplayErrorPayloadSchema),
    status: GameplayStatusSchema
  }),
  z.object({
    ok: z.literal(false),
    code: z.string(),
    message: z.string(),
    suggested_action: z.string().nullable(),
    error: ReplayErrorPayloadSchema.nullable()
  })
])

export const GameplayMatchInputSchema = z.object({
  matchId: z.string().min(1),
  sourceId: z.string().min(1).nullable().optional()
})

export const GameplayStatusResultSchema = z.discriminatedUnion('ok', [
  z.object({ ok: z.literal(true), status: GameplayStatusSchema }),
  ErrorResultSchema
])

export const GameplayEnvironmentResultSchema = z.discriminatedUnion('ok', [
  z.object({
    ok: z.literal(true),
    native_replay_supported: z.boolean(),
    install_found: z.boolean(),
    replay_api_documented: z.boolean(),
    live_game: z.boolean(),
    error: ReplayErrorPayloadSchema.nullable(),
    warnings: z.array(ReplayErrorPayloadSchema)
  }),
  ErrorResultSchema
])

export const OpenReplayInputSchema = z.object({
  sourceId: z.string().min(1),
  matchId: z.string().min(1)
})

export const OpenReplayResultSchema = z.discriminatedUnion('ok', [
  z.object({
    ok: z.literal(true),
    session_phase: z.string(),
    session_reached_ready: z.literal(true),
    status: GameplayStatusSchema
  }),
  z.object({
    ok: z.literal(false),
    code: z.string(),
    message: z.string(),
    suggested_action: z.string().nullable(),
    session_phase: z.string().nullable(),
    session_reached_ready: z.boolean(),
    error: ReplayErrorPayloadSchema.nullable(),
    status: GameplayStatusSchema.nullable()
  })
])

export const CloseReplayResultSchema = z.discriminatedUnion('ok', [
  z.object({ ok: z.literal(true), status: GameplayStatusSchema }),
  ErrorResultSchema
])

export const RevealGameplayInputSchema = z.object({
  sourceId: z.string().min(1),
  matchId: z.string().min(1),
  gameTMs: z.number().int(),
  leadInMs: z.number().int().positive().optional()
})

export const RevealGameplayResultSchema = z.discriminatedUnion('ok', [
  z.object({
    ok: z.literal(true),
    source_id: z.string(),
    target_game_ms: z.number().int(),
    lead_in_ms: z.number().int(),
    landed_source_ms: z.number().int().nullable(),
    clock_verified: z.boolean(),
    clock_confidence: z.string().nullable(),
    playback: GameplayPlaybackSchema.nullable(),
    warnings: z.array(ReplayErrorPayloadSchema),
    status: GameplayStatusSchema
  }),
  z.object({
    ok: z.literal(false),
    code: z.string(),
    message: z.string(),
    suggested_action: z.string().nullable(),
    error: ReplayErrorPayloadSchema.nullable(),
    status: GameplayStatusSchema.nullable()
  })
])

export type ReplayErrorPayload = z.infer<typeof ReplayErrorPayloadSchema>
export type GameplayStatus = z.infer<typeof GameplayStatusSchema>
export type DesktopPlatform = z.infer<typeof DesktopPlatformSchema>
export type PickRoflResult = z.infer<typeof PickRoflResultSchema>
export type ImportReplayResult = z.infer<typeof ImportReplayResultSchema>
export type GameplayStatusResult = z.infer<typeof GameplayStatusResultSchema>
export type GameplayEnvironmentResult = z.infer<typeof GameplayEnvironmentResultSchema>
export type OpenReplayResult = z.infer<typeof OpenReplayResultSchema>
export type CloseReplayResult = z.infer<typeof CloseReplayResultSchema>
export type RevealGameplayResult = z.infer<typeof RevealGameplayResultSchema>

export const OverlayContextSchema = z.object({
  reviewId: z.string().min(1),
  matchId: z.string().min(1),
  sourceId: z.string().min(1)
})

export const OverlayPrefsSchema = z.object({
  enabled: z.boolean(),
  compact: z.boolean(),
  opacity: z.number().min(0.4).max(1),
  position: z
    .object({
      x: z.number(),
      y: z.number()
    })
    .nullable(),
  width: z.number().int().min(240).max(640),
  displayId: z.number().int().nullable()
})

export const OverlayOpenInputSchema = OverlayContextSchema.extend({
  sessionPhase: z.string().nullable().optional(),
  sessionReachedReady: z.boolean().optional(),
  liveGame: z.boolean().optional()
})

export const OverlayOpenResultSchema = z.discriminatedUnion('ok', [
  z.object({ ok: z.literal(true) }),
  z.object({ ok: z.literal(false), reason: z.string() })
])

export const OverlaySessionUpdateSchema = z.object({
  sessionPhase: z.string().nullable().optional(),
  sessionReachedReady: z.boolean().optional(),
  liveGame: z.boolean().optional()
})

export const OverlayBoundsSchema = z.object({
  x: z.number(),
  y: z.number(),
  width: z.number().positive(),
  height: z.number().positive()
})

export const OverlayContextResultSchema = z.object({
  context: OverlayContextSchema.nullable(),
  prefs: OverlayPrefsSchema
})

export type OverlayContextPayload = z.infer<typeof OverlayContextSchema>
export type OverlayPrefsPayload = z.infer<typeof OverlayPrefsSchema>
export type OverlayOpenResult = z.infer<typeof OverlayOpenResultSchema>
export type OverlayContextResult = z.infer<typeof OverlayContextResultSchema>
