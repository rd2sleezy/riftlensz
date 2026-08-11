/** Overlay lifecycle: show/hide with League + replay session (R.10.5). */

import { join } from 'node:path'
import { app, BrowserWindow } from 'electron'
import { logger } from '../logging'
import {
  applyOverlayBounds,
  createOverlayWindow,
  primaryWorkArea,
  workAreaForRect
} from './createOverlayWindow'
import {
  findLeagueClientWindow,
  isReplaySessionActive,
  shouldShowOverlay
} from './leagueWindow'
import { resolveOverlayRect } from './placement'
import { loadOverlayPrefs, mergeOverlayPrefs, saveOverlayPrefs } from './prefs'
import {
  COMPACT_HEIGHT,
  EXPANDED_HEIGHT,
  LEAGUE_MISSING_GRACE_POLLS,
  OVERLAY_POLL_MS,
  type OverlayContext,
  type OverlayPrefs,
  type Rect
} from './types'

export type OverlaySessionSnapshot = {
  sessionPhase: string | null
  sessionReachedReady: boolean
  liveGame: boolean
}

export class OverlayController {
  private window: BrowserWindow | null = null
  private context: OverlayContext | null = null
  private prefs: OverlayPrefs
  private timer: NodeJS.Timeout | null = null
  private missingPolls = 0
  private lastLeagueBounds: Rect | null = null
  private session: OverlaySessionSnapshot = {
    sessionPhase: null,
    sessionReachedReady: false,
    liveGame: false
  }
  private readonly userDataPath: string
  private readonly preloadPath: string
  private readonly rendererDevUrl: string | null
  private mainWindow: BrowserWindow | null = null

  constructor(options?: {
    userDataPath?: string
    preloadPath?: string
    rendererDevUrl?: string | null
  }) {
    this.userDataPath = options?.userDataPath ?? app.getPath('userData')
    this.preloadPath =
      options?.preloadPath ?? join(__dirname, '../preload/index.js')
    this.rendererDevUrl =
      options?.rendererDevUrl ?? process.env['ELECTRON_RENDERER_URL'] ?? null
    this.prefs = loadOverlayPrefs(this.userDataPath)
  }

  setMainWindow(win: BrowserWindow | null): void {
    this.mainWindow = win
  }

  isOverlayWindow(win: BrowserWindow): boolean {
    return this.window !== null && this.window.id === win.id
  }

  getContext(): OverlayContext | null {
    return this.context
  }

  getPrefs(): OverlayPrefs {
    return { ...this.prefs }
  }

  setPrefs(patch: Partial<OverlayPrefs>): OverlayPrefs {
    this.prefs = saveOverlayPrefs(this.userDataPath, mergeOverlayPrefs(this.prefs, patch))
    if (this.window !== null && !this.window.isDestroyed()) {
      this.window.setOpacity(this.prefs.opacity)
      this.relayout()
    }
    return this.getPrefs()
  }

  open(context: OverlayContext, session?: Partial<OverlaySessionSnapshot>): { ok: true } | { ok: false; reason: string } {
    if (!this.prefs.enabled) {
      return { ok: false, reason: 'prefs_disabled' }
    }
    if (session?.liveGame === true || this.session.liveGame) {
      this.hide('live_game')
      return { ok: false, reason: 'live_game' }
    }
    this.context = context
    if (session !== undefined) {
      this.session = { ...this.session, ...session }
    }
    this.ensureWindow()
    this.startPolling()
    this.tick()
    return { ok: true }
  }

  updateSession(session: Partial<OverlaySessionSnapshot>): void {
    this.session = { ...this.session, ...session }
    if (session.liveGame === true) {
      this.hide('live_game')
      return
    }
    this.tick()
  }

  close(): void {
    this.context = null
    this.session = {
      sessionPhase: null,
      sessionReachedReady: false,
      liveGame: false
    }
    this.stopPolling()
    this.destroyWindow()
  }

  hide(reason = 'manual'): void {
    logger.info({ reason }, 'overlay hide')
    if (this.window !== null && !this.window.isDestroyed() && this.window.isVisible()) {
      this.window.hide()
    }
  }

