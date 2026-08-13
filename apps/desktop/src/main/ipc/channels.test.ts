import { describe, expect, it } from 'vitest'
import {
  GameplayStatusSchema,
  HealthSchema,
  IPC,
  IPC_RENDERER_ALLOWLIST,
  ImportReplayResultSchema,
  ListReviewsResultSchema,
  OpenReplayResultSchema,
  RevealGameplayResultSchema,
  SidecarStatusSchema
} from './channels'

const status = {
  native_replay_supported: true,
  match_id: 'NA1_5617764200',
  sources: [
    {
      id: 'src-1',
      display_name: 'NA1-5617764200.rofl',
      capabilities: ['SEEK', 'LIVE_CLIENT_DATA'],
      status: 'linked',
      file_present: true,
      declared_patch: '16.15',
      duration_ms: 1_800_000,
      available: true,
      unavailable_error: null
    }
  ],
  active_source_id: 'src-1',
  capabilities: ['SEEK', 'LIVE_CLIENT_DATA'],
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
  warnings: []
}

describe('IPC zod schemas', () => {
  it('parses a ready sidecar status', () => {
    const parsed = SidecarStatusSchema.parse({
      state: 'ready',
      version: '0.1.0',
      port: 54321,
      pid: 99
    })
    expect(parsed.port).toBe(54321)
  })

  it('parses a health payload', () => {
    const parsed = HealthSchema.parse({
      status: 'ok',
      version: '0.1.0',
      python: '3.12.11',
      db_path: '/tmp/riftlens.db',
      uptime_ms: 12
    })
    expect(parsed.uptime_ms).toBe(12)
  })

  it('parses a review list error without bypassing the schema', () => {
    const parsed = ListReviewsResultSchema.parse({
      ok: false,
      code: 'NOT_FOUND',
      message: 'Review not found: missing'
    })
    expect(parsed.ok).toBe(false)
  })

  it('parses import success and typed failure', () => {
    const ok = ImportReplayResultSchema.parse({
      ok: true,
      source_id: 'src-1',
      match_id: 'NA1_5617764200',
      identity: {
        platform_id: 'NA1',
        game_id: 5617764200,
        declared_patch: '16.15',
        declared_length_ms: 1_800_000,
        match_id_hint: 'NA1_5617764200',
        identify_method: 'filename'
      },
      warnings: [],
      status
    })
    expect(ok.ok).toBe(true)
    const failed = ImportReplayResultSchema.parse({
      ok: false,
      code: 'ROFL_NOT_RECOGNISED',
      message: "This file doesn't look like a League replay.",
      suggested_action: 'choose_file',
      match_id: null,
      identity: null,
      error: {
        code: 'ROFL_NOT_RECOGNISED',
        message: "This file doesn't look like a League replay.",
        suggested_action: 'choose_file',
        recoverable: false,
        severity: 'fatal'
      }
    })
    expect(failed.ok).toBe(false)
  })

  it('rejects READY unless session_reached_ready is true', () => {
    expect(() =>
      OpenReplayResultSchema.parse({
        ok: true,
        session_phase: 'CONNECTING',
        session_reached_ready: false,
        status
      })
    ).toThrow()
    const ready = OpenReplayResultSchema.parse({
      ok: true,
      session_phase: 'READY',
      session_reached_ready: true,
      status: { ...status, session_phase: 'READY', session_reached_ready: true }
    })
    expect(ready.ok).toBe(true)
  })

  it('parses reveal IPC without exposing arbitrary replay endpoints', () => {
    const parsed = RevealGameplayResultSchema.parse({
      ok: true,
      source_id: 'src-1',
      target_game_ms: 132_000,
      lead_in_ms: 8_000,
      landed_source_ms: 132_670,
      clock_verified: true,
      clock_confidence: 'GOOD',
      playback: {
        t_source_ms: 132_670,
        length_ms: 1_800_000,
        paused: false,
        seeking: false,
        speed_milli: 1000,
        t_game_ms: 132_000
      },
      warnings: [],
      status: { ...status, session_phase: 'PLAYING', session_reached_ready: true }
    })
    expect(parsed.ok).toBe(true)
    expect(Object.values(IPC)).not.toContain('rift:replay:playback')
    expect(IPC_RENDERER_ALLOWLIST).not.toContain('request')
    expect(IPC.revealGameplay).toBe('rift:gameplay:reveal')
  })

  it('parses gameplay status without source_type', () => {
    const parsed = GameplayStatusSchema.parse(status)
    expect('source_type' in parsed).toBe(false)
  })
})
