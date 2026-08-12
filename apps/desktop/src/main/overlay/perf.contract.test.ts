import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('overlay interaction performance contracts', () => {
  it('selects and seeks without awaiting League window detection', () => {
    const source = readFileSync(path.join(__dirname, '../../renderer/features/overlay/OverlayApp.tsx'), 'utf8')
    expect(source).toContain('setSelectedItemId(item.id)')
    expect(source).toContain('revealGameplayTimestamp')
    expect(source).not.toMatch(/await\s+.*findLeague|execFileSync|powershell/i)
    expect(source).toContain('onActivate={onRowActivate}')
    expect(source).not.toMatch(/data-testid="overlay-jump"/)
  })

  it('opens and minimizes without waiting for poll, PowerShell, or sidecar', () => {
    const source = readFileSync(path.join(__dirname, '../../renderer/features/overlay/OverlayApp.tsx'), 'utf8')
    expect(source).toContain("setPresentation('OVERLAY_OPEN')")
    expect(source).toContain("setPresentation('LAUNCHER')")
    expect(source).toContain("overlaySetPresentation('overlay')")
    expect(source).toContain("overlaySetPresentation('launcher')")
    expect(source).not.toMatch(/await window\.rift\.overlaySetPresentation/)
  })

  it('does not hide on mouseleave, blur, or inactivity timers', () => {
    const overlay = readFileSync(
      path.join(__dirname, '../../renderer/features/overlay/OverlayApp.tsx'),
      'utf8'
    )
    const controller = readFileSync(path.join(__dirname, 'controller.ts'), 'utf8')
    expect(overlay).not.toMatch(/onMouseLeave|onMouseOut|onBlur=/)
    expect(controller).not.toMatch(/\.on\(['"]blur['"]/)
    expect(controller).not.toMatch(/idleHide|hoverHide/)
    expect(controller).not.toMatch(/setTimeout\([^)]*hide\(/)
    expect(overlay).not.toMatch(/overlayHide\(\)/)
  })

  it('does not reset user presentation from poll or League-miss reconciliation', () => {
    const controller = readFileSync(path.join(__dirname, 'controller.ts'), 'utf8')
    expect(controller).toContain('nextUserIntent')
    expect(controller).toContain('isTerminalReplaySession')
    expect(controller).toContain('sameContext')
    const applyStart = controller.indexOf('private applyDecision')
    const applyEnd = controller.indexOf('private relayout')
    expect(controller.slice(applyStart, applyEnd)).not.toMatch(/userIntent/)
  })

  it('keeps PowerShell enumeration off the synchronous FindWindow hot path', () => {
    const source = readFileSync(path.join(__dirname, 'leagueWindow.ts'), 'utf8')
    expect(source).toContain('findViaFindWindow')
    expect(source).toContain('schedulePowerShellFallback')
    expect(source).not.toMatch(/execFileSync/)
    expect(source).toMatch(/execFileAsync|promisify\(execFile\)/)
  })
})
