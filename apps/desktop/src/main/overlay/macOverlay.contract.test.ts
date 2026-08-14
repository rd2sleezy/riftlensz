import { describe, expect, it } from 'vitest'
import { resolveOverlayHotkey } from './hotkeys'
import {
  applyOverlayWindowChrome,
  overlayCompanionSupported,
  overlayWindowOptionsForPlatform
} from './platform'
import { clampToWorkArea, isHudSafe, resolveOverlayRect } from './placement'
import { DEFAULT_OVERLAY_PREFS, type Rect } from './types'
import { isReplaySessionActive, shouldShowOverlay } from './leagueWindow.shared'
import { displayModeSwitchPolicy } from './displayModeAssist'
import { readFileSync } from 'node:fs'
import path from 'node:path'

describe('macOS overlay platform capability', () => {
  it('enables the companion overlay on win32 and darwin only', () => {
    expect(overlayCompanionSupported('win32')).toBe(true)
    expect(overlayCompanionSupported('darwin')).toBe(true)
    expect(overlayCompanionSupported('linux')).toBe(false)
  })

  it('uses a Mac panel always-on-top configuration above League', () => {
    const mac = overlayWindowOptionsForPlatform('darwin')
    expect(mac.frame).toBe(false)
    expect(mac.alwaysOnTop).toBe(true)
    expect(mac.type).toBe('panel')
    // floating is below Dock/game windows — screen-saver is required for League.
    expect(mac.alwaysOnTopLevel).toBe('screen-saver')
    expect(mac.alwaysOnTopRelativeLevel).toBe(1)
    expect(mac.visibleOnAllWorkspaces).toBe(true)
    expect(mac.visibleOnFullScreen).toBe(true)
    expect(mac.fullscreenable).toBe(false)
    // Non-focusable by default so Access Overlay does not key the RiftLens main window.
    expect(mac.focusable).toBe(false)
  })

  it('preserves Windows screen-saver always-on-top level', () => {
    const win = overlayWindowOptionsForPlatform('win32')
    expect(win.type).toBeUndefined()
    expect(win.alwaysOnTopLevel).toBe('screen-saver')
    expect(win.focusable).toBe(true)
  })

  it('applies chrome without parenting and skips moveTop on darwin', () => {
    const calls: string[] = []
    const win = {
      setFullScreenable: (v: boolean) => calls.push(`fullscreenable:${v}`),
      setVisibleOnAllWorkspaces: (v: boolean, opts?: { visibleOnFullScreen?: boolean }) =>
        calls.push(`workspaces:${v}:${opts?.visibleOnFullScreen === true}`),
      setAlwaysOnTop: (flag: boolean, level?: string, relative?: number) =>
        calls.push(`aot:${flag}:${level}:${relative ?? 0}`),
      setFocusable: (v: boolean) => calls.push(`focusable:${v}`),
      moveTop: () => calls.push('moveTop'),
      setIgnoreMouseEvents: (ignore: boolean) => calls.push(`ignore:${ignore}`)
    }
    applyOverlayWindowChrome(win, 'darwin')
    expect(calls).toContain('fullscreenable:false')
    expect(calls).toContain('workspaces:true:true')
    expect(calls).toContain('aot:true:screen-saver:1')
    expect(calls).not.toContain('moveTop')
    expect(calls).not.toContain('focusable:false')
    expect(calls).toContain('ignore:false')

    const win32Calls: string[] = []
    applyOverlayWindowChrome(
      {
        setFullScreenable: () => undefined,
        setVisibleOnAllWorkspaces: () => undefined,
        setAlwaysOnTop: () => undefined,
        moveTop: () => win32Calls.push('moveTop'),
        setIgnoreMouseEvents: () => undefined
      },
      'win32'
    )
    expect(win32Calls).toContain('moveTop')
  })

  it('restores focusable only when explicitly requested', () => {
    const calls: string[] = []
    applyOverlayWindowChrome(
      {
        setFullScreenable: () => undefined,
        setVisibleOnAllWorkspaces: () => undefined,
        setAlwaysOnTop: () => undefined,
        setFocusable: (v: boolean) => calls.push(`focusable:${v}`),
        setIgnoreMouseEvents: () => undefined
      },
      'darwin',
      { resetFocusable: true }
    )
    expect(calls).toEqual(['focusable:false'])
  })
})

