import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { IPC, IPC_RENDERER_ALLOWLIST } from '../main/ipc/channels'

describe('preload IPC allowlist', () => {
  it('exposes only the declared rift methods', () => {
    const source = readFileSync(path.join(__dirname, 'index.ts'), 'utf8')
    expect(source).toContain("contextBridge.exposeInMainWorld('rift', rift)")
    expect(source).not.toMatch(/rift:replay\//)
    expect(source).not.toMatch(/\/replay\/playback/)
    expect(source).not.toMatch(/shell\.exec/)
    expect(source).not.toMatch(/child_process/)
    for (const name of IPC_RENDERER_ALLOWLIST) {
      if (name === 'onSidecarStatus' || name === 'onOverlayLifecycle' || name === 'onAuthSession') {
        continue
      }
      expect(source).toContain(`${name}(`)
    }
    expect(Object.keys(IPC).length).toBeGreaterThan(10)
  })

  it('does not give the renderer a generic sidecar request', () => {
    const source = readFileSync(path.join(__dirname, 'index.ts'), 'utf8')
    expect(source).not.toMatch(/request\(path/)
    expect(IPC_RENDERER_ALLOWLIST).not.toContain('request')
    expect(IPC_RENDERER_ALLOWLIST).not.toContain('exec')
  })
})