  setUserBounds(bounds: Rect): OverlayPrefs {
    const workArea = workAreaForRect(bounds)
    const clamped = resolveOverlayRect({
      league: this.lastLeagueBounds ?? workArea,
      workArea,
      prefs: {
        compact: this.prefs.compact,
        position: { x: bounds.x, y: bounds.y },
        width: bounds.width
      },
      height: bounds.height
    })
    this.prefs = saveOverlayPrefs(
      this.userDataPath,
      mergeOverlayPrefs(this.prefs, {
        position: { x: clamped.x, y: clamped.y },
        width: clamped.width
      })
    )
    if (this.window !== null && !this.window.isDestroyed()) {
      applyOverlayBounds(this.window, {
        ...clamped,
        height: this.prefs.compact ? COMPACT_HEIGHT : EXPANDED_HEIGHT
      })
    }
    return this.getPrefs()
  }

  private ensureWindow(): void {
    if (this.window !== null && !this.window.isDestroyed()) {
      return
    }
    const initial = this.computeBounds()
    this.window = createOverlayWindow({
      preloadPath: this.preloadPath,
      rendererDevUrl: this.rendererDevUrl,
      initialBounds: initial,
      opacity: this.prefs.opacity,
      onMoved: (bounds) => {
        this.setUserBounds(bounds)
      }
    })
    this.window.on('closed', () => {
      this.window = null
      this.stopPolling()
    })
  }

  private destroyWindow(): void {
    if (this.window !== null && !this.window.isDestroyed()) {
      this.window.destroy()
    }
    this.window = null
  }

  private startPolling(): void {
    if (this.timer !== null) {
      return
    }
    this.timer = setInterval(() => this.tick(), OVERLAY_POLL_MS)
  }

  private stopPolling(): void {
    if (this.timer !== null) {
      clearInterval(this.timer)
      this.timer = null
    }
  }

  private tick(): void {
    const league = findLeagueClientWindow()
    if (league === null) {
      this.missingPolls += 1
    } else {
      this.missingPolls = 0
      this.lastLeagueBounds = league.bounds
    }
    const decision = shouldShowOverlay({
      prefsEnabled: this.prefs.enabled,
      liveGame: this.session.liveGame,
      hasContext: this.context !== null,
      sessionActive: isReplaySessionActive(
        this.session.sessionPhase,
        this.session.sessionReachedReady
      ),
      league,
      missingPolls: this.missingPolls,
      gracePolls: LEAGUE_MISSING_GRACE_POLLS
    })
    if (!decision.visible) {
      this.hide(decision.reason)
      if (decision.reason === 'session_inactive' || decision.reason === 'live_game') {
        // Keep context for reopen, but stop claiming a live overlay session.
      }
      return
    }
    this.ensureWindow()
    if (this.window === null || this.window.isDestroyed()) {
      return
    }
    this.relayout()
    if (!this.window.isVisible()) {
      this.window.showInactive()
    }
  }

  private relayout(): void {
    if (this.window === null || this.window.isDestroyed()) {
      return
    }
    applyOverlayBounds(this.window, this.computeBounds())
  }

  private computeBounds(): Rect {
    const leagueBounds = this.lastLeagueBounds
    const workArea = leagueBounds !== null ? workAreaForRect(leagueBounds) : primaryWorkArea()
    const league = leagueBounds ?? {
      x: workArea.x,
      y: workArea.y,
      width: workArea.width,
      height: workArea.height
    }
    return resolveOverlayRect({
      league,
      workArea,
      prefs: this.prefs,
      height: this.prefs.compact ? COMPACT_HEIGHT : EXPANDED_HEIGHT
    })
  }
}

/** True when the only open windows are overlay companions (main closed). */
export function onlyOverlayWindowsRemain(
  windows: BrowserWindow[],
  isOverlay: (win: BrowserWindow) => boolean
): boolean {
  return windows.length > 0 && windows.every((win) => isOverlay(win))
}
