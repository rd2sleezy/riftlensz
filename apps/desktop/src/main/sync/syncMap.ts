export const SEEK_LEAD_IN_MS = 8_000
const SLOPE_TOLERANCE = 0.02

export type SyncVerdict = 'EXCELLENT' | 'GOOD' | 'DEGRADED' | 'FAILED'

export type SyncSegment = {
  video_start_ms: number
  video_end_ms: number
  offset_ms: number
  n_anchors: number
  residual_p95_ms: number
}

export type PauseInterval = {
  video_start_ms: number
  video_end_ms: number
  t_game_ms: number
}

export type SyncQuality = {
  method: string
  n_readings: number
  n_inliers: number
  inlier_ratio: number
  residual_p50_ms: number
  residual_p95_ms: number
  coverage: number
  n_segments: number
  verdict: SyncVerdict
}

export type SyncMapData = {
  segments: SyncSegment[]
  pauses: PauseInterval[]
  quality: SyncQuality
  media_asset_id: string
  match_id: string
  version: number
  verified: boolean
}

export type SyncAnchor = {
  t_video_ms: number
  t_game_ms: number
}

export type SeekTarget = {
  t_game_ms: number
  t_video_ms: number | null
  seek_video_ms: number | null
  covered: boolean
  uncertain: boolean
  reason: string | null
}

export class SyncAnchorInconsistent extends Error {
  public override readonly name = 'SyncAnchorInconsistent'
}

/** Return game ms for a video timestamp, or null when uncovered. */
export function videoToGame(sync: SyncMapData, tVideoMs: number): number | null {
  const segment = segmentForVideo(sync, tVideoMs)
  return segment === null ? null : tVideoMs + segment.offset_ms
}

/** Return video ms for a game timestamp, or null when uncovered. */
export function gameToVideo(sync: SyncMapData, tGameMs: number): number | null {
  const segment = segmentForGame(sync, tGameMs)
  return segment === null ? null : tGameMs - segment.offset_ms
}

/** Return True when game time is covered by a segment. */
export function coversGame(sync: SyncMapData, tGameMs: number): boolean {
  return segmentForGame(sync, tGameMs) !== null
}

/** Build a slope-1.0 SyncMap from integer-ms anchors. Does not invent offsets. */
export function buildManualSync(
  anchors: SyncAnchor[],
  options: {
    videoDurationMs: number
    matchId: string
    mediaAssetId?: string
    matchDurationMs?: number | null
  }
): SyncMapData {
  if (options.videoDurationMs <= 0) {
    throw new Error('video_duration_ms must be positive')
  }
  if (anchors.length === 0) {
    throw new Error('at least one sync anchor is required')
  }
  const cleaned = [...anchors]
    .map((item) => ({ t_video_ms: item.t_video_ms, t_game_ms: item.t_game_ms }))
    .sort((a, b) => a.t_video_ms - b.t_video_ms)
  if (cleaned.length >= 2) {
    assertSlopeNearOne(cleaned)
  }
  const { offset, residualP50, residualP95 } = fitFixedSlope(cleaned)
  const coverage = manualCoverage(
    offset,
    options.videoDurationMs,
    options.matchDurationMs ?? null
  )
  const n = cleaned.length
  const verdict = manualVerdict(n, residualP95, coverage)
  return {
    segments: [
      {
        video_start_ms: 0,
        video_end_ms: options.videoDurationMs,
        offset_ms: offset,
        n_anchors: n,
        residual_p95_ms: residualP95
      }
    ],
    pauses: [],
    quality: {
      method: 'manual',
      n_readings: n,
      n_inliers: n,
      inlier_ratio: 1.0,
      residual_p50_ms: residualP50,
      residual_p95_ms: residualP95,
      coverage,
      n_segments: 1,
      verdict
    },
    media_asset_id: options.mediaAssetId ?? '',
    match_id: options.matchId,
    version: 1,
    verified: false
  }
}

/** Map finding t_ms → VOD time. Uncovered times stay null. */
export function seekTarget(
  sync: SyncMapData | null,
  tGameMs: number,
  leadInMs = SEEK_LEAD_IN_MS
): SeekTarget {
  if (sync === null) {
    return {
      t_game_ms: tGameMs,
      t_video_ms: null,
      seek_video_ms: null,
      covered: false,
      uncertain: true,
      reason: 'No sync map — VOD time is unknown until you set a clock anchor.'
    }
  }
  const tVideo = gameToVideo(sync, tGameMs)
  if (tVideo === null) {
    return {
      t_game_ms: tGameMs,
      t_video_ms: null,
      seek_video_ms: null,
      covered: false,
      uncertain: true,
      reason: 'Recording does not cover this game time.'
    }
  }
  const uncertain = sync.quality.verdict === 'DEGRADED' || sync.quality.verdict === 'FAILED' || !sync.verified
  return {
    t_game_ms: tGameMs,
    t_video_ms: tVideo,
    seek_video_ms: Math.max(0, tVideo - Math.max(0, leadInMs)),
    covered: true,
    uncertain,
    reason: uncertain ? uncertaintyReason(sync) : null
  }
}

