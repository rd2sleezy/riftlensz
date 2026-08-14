/**
 * Mac overlay placement acceptance (contracts + live probe diagnostics).
 * Live Open Replay / seek deltas remain in mac_install_seek_acceptance.py.
 */

import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  applyOverlayWindowChrome,
  overlayWindowOptionsForPlatform
} from '../../apps/desktop/src/main/overlay/platform'
import { isHudSafe, resolveOverlayRect } from '../../apps/desktop/src/main/overlay/placement'
import { DEFAULT_OVERLAY_PREFS } from '../../apps/desktop/src/main/overlay/types'

const OUT = join(__dirname, 'mac_overlay_placement_acceptance.json')

function main(): void {
  const before = {
    alwaysOnTopLevel: 'floating',
    alwaysOnTopRelativeLevel: 0,
    note: 'floating sits below Dock / Metal game windows on macOS'
  }
  const after = overlayWindowOptionsForPlatform('darwin')
  const league = { x: 0, y: 25, width: 1512, height: 957 }
  const overlay = resolveOverlayRect({
    league,
    workArea: { x: 0, y: 25, width: 1512, height: 957 },
    prefs: DEFAULT_OVERLAY_PREFS,
    height: 440
  })
  const calls: string[] = []
  applyOverlayWindowChrome(
    {
      setFullScreenable: (v) => calls.push(`fullscreenable:${v}`),
      setVisibleOnAllWorkspaces: (v, opts) =>
        calls.push(`workspaces:${v}:${opts?.visibleOnFullScreen === true}`),
      setAlwaysOnTop: (flag, level, relative) =>
        calls.push(`aot:${flag}:${level}:${relative ?? 0}`),
      moveTop: () => calls.push('moveTop'),
      setIgnoreMouseEvents: (ignore) => calls.push(`ignore:${ignore}`)
    },
    'darwin'
  )
  const report = {
    root_cause:
      'macOS overlay used alwaysOnTopLevel=floating (below League) and could show before League bounds resolved, so the panel appeared tied to the RiftLens Space/z-order.',
    before,
    after: {
      alwaysOnTopLevel: after.alwaysOnTopLevel,
      alwaysOnTopRelativeLevel: after.alwaysOnTopRelativeLevel,
      type: after.type,
      visibleOnAllWorkspaces: after.visibleOnAllWorkspaces,
      visibleOnFullScreen: after.visibleOnFullScreen,
      fullscreenable: after.fullscreenable,
      parentedToMainWindow: false
    },
    chrome_calls: calls,
    example_league_bounds: league,
    example_overlay_bounds: overlay,
    overlay_hud_safe: isHudSafe(league, overlay),
    permission_guidance:
      'If League bounds cannot be read, grant Screen Recording or Accessibility for RiftLens, keep Windowed/Borderless, then Recheck.',
    ok:
      after.alwaysOnTopLevel === 'screen-saver' &&
      after.type === 'panel' &&
      calls.includes('aot:true:screen-saver:1') &&
      isHudSafe(league, overlay)
  }
  writeFileSync(OUT, `${JSON.stringify(report, null, 2)}\n`, 'utf8')
  console.log(JSON.stringify(report, null, 2))
  if (!report.ok) {
    process.exit(1)
  }
}

main()
