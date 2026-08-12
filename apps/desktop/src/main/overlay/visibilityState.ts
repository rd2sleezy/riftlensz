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

/** True only for a genuine session end — not SEEKING, PLAYING, or a READY refresh. */
export function isTerminalReplaySession(phase: string | null | undefined): boolean {
  return phase === 'CLOSED' || phase === 'FAILED' || phase === 'IDLE' || phase === 'CANCELLED'
}

export type OverlayIntentAction =
  | 'expand'
  | 'minimize'
  | 'close'
  | 'live_game'
  | 'open'
  | 'status'
  | 'tick'
  | 'league_refresh'
  | 'bounds_refresh'

/**
 * User presentation is sticky. Polls, League probes, seeks, and READY refreshes
 * must not change it. Only Minimize, close, live-game, terminal session, or a
 * genuinely new context may return to launcher.
 */
export function nextUserIntent(input: {
  current: OverlayUserIntent
  action: OverlayIntentAction
  sameContext?: boolean
  terminalSession?: boolean
}): OverlayUserIntent {
  if (input.action === 'expand') {
    return 'overlay'
  }
  if (input.action === 'minimize') {
    return 'launcher'
  }
  if (input.action === 'close' || input.action === 'live_game') {
    return 'launcher'
  }
  if (input.action === 'open') {
    return input.sameContext === true ? input.current : 'launcher'
  }
  if (input.action === 'status' && input.terminalSession === true) {
    return 'launcher'
  }
  return input.current
}

export function effectiveOverlayPresentation(
  sessionAllowsOverlay: boolean,
  userIntent: OverlayUserIntent
): OverlayPresentation {
  if (!sessionAllowsOverlay) {
    return 'HIDDEN_NO_SESSION'
  }
  return userIntent === 'overlay' ? 'OVERLAY_OPEN' : 'LAUNCHER'
}

export type OverlayStickyState = {
  userIntent: OverlayUserIntent
  contextKey: string | null
  sessionAllows: boolean
}

export type OverlayStickyEvent =
  | { type: 'open'; contextKey: string; sessionAllows: boolean }
  | { type: 'expand' }
  | { type: 'minimize' }
  | { type: 'status'; phase: string | null; reachedReady: boolean; contextKey: string }
  | { type: 'tick' }
  | { type: 'league_refresh'; present: boolean }
  | { type: 'bounds_refresh' }
  | { type: 'seek_start' }
  | { type: 'seek_finish' }
  | { type: 'idle' }
  | { type: 'close' }
  | { type: 'live_game' }

export function reduceOverlayStickyState(
  state: OverlayStickyState,
  event: OverlayStickyEvent
): OverlayStickyState {
  if (event.type === 'open') {
    const sameContext = state.contextKey === event.contextKey
    return {
      contextKey: event.contextKey,
      sessionAllows: event.sessionAllows,
      userIntent: nextUserIntent({
        current: state.userIntent,
        action: 'open',
        sameContext
      })
    }
  }
  if (event.type === 'expand') {
    return { ...state, userIntent: nextUserIntent({ current: state.userIntent, action: 'expand' }) }
  }
  if (event.type === 'minimize') {
    return { ...state, userIntent: nextUserIntent({ current: state.userIntent, action: 'minimize' }) }
  }
  if (event.type === 'close') {
    return {
      contextKey: null,
      sessionAllows: false,
      userIntent: nextUserIntent({ current: state.userIntent, action: 'close' })
    }
  }
  if (event.type === 'live_game') {
    return {
      ...state,
      sessionAllows: false,
      userIntent: nextUserIntent({ current: state.userIntent, action: 'live_game' })
    }
  }
  if (event.type === 'status') {
    const terminal = isTerminalReplaySession(event.phase)
    const sameContext = state.contextKey === event.contextKey
    const sessionAllows = !terminal && event.reachedReady && sameContext
    return {
      contextKey: event.contextKey,
      sessionAllows,
      userIntent: nextUserIntent({
        current: state.userIntent,
        action: 'status',
        sameContext,
        terminalSession: terminal
      })
    }
  }
  if (event.type === 'league_refresh') {
    return { ...state, sessionAllows: event.present ? state.sessionAllows : state.sessionAllows }
  }
  return state
}

export function presentationOf(state: OverlayStickyState): OverlayPresentation {
  return effectiveOverlayPresentation(state.sessionAllows, state.userIntent)
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