export function formatMmss(tMs: number): string {
  const totalS = Math.max(0, Math.trunc(tMs / 1000))
  const minutes = Math.floor(totalS / 60)
  const seconds = totalS % 60
  return `${minutes}:${seconds.toString().padStart(2, '0')}`
}

function segmentForVideo(sync: SyncMapData, tVideoMs: number): SyncSegment | null {
  return sync.segments.find((item) => item.video_start_ms <= tVideoMs && tVideoMs < item.video_end_ms) ?? null
}

function segmentForGame(sync: SyncMapData, tGameMs: number): SyncSegment | null {
  return (
    sync.segments.find((item) => {
      const start = item.video_start_ms + item.offset_ms
      const end = item.video_end_ms + item.offset_ms
      return start <= tGameMs && tGameMs < end
    }) ?? null
  )
}

function assertSlopeNearOne(anchors: SyncAnchor[]): void {
  const first = anchors[0]
  const last = anchors[anchors.length - 1]
  if (first === undefined || last === undefined) {
    return
  }
  const deltaVideo = last.t_video_ms - first.t_video_ms
  if (deltaVideo === 0) {
    throw new SyncAnchorInconsistent('anchors share the same video time; cannot check slope')
  }
  const slope = (last.t_game_ms - first.t_game_ms) / deltaVideo
  if (Math.abs(slope - 1.0) > SLOPE_TOLERANCE) {
    throw new SyncAnchorInconsistent(
      `anchors imply slope ${slope.toFixed(4)}, outside 1.0 ± ${SLOPE_TOLERANCE}`
    )
  }
}

function fitFixedSlope(anchors: SyncAnchor[]): {
  offset: number
  residualP50: number
  residualP95: number
} {
  const offsets = anchors.map((item) => item.t_game_ms - item.t_video_ms)
  const offset = Math.round(offsets.reduce((sum, value) => sum + value, 0) / offsets.length)
  const residuals = offsets
    .map((value) => Math.abs(value - offset))
    .sort((a, b) => a - b)
  return {
    offset,
    residualP50: percentile(residuals, 50),
    residualP95: percentile(residuals, 95)
  }
}

function percentile(sortedValues: number[], pct: number): number {
  if (sortedValues.length === 0) {
    return 0
  }
  if (sortedValues.length === 1) {
    return sortedValues[0] ?? 0
  }
  const rank = (pct / 100) * (sortedValues.length - 1)
  const lower = Math.floor(rank)
  const upper = Math.min(lower + 1, sortedValues.length - 1)
  const frac = rank - lower
  const lo = sortedValues[lower] ?? 0
  const hi = sortedValues[upper] ?? 0
  return lo * (1 - frac) + hi * frac
}

function manualCoverage(
  offsetMs: number,
  videoDurationMs: number,
  matchDurationMs: number | null
): number {
  if (matchDurationMs === null || matchDurationMs <= 0) {
    return 1
  }
  const gameStart = offsetMs
  const gameEnd = offsetMs + videoDurationMs
  const overlap = Math.max(0, Math.min(gameEnd, matchDurationMs) - Math.max(gameStart, 0))
  return Math.max(0, Math.min(1, overlap / matchDurationMs))
}

function manualVerdict(nAnchors: number, residualP95Ms: number, coverage: number): SyncVerdict {
  if (nAnchors < 1) {
    return 'FAILED'
  }
  if (nAnchors === 1) {
    return 'DEGRADED'
  }
  if (residualP95Ms < 300 && coverage > 0.9) {
    return 'GOOD'
  }
  if (residualP95Ms < 700) {
    return 'DEGRADED'
  }
  return 'FAILED'
}

function uncertaintyReason(sync: SyncMapData): string {
  if (sync.quality.verdict === 'FAILED') {
    return 'Sync failed quality checks — do not treat VOD times as exact.'
  }
  if (sync.quality.n_readings < 2) {
    return 'Single-anchor sync is approximate. A second clock reading would confirm it.'
  }
  if (!sync.verified) {
    return 'Sync is not independently verified against in-game events.'
  }
  return 'Sync confidence is limited.'
}
