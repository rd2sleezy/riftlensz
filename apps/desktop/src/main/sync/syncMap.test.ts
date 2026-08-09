import { describe, expect, it } from 'vitest'
import {
  SEEK_LEAD_IN_MS,
  SyncAnchorInconsistent,
  buildManualSync,
  gameToVideo,
  seekTarget,
  videoToGame
} from './syncMap'

describe('manual sync map', () => {
  it('maps one anchor both directions', () => {
    const sync = buildManualSync([{ t_video_ms: 12_000, t_game_ms: 90_000 }], {
      videoDurationMs: 600_000,
      matchId: 'NA1_x',
      mediaAssetId: 'media1',
      matchDurationMs: 1_800_000
    })
    expect(sync.quality.verdict).toBe('DEGRADED')
    expect(gameToVideo(sync, 90_000)).toBe(12_000)
    expect(videoToGame(sync, 12_000)).toBe(90_000)
    expect(gameToVideo(sync, 5_000)).toBeNull()
  })

  it('rejects a slope far from 1.0', () => {
    expect(() =>
      buildManualSync(
        [
          { t_video_ms: 0, t_game_ms: 0 },
          { t_video_ms: 60_000, t_game_ms: 120_000 }
        ],
        { videoDurationMs: 180_000, matchId: 'NA1_x' }
      )
    ).toThrow(SyncAnchorInconsistent)
  })

  it('does not invent timestamps without a sync map', () => {
    const target = seekTarget(null, 140_000)
    expect(target.t_video_ms).toBeNull()
    expect(target.seek_video_ms).toBeNull()
    expect(target.covered).toBe(false)
    expect(target.uncertain).toBe(true)
  })

  it('applies lead-in and marks single-anchor seeks uncertain', () => {
    const sync = buildManualSync([{ t_video_ms: 20_000, t_game_ms: 80_000 }], {
      videoDurationMs: 300_000,
      matchId: 'm'
    })
    const target = seekTarget(sync, 80_000)
    expect(target.covered).toBe(true)
    expect(target.t_video_ms).toBe(20_000)
    expect(target.seek_video_ms).toBe(20_000 - SEEK_LEAD_IN_MS)
    expect(target.uncertain).toBe(true)
  })
})
