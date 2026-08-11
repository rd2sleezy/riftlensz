import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('overlay input safety policy', () => {
  it('never registers Electron globalShortcut in overlay modules', () => {
    const roots = [
      path.join(__dirname, 'controller.ts'),
      path.join(__dirname, 'createOverlayWindow.ts'),
      path.join(__dirname, 'leagueWindow.ts'),
      path.join(__dirname, '../index.ts')
    ]
    for (const file of roots) {
      const source = readFileSync(file, 'utf8')
      expect(source).not.toMatch(/globalShortcut/)
      expect(source).not.toMatch(/register\(['"]Escape|Space|F[0-9]/)
    }
  })

  it('does not inject into League or expose Replay API from overlay code', () => {
    const controller = readFileSync(path.join(__dirname, 'controller.ts'), 'utf8')
    expect(controller).not.toMatch(/WriteProcessMemory|SetWindowsHook|dll inject/i)
    expect(controller).not.toMatch(/\/replay\/playback/)
  })
})
