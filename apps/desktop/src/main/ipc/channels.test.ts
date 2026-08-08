import { describe, expect, it } from 'vitest'
import { HealthSchema, SidecarStatusSchema } from './channels'

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
})
