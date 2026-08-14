/** Shared League window helpers used by Windows and macOS overlay probes (R.10.5). */

import type { LeagueDisplayMode, LeagueWindowInfo, Rect } from './types'

export function classifyDisplayMode(input: {
  exclusiveD3d: boolean
  bounds: Rect
  displayBounds: Rect | null
}): LeagueDisplayMode {
  if (input.exclusiveD3d) {
    return 'exclusive_fullscreen'
  }
  if (input.displayBounds === null) {
    return 'unknown'
  }
  const covers =
    Math.abs(input.bounds.width - input.displayBounds.width) <= 2 &&
    Math.abs(input.bounds.height - input.displayBounds.height) <= 48 &&
    Math.abs(input.bounds.x - input.displayBounds.x) <= 2 &&
    Math.abs(input.bounds.y - input.displayBounds.y) <= 2
  return covers ? 'borderless' : 'windowed'
}

export function isLeagueTitle(title: string): boolean {
  const normalized = title.trim()
  if (normalized.length === 0) {
    return false
  }
  if (/riot client/i.test(normalized)) {
    return false
  }
  return (
    normalized.includes('League of Legends (TM) Client') ||
    normalized.includes('League of Legends')
  )
}

/** Visibility policy used by the controller (pure, testable). */
export function shouldShowOverlay(input: {
  prefsEnabled: boolean
  liveGame: boolean
  hasContext: boolean
  sessionActive: boolean
  league: LeagueWindowInfo | null
  missingPolls: number
  gracePolls?: number
  exclusiveFullscreen?: boolean
}): { visible: boolean; reason: string } {
  if (!input.prefsEnabled) {
    return { visible: false, reason: 'prefs_disabled' }
  }
  if (input.liveGame) {
    return { visible: false, reason: 'live_game' }
  }
  if (!input.hasContext) {
    return { visible: false, reason: 'no_context' }
  }
  if (!input.sessionActive) {
    return { visible: false, reason: 'session_inactive' }
  }
  if (input.league === null) {
    const grace = input.gracePolls ?? 3
    if (input.missingPolls > grace) {
      return { visible: false, reason: 'league_missing' }
    }
    return { visible: true, reason: 'league_grace' }
  }
  if (input.league.minimized) {
    return { visible: false, reason: 'league_minimized' }
  }
  if (
    input.exclusiveFullscreen === true ||
    input.league.displayMode === 'exclusive_fullscreen'
  ) {
    return { visible: true, reason: 'exclusive_fullscreen' }
  }
  return { visible: true, reason: 'ok' }
}

export function isReplaySessionActive(
  phase: string | null | undefined,
  reachedReady: boolean
): boolean {
  if (!reachedReady) {
    return false
  }
  return phase === 'READY' || phase === 'PLAYING' || phase === 'PAUSED' || phase === 'SEEKING'
}
