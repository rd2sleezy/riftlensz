/** Explicit overlay presentation state (R.10.5). No hover/inactivity transitions. */

export type OverlayPresentation = 'HIDDEN_NO_SESSION' | 'LAUNCHER' | 'OVERLAY_OPEN'

/** User-controlled surface. Never inferred from mouse, focus, or idle time. */
export type OverlayUserIntent = 'launcher' | 'overlay'

export type OverlayVisibilityInput = {
  prefsEnabled: boolean
  liveGame: boolean
  hasContext: boolean
  sessionActive: boolean
  leaguePresent: boolean
  leagueMinimized: boolean
  missingPolls: number
  gracePolls?: number
  exclusiveFullscreen: boolean
  userIntent: OverlayUserIntent
}

export type OverlayVisibilityDecision = {
  presentation: OverlayPresentation
  showWindow: boolean
  needsCompat: boolean
  reason: string
}

function hidden(reason: string): OverlayVisibilityDecision {
  return {
    presentation: 'HIDDEN_NO_SESSION',
    showWindow: false,
    needsCompat: false,
    reason
  }
}

/**
 * Resolve launcher vs full overlay vs hidden.
 * Exclusive fullscreen still shows a companion surface (launcher or guided compat).
 * There is no mouseleave, blur, or inactivity path to LAUNCHER.
 */
export function resolveOverlayPresentation(
  input: OverlayVisibilityInput
): OverlayVisibilityDecision {
  if (!input.prefsEnabled) {
    return hidden('prefs_disabled')
  }
  if (input.liveGame) {
    return hidden('live_game')
  }
  if (!input.hasContext) {
    return hidden('no_context')
  }
  if (!input.sessionActive) {
    return hidden('session_inactive')
  }
  if (input.leagueMinimized) {
    return hidden('league_minimized')
  }
  if (!input.leaguePresent) {
    const grace = input.gracePolls ?? 3
    if (input.missingPolls > grace) {
      return hidden('league_missing')
    }
  }

  const needsCompat = input.exclusiveFullscreen
  const reason = needsCompat ? 'exclusive_fullscreen' : 'ok'
  if (input.userIntent === 'overlay') {
    return {
      presentation: 'OVERLAY_OPEN',
      showWindow: true,
      needsCompat,
      reason
    }
  }
  return {
    presentation: 'LAUNCHER',
    showWindow: true,
    needsCompat,
    reason
  }
}

/** Session reconnects always return to the launcher, never auto-expand. */
export function intentAfterSessionReset(): OverlayUserIntent {
  return 'launcher'
}

export function isInactivityHideReason(reason: string): boolean {
  return (
    reason === 'mouseleave' ||
    reason === 'hover' ||
    reason === 'idle' ||
    reason === 'blur' ||
    reason === 'focus_lost' ||
    reason === 'inactivity'
  )
}
