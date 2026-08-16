import { describe, expect, it } from 'vitest'
import type { GameplayStatus, ReplayErrorPayload } from '../../../main/ipc/channels'
import { deriveGameplayBar, nativeSessionReady } from './gameplayBar'
import { knownReplayErrorCodes, replayErrorView } from './replayErrors'

function error(code: string, message = 'typed'): ReplayErrorPayload {
  return {
    code,
    message,
    suggested_action: null,
    recoverable: true,
    severity: 'fatal'
  }
}

function status(partial: Partial<GameplayStatus>): GameplayStatus {
  return {
    native_replay_supported: true,
    match_id: 'NA1_5617764200',
    sources: [],
    active_source_id: 'src-1',
    capabilities: ['READ_TIME', 'SEEK', 'LIVE_CLIENT_DATA'],
    source_status: 'linked',
    file_present: true,
    display_name: 'NA1-5617764200.rofl',
    declared_patch: '16.15',
    session_phase: 'IDLE',
    session_reached_ready: false,
    session_owns_process: false,
    clock_confidence: null,
    clock_verified: null,
    clock_method: null,
    offset_ms: null,
    residual_ms: null,
    anchor_count: null,
    error: null,
    warnings: [],
    ...partial
  }
}

describe('deriveGameplayBar', () => {
  it('shows none when no gameplay is attached', () => {
    const view = deriveGameplayBar({
      status: status({ active_source_id: null, capabilities: [] }),
      nativeReplaySupported: true,
      hasInlineVideo: false,
      videoSynced: false,
      opening: false,
      seeking: false
    })
    expect(view.kind).toBe('none')
    expect(view.label).toMatch(/no gameplay attached/i)
  })

  it('shows video manual sync without using source_type', () => {
    const view = deriveGameplayBar({
      status: status({ active_source_id: null, capabilities: [] }),
      nativeReplaySupported: true,
      hasInlineVideo: true,
      videoSynced: true,
      opening: false,
      seeking: false
    })
    expect(view.kind).toBe('video_manual')
    expect(view.syncLabel).toBe('Manual sync')
  })

  it('shows video auto-sync quality without using source_type', () => {
    const view = deriveGameplayBar({
      status: status({ active_source_id: null, capabilities: [] }),
      nativeReplaySupported: true,
      hasInlineVideo: true,
      videoSynced: true,
      videoSyncMethod: 'clock_ocr',
      videoSyncVerdict: 'GOOD',
      opening: false,
      seeking: false
    })
    expect(view.kind).toBe('video_manual')
    expect(view.syncLabel).toMatch(/auto-sync/i)
    expect(view.label).toMatch(/GOOD/)
  })

  it('shows linked replay ready to open', () => {
    const view = deriveGameplayBar({
      status: status({ session_phase: 'IDLE' }),
      nativeReplaySupported: true,
      hasInlineVideo: false,
      videoSynced: false,
      opening: false,
      seeking: false
    })
    expect(view.kind).toBe('replay_linked')
    expect(view.showOpen).toBe(true)
    expect(view.label).toMatch(/replay linked/i)
  })

  it('explains unavailable native replay on non-Windows', () => {
    const view = deriveGameplayBar({
      status: status({
        native_replay_supported: false,
        capabilities: [],
        error: error('PLATFORM_UNSUPPORTED', 'This gameplay source is not supported on this platform.')
      }),
      nativeReplaySupported: false,
      hasInlineVideo: false,
      videoSynced: false,
      opening: false,
      seeking: false
    })
    expect(view.kind).toBe('replay_unavailable_platform')
    expect(view.actionId).toBe('attach_video')
  })

  it('shows launching before READY', () => {
    const view = deriveGameplayBar({
      status: status({ session_phase: 'LAUNCHING' }),
      nativeReplaySupported: true,
      hasInlineVideo: false,
      videoSynced: false,
      opening: true,
      seeking: false
    })
    expect(view.kind).toBe('launching')
    expect(view.label).toMatch(/opening replay/i)
  })

  it('does not claim ready until backend reached_ready', () => {
    const connecting = deriveGameplayBar({
      status: status({ session_phase: 'CONNECTING', session_reached_ready: false }),
      nativeReplaySupported: true,
      hasInlineVideo: false,
      videoSynced: false,
      opening: false,
      seeking: false
    })
    expect(connecting.kind).toBe('connecting')
    expect(nativeSessionReady(status({ session_phase: 'CONNECTING', session_reached_ready: false }))).toBe(
      false
    )
    const ready = deriveGameplayBar({
      status: status({
        session_phase: 'READY',
        session_reached_ready: true,
        clock_verified: true,
        clock_confidence: 'GOOD',
        residual_ms: 80
      }),
      nativeReplaySupported: true,
      hasInlineVideo: false,
      videoSynced: false,
      opening: false,
      seeking: false
    })
    expect(ready.kind).toBe('ready_verified')
    expect(ready.syncLabel).toBe('Verified replay sync')
  })

  it('does not present degraded sync as verified', () => {
    const view = deriveGameplayBar({
      status: status({
        session_phase: 'READY',
        session_reached_ready: true,
        clock_verified: false,
        clock_confidence: 'DEGRADED'
      }),
      nativeReplaySupported: true,
      hasInlineVideo: false,
      videoSynced: false,
      opening: false,
      seeking: false
    })
    expect(view.kind).toBe('ready_degraded')
    expect(view.syncLabel).not.toMatch(/verified/i)
    expect(view.syncLabel).toMatch(/estimated|manual|auto-synced/i)
  })

  it('shows session lost and seek failure typed states', () => {
    const lost = deriveGameplayBar({
      status: status({
        session_phase: 'FAILED',
        error: error('SESSION_LOST', 'Replay window was closed. Reopen the replay to continue.')
      }),
      nativeReplaySupported: true,
      hasInlineVideo: false,
      videoSynced: false,
      opening: false,
      seeking: false
    })
    expect(lost.kind).toBe('session_lost')
    expect(lost.showRetry).toBe(true)
    const seekFail = deriveGameplayBar({
      status: status({
        session_phase: 'READY',
        session_reached_ready: false,
        error: error('SEEK_FAILED', 'Replay seek did not change playback time.')
      }),
      nativeReplaySupported: true,
      hasInlineVideo: false,
      videoSynced: false,
      opening: false,
      seeking: false
    })
    expect(seekFail.kind).toBe('replay_error')
    expect(seekFail.errorCode).toBe('SEEK_FAILED')
  })

  it('maps league missing and replay api errors', () => {
    expect(
      deriveGameplayBar({
        status: status({ error: error('INSTALL_NOT_FOUND', 'League of Legends installation was not found.') }),
        nativeReplaySupported: true,
        hasInlineVideo: false,
        videoSynced: false,
        opening: false,
        seeking: false
      }).kind
    ).toBe('league_not_found')
    expect(
      deriveGameplayBar({
        status: status({
          error: error('REPLAY_API_UNAVAILABLE', 'Local Replay API is not reachable.')
        }),
        nativeReplaySupported: true,
        hasInlineVideo: false,
        videoSynced: false,
        opening: false,
        seeking: false
      }).kind
    ).toBe('replay_api_unavailable')
    expect(
      deriveGameplayBar({
        status: status({
          error: error('REPLAY_API_DISABLED', 'Replay API is not enabled in the game client.')
        }),
        nativeReplaySupported: true,
        hasInlineVideo: false,
        videoSynced: false,
        opening: false,
        seeking: false
      }).kind
    ).toBe('replay_api_disabled')
  })
})

describe('replay error UX', () => {
  it('gives every required code a specific message and action', () => {
    const required = [
      'PLATFORM_UNSUPPORTED',
      'ROFL_UNREADABLE',
      'ROFL_NOT_RECOGNISED',
      'MATCH_ID_UNRESOLVED',
      'MATCH_NOT_INGESTED',
      'MATCH_IDENTITY_MISMATCH',
      'RIOT_CREDENTIAL_MISSING',
      'INSTALL_NOT_FOUND',
      'REPLAY_API_DISABLED',
      'REPLAY_API_UNAVAILABLE',
      'LIVE_GAME_IN_PROGRESS',
      'PATCH_INCOMPATIBLE',
      'LAUNCH_FAILED',
      'SESSION_LOST',
      'CLOCK_CALIBRATION_FAILED',
      'SEEK_FAILED',
      'SOURCE_NOT_READY'
    ]
    for (const code of required) {
      const view = replayErrorView({ code })
      expect(view.message.toLowerCase()).not.toContain('something went wrong')
      expect(view.actionLabel.length).toBeGreaterThan(0)
      expect(knownReplayErrorCodes()).toContain(code)
    }
  })
})