describe('overlay local hotkeys', () => {
  it('maps prev/next/seek/minimize/expand without Escape or Space', () => {
    expect(
      resolveOverlayHotkey({
        key: '[',
        code: 'BracketLeft',
        altKey: true,
        metaKey: false,
        ctrlKey: false,
        shiftKey: false,
        repeat: false
      })
    ).toBe('prev_item')
    expect(
      resolveOverlayHotkey({
        key: ']',
        code: 'BracketRight',
        altKey: true,
        metaKey: false,
        ctrlKey: false,
        shiftKey: false,
        repeat: false
      })
    ).toBe('next_item')
    expect(
      resolveOverlayHotkey({
        key: 'Enter',
        code: 'Enter',
        altKey: true,
        metaKey: false,
        ctrlKey: false,
        shiftKey: false,
        repeat: false
      })
    ).toBe('seek_selected')
    expect(
      resolveOverlayHotkey({
        key: 'h',
        code: 'KeyH',
        altKey: true,
        metaKey: false,
        ctrlKey: false,
        shiftKey: false,
        repeat: false
      })
    ).toBe('minimize')
    expect(
      resolveOverlayHotkey({
        key: 'o',
        code: 'KeyO',
        altKey: true,
        metaKey: false,
        ctrlKey: false,
        shiftKey: false,
        repeat: false
      })
    ).toBe('expand')
    expect(
      resolveOverlayHotkey({
        key: 'Escape',
        code: 'Escape',
        altKey: false,
        metaKey: false,
        ctrlKey: false,
        shiftKey: false,
        repeat: false
      })
    ).toBeNull()
    expect(
      resolveOverlayHotkey({
        key: ' ',
        code: 'Space',
        altKey: false,
        metaKey: false,
        ctrlKey: false,
        shiftKey: false,
        repeat: false
      })
    ).toBeNull()
  })

  it('never registers Electron global shortcuts in overlay modules', () => {
    const roots = [
      'controller.ts',
      'createOverlayWindow.ts',
      'leagueWindow.ts',
      'leagueWindow.darwin.ts',
      'hotkeys.ts',
      'platform.ts',
      'visibilityState.ts',
      '../../renderer/features/overlay/OverlayApp.tsx'
    ]
    for (const file of roots) {
      const source = readFileSync(path.join(__dirname, file), 'utf8')
      expect(source).not.toMatch(/globalShortcut\.(register|registerAll|unregister)/)
    }
  })
})

describe('overlay bounds clamping and HUD safety', () => {
  it('clamps dragged overlays so they remain at least partially visible', () => {
    const work: Rect = { x: 0, y: 0, width: 1920, height: 1080 }
    const clamped = clampToWorkArea({ x: -400, y: 2000, width: 300, height: 200 }, work)
    // Policy: at least 48px remains inside the work area (matches placement.ts).
    expect(clamped.x + clamped.width).toBeGreaterThan(work.x)
    expect(clamped.y).toBeLessThan(work.y + work.height)
    expect(clamped.x).toBeLessThan(work.x + work.width)
  })

  it('keeps the default Mac primary-display placement HUD-safe at 1440p', () => {
    const league: Rect = { x: 0, y: 0, width: 2560, height: 1440 }
    const work = league
    const placed = resolveOverlayRect({
      league,
      workArea: work,
      prefs: DEFAULT_OVERLAY_PREFS,
      height: 440
    })
    expect(isHudSafe(league, placed)).toBe(true)
    expect(placed.y).toBeLessThan(league.y + league.height * 0.62)
  })
})

describe('replay-only overlay safety', () => {
  it('refuses live games and inactive sessions', () => {
    expect(
      shouldShowOverlay({
        prefsEnabled: true,
        liveGame: true,
        hasContext: true,
        sessionActive: true,
        league: {
          bounds: { x: 0, y: 0, width: 1920, height: 1080 },
          minimized: false,
          title: 'League of Legends',
          displayMode: 'borderless'
        },
        missingPolls: 0
      }).reason
    ).toBe('live_game')
    expect(isReplaySessionActive('PLAYING', true)).toBe(true)
    expect(isReplaySessionActive('READY', false)).toBe(false)
    expect(isReplaySessionActive('IDLE', true)).toBe(false)
  })
})

describe('macOS display-mode assist copy', () => {
  it('documents Spaces/fullscreen limitation without auto-switching', () => {
    const policy = displayModeSwitchPolicy('darwin')
    expect(policy.automaticSwitchAvailable).toBe(false)
    expect(policy.steps.some((step) => /Space/i.test(step))).toBe(true)
  })
})

describe('overlay teardown contract', () => {
  it('closes the overlay when the main window closes and on before-quit', () => {
    const main = readFileSync(path.join(__dirname, '../index.ts'), 'utf8')
    expect(main).toContain('overlay.close()')
    expect(main).toContain("mainWindow.on('closed'")
    expect(main).toContain("app.on('before-quit'")
  })
})
