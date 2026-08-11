/**
 * R.10.5 T4: probe League window + HUD-safe two-panel placement against live bounds.
 *
 * Prerequisites: a native League replay client window is open.
 *   pnpm exec tsx scripts/r105_overlay_t4.ts
 */

import {
  findLeagueClientWindow,
  isExclusiveD3dFullscreen,
  isHudSafe,
  resolveOverlayLayout,
  shouldShowOverlay
} from '../src/main/overlay'

function main(): number {
  const exclusive = isExclusiveD3dFullscreen()
  const league = findLeagueClientWindow()
  console.log(JSON.stringify({ exclusive, league }, null, 2))
  if (league === null) {
    console.error('FAIL: League client window not found (open a native replay first)')
    return 2
  }
  const layout = resolveOverlayLayout({
    league: league.bounds,
    workArea: league.bounds,
    prefs: {
      detailOpen: true,
      position: null,
      navigatorWidth: 300,
      detailWidth: 340
    }
  })
  const hudSafe = isHudSafe(league.bounds, layout.outer)
  const visibility = shouldShowOverlay({
    prefsEnabled: true,
    liveGame: false,
    hasContext: true,
    sessionActive: true,
    league,
    missingPolls: 0,
    exclusiveFullscreen: exclusive
  })
  console.log(JSON.stringify({ layout, hudSafe, visibility }, null, 2))
  if (visibility.reason === 'exclusive_fullscreen') {
    console.log('NOTE: exclusive fullscreen detected — overlay correctly refused')
    return 0
  }
  if (!hudSafe || !visibility.visible) {
    console.error('FAIL: placement or visibility policy rejected')
    return 3
  }
  console.log('PASS: League companion two-panel placement is HUD-safe')
  return 0
}

process.exit(main())
