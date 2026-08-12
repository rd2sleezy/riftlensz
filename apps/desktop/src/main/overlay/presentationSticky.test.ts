import { describe, expect, it } from 'vitest'
import {
  effectiveOverlayPresentation,
  nextUserIntent,
  presentationOf,
  reduceOverlayStickyState,
  type OverlayStickyState
} from './visibilityState'

const SESSION = 'review:NA1_5617764200:src1'

function fresh(): OverlayStickyState {
  return { userIntent: 'launcher', contextKey: null, sessionAllows: false }
}

describe('OVERLAY_OPEN is sticky across ordinary updates', () => {
  it('READY → launcher → Access Overlay → stays OPEN through polls/seeks/focus/idle → Minimize → launcher', () => {
    let state = fresh()

    state = reduceOverlayStickyState(state, {
      type: 'open',
      contextKey: SESSION,
      sessionAllows: true
    })
    expect(presentationOf(state)).toBe('LAUNCHER')

    state = reduceOverlayStickyState(state, { type: 'expand' })
    expect(presentationOf(state)).toBe('OVERLAY_OPEN')

    const ordinary: Parameters<typeof reduceOverlayStickyState>[1][] = [
      { type: 'status', phase: 'READY', reachedReady: true, contextKey: SESSION },
      { type: 'status', phase: 'READY', reachedReady: true, contextKey: SESSION },
      { type: 'status', phase: 'PLAYING', reachedReady: true, contextKey: SESSION },
      { type: 'tick' },
      { type: 'tick' },
      { type: 'tick' },
      { type: 'league_refresh', present: true },
      { type: 'league_refresh', present: false },
      { type: 'bounds_refresh' },
      { type: 'seek_start' },
      { type: 'status', phase: 'SEEKING', reachedReady: true, contextKey: SESSION },
      { type: 'seek_finish' },
      { type: 'status', phase: 'PLAYING', reachedReady: true, contextKey: SESSION },
      { type: 'idle' },
      { type: 'idle' },
      { type: 'open', contextKey: SESSION, sessionAllows: true }
    ]
    for (const event of ordinary) {
      state = reduceOverlayStickyState(state, event)
      expect(presentationOf(state), JSON.stringify(event)).toBe('OVERLAY_OPEN')
    }

    state = reduceOverlayStickyState(state, { type: 'minimize' })
    expect(presentationOf(state)).toBe('LAUNCHER')
  })

  it('session loss while OPEN hides; a fresh READY session starts at launcher', () => {
    let state = reduceOverlayStickyState(fresh(), {
      type: 'open',
      contextKey: SESSION,
      sessionAllows: true
    })
    state = reduceOverlayStickyState(state, { type: 'expand' })
    expect(presentationOf(state)).toBe('OVERLAY_OPEN')

    state = reduceOverlayStickyState(state, {
      type: 'status',
      phase: 'IDLE',
      reachedReady: false,
      contextKey: SESSION
    })
    expect(presentationOf(state)).toBe('HIDDEN_NO_SESSION')
    expect(state.userIntent).toBe('launcher')

    state = reduceOverlayStickyState(state, {
      type: 'open',
      contextKey: `${SESSION}:next`,
      sessionAllows: true
    })
    expect(presentationOf(state)).toBe('LAUNCHER')
  })

  it('same-session READY refresh after a transient inactive tick does not collapse OPEN', () => {
    let state = reduceOverlayStickyState(fresh(), {
      type: 'open',
      contextKey: SESSION,
      sessionAllows: true
    })
    state = reduceOverlayStickyState(state, { type: 'expand' })
    state = {
      ...state,
      sessionAllows: false
    }
    expect(presentationOf(state)).toBe('HIDDEN_NO_SESSION')
    expect(state.userIntent).toBe('overlay')

    state = reduceOverlayStickyState(state, {
      type: 'status',
      phase: 'READY',
      reachedReady: true,
      contextKey: SESSION
    })
    expect(presentationOf(state)).toBe('OVERLAY_OPEN')
  })

  it('nextUserIntent ignores ticks, league refresh, and non-terminal status', () => {
    expect(
      nextUserIntent({ current: 'overlay', action: 'tick' })
    ).toBe('overlay')
    expect(
      nextUserIntent({ current: 'overlay', action: 'league_refresh' })
    ).toBe('overlay')
    expect(
      nextUserIntent({ current: 'overlay', action: 'status', terminalSession: false })
    ).toBe('overlay')
    expect(
      nextUserIntent({ current: 'overlay', action: 'open', sameContext: true })
    ).toBe('overlay')
    expect(
      nextUserIntent({ current: 'overlay', action: 'open', sameContext: false })
    ).toBe('launcher')
    expect(effectiveOverlayPresentation(true, 'overlay')).toBe('OVERLAY_OPEN')
    expect(effectiveOverlayPresentation(false, 'overlay')).toBe('HIDDEN_NO_SESSION')
  })
})
