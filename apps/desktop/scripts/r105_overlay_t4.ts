/**
 * R.10.5 T4: probe League window + HUD-safe placement against live bounds.
 *
 * Prerequisites: a native League replay client window is open.
 *   pnpm exec tsx scripts/r105_overlay_t4.ts
 */

import {
  defaultOverlayRect,
  findLeagueClientWindow,
  isHudSafe,
  shouldShowOverlay
} from '../src/main/overlay'

function main(): number {
  const league = findLeagueClientWindow()
  console.log(JSON.stringify({ league }, null, 2))
  if (league === null) {
    console.error('FAIL: League client window not found (open a native replay first)')
    return 2
  }
  const overlay = defaultOverlayRect({
    league: league.bounds,
    workArea: league.bounds,
    prefs: { compact: true, position: null, width: 320 }
  })
  const hudSafe = isHudSafe(league.bounds, overlay)
  const visibility = shouldShowOverlay({
    prefsEnabled: true,
    liveGame: false,
    hasContext: true,
    sessionActive: true,
    league,
    missingPolls: 0
  })
  console.log(JSON.stringify({ overlay, hudSafe, visibility }, null, 2))
  if (!hudSafe || !visibility.visible) {
    console.error('FAIL: placement or visibility policy rejected')
    return 3
  }
  console.log('PASS: League companion placement is HUD-safe')
  return 0
}

process.exit(main())
