import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('overlay interaction performance contracts', () => {
  it('selects and seeks without awaiting League window detection', () => {
    const source = readFileSync(path.join(__dirname, '../../renderer/features/overlay/OverlayApp.tsx'), 'utf8')
    expect(source).toContain('setSelectedItemId(item.id)')
    expect(source).toContain('revealGameplayTimestamp')
    expect(source).not.toMatch(/await\s+.*findLeague|execFileSync|powershell/i)
    // Row click activates seek directly — no separate Jump gate.
    expect(source).toContain('onActivate={onRowActivate}')
    expect(source).not.toMatch(/data-testid="overlay-jump"/)
  })

  it('keeps PowerShell enumeration off the synchronous FindWindow hot path', () => {
    const source = readFileSync(path.join(__dirname, 'leagueWindow.ts'), 'utf8')
    expect(source).toContain('findViaFindWindow')
    expect(source).toContain('schedulePowerShellFallback')
    expect(source).not.toMatch(/execFileSync/)
    expect(source).toMatch(/execFileAsync|promisify\(execFile\)/)
  })
})
