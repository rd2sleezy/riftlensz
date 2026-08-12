import { describe, expect, it } from 'vitest'
import {
  intentAfterSessionReset,
  isInactivityHideReason,
  resolveOverlayPresentation,
  type OverlayVisibilityInput
} from './visibilityState'

const ready: OverlayVisibilityInput = {
  prefsEnabled: true,
  liveGame: false,
  hasContext: true,
  sessionActive: true,
  leaguePresent: true,
  leagueMinimized: false,
  missingPolls: 0,
  exclusiveFullscreen: false,
  userIntent: 'launcher'
}

describe('overlay explicit visibility state', () => {
  it('READY → launcher', () => {
    expect(resolveOverlayPresentation(ready)).toEqual({
      presentation: 'LAUNCHER',
      showWindow: true,
      needsCompat: false,
      reason: 'ok'
    })
  })

  it('launcher intent + expand request → overlay', () => {
    expect(resolveOverlayPresentation({ ...ready, userIntent: 'overlay' }).presentation).toBe(
      'OVERLAY_OPEN'
    )
  })

  it('minimize is launcher, never HIDDEN while the session is active', () => {
    const minimized = resolveOverlayPresentation({ ...ready, userIntent: 'launcher' })
    expect(minimized.presentation).toBe('LAUNCHER')
    expect(minimized.showWindow).toBe(true)
  })

  it('replay close / session loss hides both surfaces', () => {
    expect(resolveOverlayPresentation({ ...ready, sessionActive: false }).presentation).toBe(
      'HIDDEN_NO_SESSION'
    )
    expect(resolveOverlayPresentation({ ...ready, hasContext: false }).presentation).toBe(
      'HIDDEN_NO_SESSION'
    )
  })

  it('live match never shows launcher or overlay', () => {
    const live = resolveOverlayPresentation({ ...ready, liveGame: true, userIntent: 'overlay' })
    expect(live).toEqual({
      presentation: 'HIDDEN_NO_SESSION',
      showWindow: false,
      needsCompat: false,
      reason: 'live_game'
    })
  })

  it('exclusive fullscreen is not a silent hide — companion stays up with compat', () => {
    const launcher = resolveOverlayPresentation({
      ...ready,
      exclusiveFullscreen: true,
      userIntent: 'launcher'
    })
    expect(launcher.showWindow).toBe(true)
    expect(launcher.presentation).toBe('LAUNCHER')
    expect(launcher.needsCompat).toBe(true)
    expect(launcher.reason).toBe('exclusive_fullscreen')

    const expanded = resolveOverlayPresentation({
      ...ready,
      exclusiveFullscreen: true,
      userIntent: 'overlay'
    })
    expect(expanded.presentation).toBe('OVERLAY_OPEN')
    expect(expanded.needsCompat).toBe(true)
    expect(expanded.showWindow).toBe(true)
  })

  it('userIntent overlay is preserved across exclusive-fullscreen detection', () => {
    const decision = resolveOverlayPresentation({
      ...ready,
      exclusiveFullscreen: true,
      userIntent: 'overlay'
    })
    expect(decision.presentation).toBe('OVERLAY_OPEN')
  })

  it('reconnect intent is always launcher', () => {
    expect(intentAfterSessionReset()).toBe('launcher')
  })

  it('does not treat mouseleave, blur, or idle as hide reasons', () => {
    expect(isInactivityHideReason('ok')).toBe(false)
    expect(isInactivityHideReason('mouseleave')).toBe(true)
    expect(isInactivityHideReason('inactivity')).toBe(true)
    expect(isInactivityHideReason('blur')).toBe(true)
  })

  it('league missing after grace hides; grace keeps the requested surface', () => {
    expect(
      resolveOverlayPresentation({
        ...ready,
        leaguePresent: false,
        missingPolls: 4,
        userIntent: 'overlay'
      }).presentation
    ).toBe('HIDDEN_NO_SESSION')
    expect(
      resolveOverlayPresentation({
        ...ready,
        leaguePresent: false,
        missingPolls: 1,
        userIntent: 'overlay'
      }).presentation
    ).toBe('OVERLAY_OPEN')
  })
})
