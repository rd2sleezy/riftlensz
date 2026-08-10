import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import { DEFAULT_REVEAL_LEAD_IN_MS, revealGameplayTimestamp } from './gameplaySeek'

describe('gameplaySeek', () => {
  it('forwards game timestamps to IPC without converting clocks', async () => {
    const reveal = vi.fn().mockResolvedValue({ ok: true })
    ;(globalThis as unknown as { window: { rift: { revealGameplay: typeof reveal } } }).window = {
      rift: { revealGameplay: reveal }
    }
    await revealGameplayTimestamp('src-1', 'NA1_5617764200', 140_000)
    expect(reveal).toHaveBeenCalledWith({
      sourceId: 'src-1',
      matchId: 'NA1_5617764200',
      gameTMs: 140_000,
      leadInMs: DEFAULT_REVEAL_LEAD_IN_MS
    })
    expect(DEFAULT_REVEAL_LEAD_IN_MS).toBe(8_000)
  })

  it('contains no replay clock math in the native seek helper', () => {
    const source = readFileSync(path.join(__dirname, 'gameplaySeek.ts'), 'utf8')
    expect(source).not.toMatch(/offset_ms/)
    expect(source).not.toMatch(/game_to_source/)
    expect(source).not.toMatch(/source_ms\s*[+\-*/]/)
    expect(source).not.toMatch(/seekTarget/)
  })

  it('renderer gameplay views never branch on source_type', () => {
    const files = ['gameplayBar.ts', 'GameplayStatusBar.tsx', 'AddGameplayMenu.tsx', 'ImportReplayWizard.tsx']
    for (const file of files) {
      const source = readFileSync(path.join(__dirname, file), 'utf8')
      expect(source, file).not.toMatch(/source_type/)
      expect(source, file).not.toMatch(/sourceType/)
    }
  })
})
