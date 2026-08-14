/** Overlay lifecycle: explicit launcher / overlay / hidden (R.10.5). */

import { join } from 'node:path'
import { app, BrowserWindow, screen } from 'electron'
import { IPC } from '../ipc/channels'
import { logger } from '../logging'
import { BORDERLESS_REQUIRED_MESSAGE } from './displayModeAssist'
import {
  applyOverlayBounds,
  createOverlayWindow,
  primaryWorkArea,
  workAreaForRect
} from './createOverlayWindow'
import { overlayWindowOptionsForPlatform } from './platform'
import {
  classifyDisplayMode,
  findLeagueClientWindow,
  isExclusiveD3dFullscreen,
  isReplaySessionActive,
  refreshLeagueClientWindowAsync
} from './leagueWindow'
import { resolveCompatRect, resolveLauncherRect, resolveOverlayRect } from './placement'
import { loadOverlayPrefs, mergeOverlayPrefs, saveOverlayPrefs } from './prefs'
import {
  LEAGUE_MISSING_GRACE_POLLS,
  NAVIGATOR_HEIGHT,
  OVERLAY_POLL_MS,
  type LeagueDisplayMode,
  type OverlayContext,
  type OverlayPrefs,
  type Rect
} from './types'
import {
  isTerminalReplaySession,
  nextUserIntent,
  resolveOverlayPresentation,
  type OverlayPresentation,
  type OverlayUserIntent,
  type OverlayVisibilityDecision
} from './visibilityState'

export type OverlaySessionSnapshot = {
  sessionPhase: string | null
  sessionReachedReady: boolean
  liveGame: boolean
}

export type OverlayLifecycleEvent = {
  kind: 'visibility' | 'display_mode' | 'session' | 'presentation'
  visible: boolean
  reason: string
  displayMode: LeagueDisplayMode
  message: string | null
  sessionPhase: string | null
  sessionReachedReady: boolean
  presentation: OverlayPresentation
  needsCompat: boolean
}

