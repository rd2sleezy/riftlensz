/**
 * R.10.5 T4: probe League window + HUD-safe launcher / two-panel placement.
 *
 * Prerequisites: a native League replay client window is open.
 *   pnpm exec tsx scripts/r105_overlay_t4.ts
 */

import {
  displayModeSwitchPolicy,
  findLeagueClientWindow,
  isExclusiveD3dFullscreen,
  isHudSafe,
  resolveLauncherRect,
  resolveOverlayLayout,
  resolveOverlayPresentation,
  shouldShowOverlay
} from '../src/main/overlay'

function main(): number {
  const exclusive = isExclusiveD3dFullscreen()
  const league = findLeagueClientWindow()
  const switchPolicy = displayModeSwitchPolicy()
  console.log(JSON.stringify({ exclusive, league, switchPolicy }, null, 2))
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
  const launcher = resolveLauncherRect({
    league: league.bounds,
    workArea: league.bounds,
    launcherPosition: null
  })
  const hudSafe = isHudSafe(league.bounds, layout.outer)
  const launcherSafe = isHudSafe(league.bounds, launcher)
  const visibility = shouldShowOverlay({
    prefsEnabled: true,
    liveGame: false,
    hasContext: true,
    sessionActive: true,
    league,
    missingPolls: 0,
    exclusiveFullscreen: exclusive
  })
  const presentation = resolveOverlayPresentation({
    prefsEnabled: true,
    liveGame: false,
    hasContext: true,
    sessionActive: true,
    leaguePresent: true,
    leagueMinimized: league.minimized,
    missingPolls: 0,
    exclusiveFullscreen: exclusive,
    userIntent: 'launcher'
  })
  console.log(JSON.stringify({ layout, launcher, hudSafe, launcherSafe, visibility, presentation }, null, 2))
  if (exclusive || presentation.needsCompat) {
    console.log('NOTE: exclusive fullscreen detected — guided Borderless + Recheck (no silent hide)')
    if (!presentation.showWindow) {
      console.error('FAIL: exclusive fullscreen silently hid the companion')
      return 3
    }
    return 0
  }
  if (!hudSafe || !launcherSafe || !visibility.visible || presentation.presentation !== 'LAUNCHER') {
    console.error('FAIL: placement or visibility policy rejected')
    return 3
  }
  console.log('PASS: launcher + two-panel placement are HUD-safe')
  return 0
}

process.exit(main())
