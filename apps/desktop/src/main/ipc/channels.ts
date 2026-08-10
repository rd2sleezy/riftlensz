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
  getAuthSession: 'rift:auth:get-session',
  authSessionEvent: 'rift:auth:session',
  signIn: 'rift:auth:sign-in',
  signInWithApiKey: 'rift:auth:sign-in-api-key',
  signOut: 'rift:auth:sign-out'
} as const

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
    'AUTH_NOT_CONFIGURED',
    'AUTH_CANCELLED',
    'AUTH_FAILED',
    'UNKNOWN'
  ]),
  message: z.string()
})

/** Public-safe account session. Never carries tokens across the IPC boundary. */
export const AuthSessionSchema = z.object({
  signedIn: z.boolean(),
  puuid: z.string().nullable(),
  gameName: z.string().nullable(),
  tagLine: z.string().nullable(),
  signedInAt: z.number().int().nullable()
})

export const SignInResultSchema = z.discriminatedUnion('ok', [
  z.object({ ok: z.literal(true), session: AuthSessionSchema }),
  ErrorResultSchema
])

export const SignInWithApiKeyInputSchema = z.object({
  apiKey: z.string().min(1),
  gameName: z.string().min(1),
  tagLine: z.string().min(1),
  region: z.enum(['americas', 'asia', 'europe'])
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
export type AuthSession = z.infer<typeof AuthSessionSchema>
export type SignInResult = z.infer<typeof SignInResultSchema>
export type SignInWithApiKeyInput = z.infer<typeof SignInWithApiKeyInputSchema>