function rectsEqual(a: Rect, b: Rect): boolean {
  return a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height
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
  private userIntent: OverlayUserIntent = 'launcher'
  private presentation: OverlayPresentation = 'HIDDEN_NO_SESSION'
  private needsCompat = false
  private lastAppliedBounds: Rect | null = null
  private lastBroadcastKey = ''
  private lastLeagueSeenAt = 0
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
    const visible =
      this.presentation !== 'HIDDEN_NO_SESSION' &&
      this.window !== null &&
      !this.window.isDestroyed() &&
      this.window.isVisible()
    return {
      kind: 'visibility',
      visible,
      reason: this.lastReason,
      displayMode: this.displayMode,
      message: this.needsCompat ? BORDERLESS_REQUIRED_MESSAGE : null,
      sessionPhase: this.session.sessionPhase,
      sessionReachedReady: this.session.sessionReachedReady,
      presentation: this.presentation,
      needsCompat: this.needsCompat
    }
  }

  setPrefs(patch: Partial<OverlayPrefs>): OverlayPrefs {
    this.prefs = saveOverlayPrefs(this.userDataPath, mergeOverlayPrefs(this.prefs, patch))
    if (this.window !== null && !this.window.isDestroyed()) {
      this.relayout(true)
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
    const sameContext =
      this.context !== null &&
      this.context.reviewId === context.reviewId &&
      this.context.matchId === context.matchId &&
      this.context.sourceId === context.sourceId
    this.userIntent = nextUserIntent({
      current: this.userIntent,
      action: 'open',
      sameContext
    })
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
      this.userIntent = nextUserIntent({ current: this.userIntent, action: 'live_game' })
      this.hide('live_game')
      this.broadcastLifecycle('session')
      return
    }
    this.userIntent = nextUserIntent({
      current: this.userIntent,
      action: 'status',
      sameContext: true,
      terminalSession: isTerminalReplaySession(this.session.sessionPhase)
    })
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
    this.userIntent = nextUserIntent({ current: this.userIntent, action: 'close' })
    this.presentation = 'HIDDEN_NO_SESSION'
    this.needsCompat = false
    this.stopPolling()
    this.destroyWindow()
    this.broadcastLifecycle('visibility')
  }

  /** Session/lifecycle hide. Not used for minimize or hover. */
  hide(reason = 'manual'): void {
    this.lastReason = reason
    this.presentation = 'HIDDEN_NO_SESSION'
    this.userIntent = nextUserIntent({
      current: this.userIntent,
      action: reason === 'live_game' ? 'live_game' : 'close'
    })
    this.needsCompat = false
    logger.info({ reason }, 'overlay hide')
    if (this.window !== null && !this.window.isDestroyed() && this.window.isVisible()) {
      this.window.hide()
    }
    this.broadcastLifecycle('visibility')
  }

  /** Explicit minimize → Access Overlay launcher. Does not touch replay/session. */
  minimize(): OverlayLifecycleEvent {
    this.userIntent = nextUserIntent({ current: this.userIntent, action: 'minimize' })
    this.applyDecision(this.evaluate(), { forceLayout: true, kind: 'presentation' })
    return this.getLifecycleSnapshot()
  }

  /** Explicit Access Overlay → full coaching (or compat guide). */
  expand(): OverlayLifecycleEvent {
    this.userIntent = nextUserIntent({ current: this.userIntent, action: 'expand' })
    this.applyDecision(this.evaluate(), { forceLayout: true, kind: 'presentation' })
    return this.getLifecycleSnapshot()
  }

  setPresentation(intent: OverlayUserIntent): OverlayLifecycleEvent {
    return intent === 'overlay' ? this.expand() : this.minimize()
  }

  /** Re-read exclusive-fullscreen / League bounds after the player changes display mode. */
  recheckDisplay(): OverlayLifecycleEvent {
    void refreshLeagueClientWindowAsync().then(() => {
      this.tick()
    })
    this.tick()
    this.broadcastLifecycle('display_mode')
    return this.getLifecycleSnapshot()
  }

  setUserBounds(bounds: Rect): OverlayPrefs {
    const workArea = workAreaForRect(bounds)
    const league = this.lastLeagueBounds ?? workArea
    if (this.presentation === 'LAUNCHER') {
      const placed = resolveLauncherRect({
        league,
        workArea,
        launcherPosition: { x: bounds.x, y: bounds.y }
      })
      this.prefs = saveOverlayPrefs(
        this.userDataPath,
        mergeOverlayPrefs(this.prefs, {
          launcherPosition: { x: placed.x, y: placed.y }
        })
      )
    } else {
      const placed = resolveOverlayRect({
        league,
        workArea,
        prefs: {
          ...this.prefs,
          position: { x: bounds.x, y: bounds.y }
        },
        height: bounds.height
      })
      this.prefs = saveOverlayPrefs(
        this.userDataPath,
        mergeOverlayPrefs(this.prefs, {
          position: { x: placed.x, y: placed.y }
        })
      )
    }
    this.relayout(true)
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
      onMoved: (bounds) => {
        this.setUserBounds(bounds)
      }
    })
    this.lastAppliedBounds = initial
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
    this.lastAppliedBounds = null
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

  private evaluate(): OverlayVisibilityDecision {
    return resolveOverlayPresentation({
      prefsEnabled: this.prefs.enabled,
      liveGame: this.session.liveGame,
      hasContext: this.context !== null,
      sessionActive: isReplaySessionActive(
        this.session.sessionPhase,
        this.session.sessionReachedReady
      ),
      leaguePresent: this.lastLeagueBounds !== null,
      leagueMinimized: false,
      missingPolls: this.missingPolls,
      gracePolls: LEAGUE_MISSING_GRACE_POLLS,
      exclusiveFullscreen: this.displayMode === 'exclusive_fullscreen',
      userIntent: this.userIntent
    })
  }

  private tick(): void {
    const exclusive = isExclusiveD3dFullscreen()
    let league = findLeagueClientWindow()
    let leagueMinimized = false
    if (league !== null) {
      this.missingPolls = 0
      this.lastLeagueSeenAt = Date.now()
      this.lastLeagueBounds = league.bounds
      leagueMinimized = league.minimized
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
      const graceMs = LEAGUE_MISSING_GRACE_POLLS * OVERLAY_POLL_MS
      const recentlySeen =
        this.lastLeagueBounds !== null && Date.now() - this.lastLeagueSeenAt <= graceMs
      if (!recentlySeen) {
        this.missingPolls += 1
      }
      if (exclusive) {
        this.displayMode = 'exclusive_fullscreen'
      }
    }

    const graceMs = LEAGUE_MISSING_GRACE_POLLS * OVERLAY_POLL_MS
    const leaguePresent =
      league !== null ||
      (this.lastLeagueBounds !== null && Date.now() - this.lastLeagueSeenAt <= graceMs)

    const decision = resolveOverlayPresentation({
      prefsEnabled: this.prefs.enabled,
      liveGame: this.session.liveGame,
      hasContext: this.context !== null,
      sessionActive: isReplaySessionActive(
        this.session.sessionPhase,
        this.session.sessionReachedReady
      ),
      leaguePresent,
      leagueMinimized,
      missingPolls: this.missingPolls,
      gracePolls: LEAGUE_MISSING_GRACE_POLLS,
      exclusiveFullscreen: exclusive || this.displayMode === 'exclusive_fullscreen',
      userIntent: this.userIntent
    })
    this.applyDecision(decision, { forceLayout: false, kind: 'visibility' })
  }

  private applyDecision(
    decision: OverlayVisibilityDecision,
    options: { forceLayout: boolean; kind: OverlayLifecycleEvent['kind'] }
  ): void {
    this.lastReason = decision.reason
    this.needsCompat = decision.needsCompat
    this.presentation = decision.presentation
    if (!decision.showWindow) {
      if (this.window !== null && !this.window.isDestroyed() && this.window.isVisible()) {
        this.window.hide()
      }
      this.broadcastLifecycle(options.kind)
      return
    }
    this.ensureWindow()
    if (this.window === null || this.window.isDestroyed()) {
      return
    }
    this.relayout(options.forceLayout)
    if (!this.window.isVisible()) {
      const platformOpts = overlayWindowOptionsForPlatform()
      this.window.setAlwaysOnTop(true, platformOpts.alwaysOnTopLevel)
      if (platformOpts.visibleOnAllWorkspaces) {
        this.window.setVisibleOnAllWorkspaces(true, {
          visibleOnFullScreen: platformOpts.visibleOnFullScreen
        })
      }
      this.window.showInactive()
    }
    this.broadcastLifecycle(options.kind)
  }

  private relayout(force: boolean): void {
    if (this.window === null || this.window.isDestroyed()) {
      return
    }
    const next = this.computeBounds()
    if (!force && this.lastAppliedBounds !== null && rectsEqual(this.lastAppliedBounds, next)) {
      return
    }
    applyOverlayBounds(this.window, next)
    this.lastAppliedBounds = next
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
    if (this.presentation === 'LAUNCHER') {
      return resolveLauncherRect({
        league,
        workArea,
        launcherPosition: this.prefs.launcherPosition
      })
    }
    if (this.needsCompat) {
      return resolveCompatRect({
        league,
        workArea,
        position: this.prefs.position
      })
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
    const key = JSON.stringify({
      kind: payload.kind,
      visible: payload.visible,
      reason: payload.reason,
      displayMode: payload.displayMode,
      presentation: payload.presentation,
      needsCompat: payload.needsCompat,
      sessionPhase: payload.sessionPhase
    })
    if (key === this.lastBroadcastKey) {
      return
    }
    this.lastBroadcastKey = key
    const targets = new Set(BrowserWindow.getAllWindows())
    if (this.mainWindow !== null && !this.mainWindow.isDestroyed()) {
      targets.add(this.mainWindow)
    }
    for (const win of targets) {
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
