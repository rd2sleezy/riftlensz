/** Overlay lifecycle: show/hide with League + replay session (R.10.5). */

import { join } from 'node:path'
import { app, BrowserWindow, screen } from 'electron'
import { IPC } from '../ipc/channels'
import { logger } from '../logging'
import {
  applyOverlayBounds,
  createOverlayWindow,
  primaryWorkArea,
  workAreaForRect
} from './createOverlayWindow'
import {
  classifyDisplayMode,
  findLeagueClientWindow,
  isExclusiveD3dFullscreen,
  isReplaySessionActive,
  refreshLeagueClientWindowAsync,
  shouldShowOverlay
} from './leagueWindow'
import { resolveOverlayRect } from './placement'
import { loadOverlayPrefs, mergeOverlayPrefs, saveOverlayPrefs } from './prefs'
import {
  EXCLUSIVE_FULLSCREEN_MESSAGE,
  LEAGUE_MISSING_GRACE_POLLS,
  NAVIGATOR_HEIGHT,
  OVERLAY_POLL_MS,
  type LeagueDisplayMode,
  type OverlayContext,
  type OverlayPrefs,
  type Rect
} from './types'

export type OverlaySessionSnapshot = {
  sessionPhase: string | null
  sessionReachedReady: boolean
  liveGame: boolean
}

export type OverlayLifecycleEvent = {
  kind: 'visibility' | 'display_mode' | 'session'
  visible: boolean
  reason: string
  displayMode: LeagueDisplayMode
  message: string | null
  sessionPhase: string | null
  sessionReachedReady: boolean
}

export class OverlayController {
  private window: BrowserWindow | null = null
  private mainWindow: BrowserWindow | null = null
  private context: OverlayContext | null = null
  private prefs: OverlayPrefs
  private timer: NodeJS.Timeout | null = null
  private missingPolls = 0
  private lastLeagueBounds: Rect | null = null
  private displayMode: LeagueDisplayMode = 'unknown'
  private lastReason = 'idle'
  private session: OverlaySessionSnapshot = {
    sessionPhase: null,
    sessionReachedReady: false,
    liveGame: false
  }
  private readonly userDataPath: string
  private readonly preloadPath: string
  private readonly rendererDevUrl: string | null

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

  setMainWindow(_win: BrowserWindow | null): void {
    this.mainWindow = _win
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

  getDisplayMode(): LeagueDisplayMode {
    return this.displayMode
  }

  getLifecycleSnapshot(): OverlayLifecycleEvent {
    return {
      kind: 'visibility',
      visible: this.window !== null && !this.window.isDestroyed() && this.window.isVisible(),
      reason: this.lastReason,
      displayMode: this.displayMode,
      message:
        this.displayMode === 'exclusive_fullscreen' ? EXCLUSIVE_FULLSCREEN_MESSAGE : null,
      sessionPhase: this.session.sessionPhase,
      sessionReachedReady: this.session.sessionReachedReady
    }
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
    void refreshLeagueClientWindowAsync().then(() => this.tick())
    return { ok: true }
  }

  updateSession(session: Partial<OverlaySessionSnapshot>): void {
    this.session = { ...this.session, ...session }
    if (session.liveGame === true) {
      this.hide('live_game')
      this.broadcastLifecycle('session')
      return
    }
    this.tick()
    this.broadcastLifecycle('session')
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
    this.broadcastLifecycle('visibility')
  }

  hide(reason = 'manual'): void {
    this.lastReason = reason
    logger.info({ reason }, 'overlay hide')
    if (this.window !== null && !this.window.isDestroyed() && this.window.isVisible()) {
      this.window.hide()
    }
    this.broadcastLifecycle('visibility')
  }

  setUserBounds(bounds: Rect): OverlayPrefs {
    const workArea = workAreaForRect(bounds)
    const clamped = resolveOverlayRect({
      league: this.lastLeagueBounds ?? workArea,
      workArea,
      prefs: this.prefs,
      height: bounds.height
    })
    this.prefs = saveOverlayPrefs(
      this.userDataPath,
      mergeOverlayPrefs(this.prefs, {
        position: { x: clamped.x, y: clamped.y },
        navigatorWidth: this.prefs.navigatorWidth,
        detailWidth: this.prefs.detailWidth
      })
    )
    if (this.window !== null && !this.window.isDestroyed()) {
      applyOverlayBounds(this.window, resolveOverlayRect({
        league: this.lastLeagueBounds ?? workArea,
        workArea,
        prefs: this.prefs,
        height: NAVIGATOR_HEIGHT
      }))
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
    const exclusive = isExclusiveD3dFullscreen()
    let league = findLeagueClientWindow()
    if (league !== null) {
      this.missingPolls = 0
      this.lastLeagueBounds = league.bounds
      const display = screen.getDisplayMatching({
        x: Math.round(league.bounds.x),
        y: Math.round(league.bounds.y),
        width: Math.max(1, Math.round(league.bounds.width)),
        height: Math.max(1, Math.round(league.bounds.height))
      })
      this.displayMode = classifyDisplayMode({
        exclusiveD3d: exclusive,
        bounds: league.bounds,
        displayBounds: {
          x: display.bounds.x,
          y: display.bounds.y,
          width: display.bounds.width,
          height: display.bounds.height
        }
      })
      league = { ...league, displayMode: this.displayMode }
    } else {
      this.missingPolls += 1
      if (exclusive) {
        this.displayMode = 'exclusive_fullscreen'
      }
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
      gracePolls: LEAGUE_MISSING_GRACE_POLLS,
      exclusiveFullscreen: exclusive
    })
    this.lastReason = decision.reason
    if (!decision.visible) {
      this.hide(decision.reason)
      return
    }
    this.ensureWindow()
    if (this.window === null || this.window.isDestroyed()) {
      return
    }
    // Re-assert topmost after fullscreen transitions (borderless).
    this.window.setAlwaysOnTop(true, 'screen-saver')
    this.window.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
    this.relayout()
    if (!this.window.isVisible()) {
      this.window.showInactive()
    }
    this.broadcastLifecycle('visibility')
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
      height: NAVIGATOR_HEIGHT
    })
  }

  private broadcastLifecycle(kind: OverlayLifecycleEvent['kind']): void {
    const payload = { ...this.getLifecycleSnapshot(), kind }
    for (const win of BrowserWindow.getAllWindows()) {
      win.webContents.send(IPC.overlayLifecycleEvent, payload)
    }
  }
}

/** True when the only open windows are overlay companions (main closed). */
export function onlyOverlayWindowsRemain(
  windows: BrowserWindow[],
  isOverlay: (win: BrowserWindow) => boolean
): boolean {
  return windows.length > 0 && windows.every((win) => isOverlay(win))
}
