import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('macOS League focus restore', () => {
  it('uses NSRunningApplication activation without keystroke injection', () => {
    const source = readFileSync(path.join(__dirname, 'leagueFocus.darwin.ts'), 'utf8')
    expect(source).toContain('activateWithOptions')
    expect(source).toContain('NSWorkspace')
    expect(source).toContain("['-l', 'JavaScript'")
    expect(source).not.toMatch(/key code|keystroke of|CGEventCreate|hidutil/i)
    expect(source).toMatch(/riotclient/i)
  })

  it('wires expand/minimize/open to restore League focus and showInactive', () => {
    const controller = readFileSync(path.join(__dirname, 'controller.ts'), 'utf8')
    expect(controller).toContain('restoreLeagueReplayFocusDarwin')
    expect(controller).toContain("scheduleReplayFocusRestore('expand')")
    expect(controller).toContain("scheduleReplayFocusRestore('minimize')")
    expect(controller).toContain("scheduleReplayFocusRestore('open')")
    expect(controller).toContain('showInactive()')
    expect(controller).toContain('allowInteractionFocus')
    expect(controller).not.toMatch(/mainWindow\.focus\(/)
    expect(controller).not.toMatch(/app\.focus\(/)
  })

  it('keeps Access Overlay launcher non-activating (no interaction-focus on launcher)', () => {
    const overlayApp = readFileSync(
      path.join(__dirname, '../../renderer/features/overlay/OverlayApp.tsx'),
      'utf8'
    )
    expect(overlayApp).toContain('overlayAllowInteractionFocus')
    expect(overlayApp).toContain("presentation !== 'OVERLAY_OPEN'")
    expect(overlayApp).toContain("data-testid=\"overlay-access\"")
    // Launcher Access Overlay must not request interaction focus before expand.
    const launcherBlock = overlayApp.slice(
      overlayApp.indexOf("presentation === 'LAUNCHER'"),
      overlayApp.indexOf('if (needsCompat)')
    )
    expect(launcherBlock).not.toContain('requestInteractionFocus')
  })
})
