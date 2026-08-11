import { BrowserWindow, dialog, ipcMain } from 'electron'
import { z } from 'zod'
import {
  BuildManualSyncInputSchema,
  BuildManualSyncResultSchema,
  CloseReplayResultSchema,
  DesktopPlatformSchema,
  ErrorResultSchema,
  GameplayEnvironmentResultSchema,
  GameplayMatchInputSchema,
  GameplayStatusResultSchema,
  GameplayStatusSchema,
  GetReviewResultSchema,
  HealthSchema,
  IPC,
  ImportReplayInputSchema,
  ImportReplayResultSchema,
  ListReviewsResultSchema,
  OpenFixtureInputSchema,
  OpenReplayInputSchema,
  OpenReplayResultSchema,
  OverlayBoundsSchema,
  OverlayContextResultSchema,
  OverlayLifecycleEventSchema,
  OverlayOpenInputSchema,
  OverlayOpenResultSchema,
  OverlayPrefsSchema,
  OverlaySessionUpdateSchema,
  PickRoflResultSchema,
  PickVodResultSchema,
  ProbeVodInputSchema,
  ProbeVodResultSchema,
  RevealGameplayInputSchema,
  RevealGameplayResultSchema,
  ReviewPresentationSchema,
  ReviewSummarySchema,
  SidecarStatusSchema,
  SyncMapSchema,
  type ErrorResult,
  type ReplayErrorPayload
} from './channels'
import { mediaUrlForPath } from '../media/protocol'
import { logger } from '../logging'
import type { OverlayController } from '../overlay'
import { SidecarRequestError } from '../sidecar/client'
import type { SidecarSupervisor } from '../sidecar/supervisor'
import { SyncAnchorInconsistent, buildManualSync } from '../sync/syncMap'

/** Register IPC handlers. Assumes supervisor.start() will run around the same time. */
export function registerIpcHandlers(
  supervisor: SidecarSupervisor,
  overlay: OverlayController
): void {
  for (const channel of Object.values(IPC)) {
    if (channel !== IPC.sidecarStatusEvent && channel !== IPC.overlayLifecycleEvent) {
      ipcMain.removeHandler(channel)
    }
  }

  ipcMain.handle(IPC.getSidecarStatus, () => {
    return SidecarStatusSchema.parse(supervisor.getStatus())
  })

  ipcMain.handle(IPC.health, async () => {
    const payload = await supervisor.health()
    return HealthSchema.parse(payload)
  })

  ipcMain.handle(IPC.restartSidecar, async () => {
    logger.info('manual sidecar restart requested')
    await supervisor.restart()
    return SidecarStatusSchema.parse(supervisor.getStatus())
  })

  ipcMain.handle(IPC.listReviews, async () => {
    return ListReviewsResultSchema.parse(await listReviews(supervisor))
  })

  ipcMain.handle(IPC.getReview, async (_event, raw: unknown) => {
    const input = z.object({ reviewId: z.string().min(1) }).parse(raw)
    return GetReviewResultSchema.parse(await getReview(supervisor, input.reviewId))
  })

  ipcMain.handle(IPC.openFixtureReview, async (_event, raw: unknown) => {
    const input = OpenFixtureInputSchema.parse(raw)
    return GetReviewResultSchema.parse(await openFixtureReview(supervisor, input))
  })

  ipcMain.handle(IPC.pickVod, async (event) => {
    const win = BrowserWindow.fromWebContents(event.sender)
    const options: Electron.OpenDialogOptions = {
      title: 'Attach a VOD',
      properties: ['openFile'],
      filters: [{ name: 'Video', extensions: ['mp4', 'mkv', 'webm', 'mov', 'avi'] }]
    }
    const picked =
      win === null ? await dialog.showOpenDialog(options) : await dialog.showOpenDialog(win, options)
    const path = picked.canceled ? null : (picked.filePaths[0] ?? null)
    return PickVodResultSchema.parse({ ok: true, path })
  })

  ipcMain.handle(IPC.probeVod, async (_event, raw: unknown) => {
    const input = ProbeVodInputSchema.parse(raw)
    return ProbeVodResultSchema.parse(await probeVod(supervisor, input.path))
  })

  ipcMain.handle(IPC.buildManualSync, async (_event, raw: unknown) => {
    const input = BuildManualSyncInputSchema.parse(raw)
    try {
      const sync = buildManualSync(input.anchors, {
        videoDurationMs: input.videoDurationMs,
        matchId: input.matchId,
        mediaAssetId: input.mediaAssetId,
        matchDurationMs: input.matchDurationMs
      })
      return BuildManualSyncResultSchema.parse({
        ok: true,
        sync_map: SyncMapSchema.parse(sync)
      })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'sync failed'
      const code = error instanceof SyncAnchorInconsistent ? 'SYNC_INVALID' : 'VALIDATION'
      return BuildManualSyncResultSchema.parse({ ok: false, code, message })
    }
  })

  ipcMain.handle(IPC.getDesktopPlatform, () => {
    return DesktopPlatformSchema.parse({
      platform: process.platform,
      nativeReplaySupported: process.platform === 'win32'
    })
  })

  ipcMain.handle(IPC.pickRofl, async (event) => {
    const win = BrowserWindow.fromWebContents(event.sender)
    const options: Electron.OpenDialogOptions = {
      title: 'Import a League replay',
      properties: ['openFile'],
      filters: [{ name: 'League Replay', extensions: ['rofl'] }]
    }
    const picked =
      win === null ? await dialog.showOpenDialog(options) : await dialog.showOpenDialog(win, options)
    const path = picked.canceled ? null : (picked.filePaths[0] ?? null)
    return PickRoflResultSchema.parse({ ok: true, path })
  })

  ipcMain.handle(IPC.importReplay, async (_event, raw: unknown) => {
    const input = ImportReplayInputSchema.parse(raw)
    return ImportReplayResultSchema.parse(await importReplay(supervisor, input.path, input.matchId))
  })

  ipcMain.handle(IPC.getGameplayStatus, async (_event, raw: unknown) => {
    const input = GameplayMatchInputSchema.parse(raw)
    return GameplayStatusResultSchema.parse(await getGameplayStatus(supervisor, input))
  })

  ipcMain.handle(IPC.checkGameplayEnvironment, async () => {
    return GameplayEnvironmentResultSchema.parse(await checkGameplayEnvironment(supervisor))
  })

  ipcMain.handle(IPC.openReplay, async (_event, raw: unknown) => {
    const input = OpenReplayInputSchema.parse(raw)
    return OpenReplayResultSchema.parse(await openReplay(supervisor, input.sourceId, input.matchId))
  })

  ipcMain.handle(IPC.closeReplay, async (_event, raw: unknown) => {
    const input = OpenReplayInputSchema.parse(raw)
    return CloseReplayResultSchema.parse(await closeReplay(supervisor, input.sourceId, input.matchId))
  })

  ipcMain.handle(IPC.revealGameplay, async (_event, raw: unknown) => {
    const input = RevealGameplayInputSchema.parse(raw)
    return RevealGameplayResultSchema.parse(await revealGameplay(supervisor, input))
  })

  ipcMain.handle(IPC.overlayOpen, (_event, raw: unknown) => {
    const input = OverlayOpenInputSchema.parse(raw)
    const result = overlay.open(
      {
        reviewId: input.reviewId,
        matchId: input.matchId,
        sourceId: input.sourceId
      },
      {
        sessionPhase: input.sessionPhase ?? null,
        sessionReachedReady: input.sessionReachedReady ?? true,
        liveGame: input.liveGame ?? false
      }
    )
    return OverlayOpenResultSchema.parse(result)
  })

  ipcMain.handle(IPC.overlayClose, () => {
    overlay.close()
    return { ok: true as const }
  })

  ipcMain.handle(IPC.overlayHide, () => {
    overlay.hide('manual')
    return { ok: true as const }
  })

  ipcMain.handle(IPC.overlayGetPrefs, () => {
    return OverlayPrefsSchema.parse(overlay.getPrefs())
  })

  ipcMain.handle(IPC.overlaySetPrefs, (_event, raw: unknown) => {
    const patch = OverlayPrefsSchema.partial().parse(raw)
    return OverlayPrefsSchema.parse(overlay.setPrefs(patch))
  })

  ipcMain.handle(IPC.overlayGetContext, () => {
    return OverlayContextResultSchema.parse({
      context: overlay.getContext(),
      prefs: overlay.getPrefs()
    })
  })

  ipcMain.handle(IPC.overlaySetBounds, (_event, raw: unknown) => {
    const bounds = OverlayBoundsSchema.parse(raw)
    return OverlayPrefsSchema.parse(overlay.setUserBounds(bounds))
  })

  ipcMain.handle(IPC.overlayUpdateSession, (_event, raw: unknown) => {
    const update = OverlaySessionUpdateSchema.parse(raw)
    overlay.updateSession({
      sessionPhase: update.sessionPhase ?? undefined,
      sessionReachedReady: update.sessionReachedReady,
      liveGame: update.liveGame
    })
    return { ok: true as const }
  })

  ipcMain.handle(IPC.overlayGetLifecycle, () => {
    return OverlayLifecycleEventSchema.parse(overlay.getLifecycleSnapshot())
  })

  supervisor.on('status', (status) => {
    const parsed = SidecarStatusSchema.parse(status)
    for (const win of BrowserWindow.getAllWindows()) {
      win.webContents.send(IPC.sidecarStatusEvent, parsed)
    }
  })
}

async function listReviews(supervisor: SidecarSupervisor) {
  try {
    const payload = await supervisor.request('/reviews')
    const parsed = (payload as { reviews?: unknown }).reviews
    const reviews = ReviewSummarySchema.array().parse(parsed ?? [])
    return { ok: true as const, reviews }
  } catch (error) {
    return fail(error)
  }
}

async function getReview(supervisor: SidecarSupervisor, reviewId: string) {
  try {
    const payload = await supervisor.request(`/reviews/${encodeURIComponent(reviewId)}`)
    return { ok: true as const, review: ReviewPresentationSchema.parse(payload) }
  } catch (error) {
    return fail(error)
  }
}

async function openFixtureReview(
  supervisor: SidecarSupervisor,
  input: { fixtureId: string; participantId: number; rank?: string }
) {
  try {
    const payload = await supervisor.request(
      '/reviews/from-fixture',
      {
        method: 'POST',
        body: JSON.stringify({
          fixture_id: input.fixtureId,
          participant_id: input.participantId,
          rank: input.rank ?? 'UNRANKED'
        })
      },
      180_000
    )
    return { ok: true as const, review: ReviewPresentationSchema.parse(payload) }
  } catch (error) {
    return fail(error)
  }
}

async function probeVod(supervisor: SidecarSupervisor, path: string) {
  try {
    const payload = await supervisor.request('/media/probe', {
      method: 'POST',
      body: JSON.stringify({ path })
    })
    const body = payload as {
      ok?: boolean
      playable?: boolean
      handling?: string
      ingest_errors?: string[]
      message?: string | null
      probe?: unknown
    }
    if (body.playable !== true || body.probe === undefined) {
      return {
        ok: false as const,
        code: body.playable === false ? ('UNSUPPORTED_CODEC' as const) : ('INVALID_VOD' as const),
        message: body.message ?? 'Video cannot be played in RiftLens.'
      }
    }
    return {
      ok: true as const,
      playable: true,
      handling: String(body.handling ?? ''),
      ingest_errors: body.ingest_errors ?? [],
      message: body.message ?? null,
      probe: body.probe,
      mediaUrl: mediaUrlForPath(path)
    }
  } catch (error) {
    return fail(error, 'INVALID_VOD')
  }
}

async function importReplay(supervisor: SidecarSupervisor, path: string, matchId: string) {
  try {
    const payload = (await supervisor.request('/gameplay/import', {
      method: 'POST',
      body: JSON.stringify({ path, match_id: matchId })
    })) as Record<string, unknown>
    if (payload['ok'] === true && typeof payload['source_id'] === 'string') {
      return {
        ok: true as const,
        source_id: payload['source_id'],
        match_id: String(payload['match_id'] ?? matchId),
        identity: payload['identity'] ?? null,
        warnings: asErrors(payload['warnings']),
        status: GameplayStatusSchema.parse(payload['status'])
      }
    }
    const typed = asError(payload['error'])
    return {
      ok: false as const,
      code: typed?.code ?? 'UNKNOWN',
      message: typed?.message ?? 'Replay import failed.',
      suggested_action: typed?.suggested_action ?? 'choose_file',
      error: typed
    }
  } catch (error) {
    return sidecarReplayFail(error)
  }
}

async function getGameplayStatus(
  supervisor: SidecarSupervisor,
  input: { matchId: string; sourceId?: string | null }
) {
  try {
    const params = new URLSearchParams({ match_id: input.matchId })
    if (input.sourceId) {
      params.set('source_id', input.sourceId)
    }
    const payload = await supervisor.request(`/gameplay/status?${params.toString()}`)
    return { ok: true as const, status: GameplayStatusSchema.parse(payload) }
  } catch (error) {
    return fail(error)
  }
}

async function checkGameplayEnvironment(supervisor: SidecarSupervisor) {
  try {
    const payload = (await supervisor.request('/gameplay/environment')) as Record<string, unknown>
    return {
      ok: true as const,
      native_replay_supported: Boolean(payload['native_replay_supported']),
      install_found: Boolean(payload['install_found']),
      replay_api_documented: Boolean(payload['replay_api_documented']),
      live_game: Boolean(payload['live_game']),
      error: asError(payload['error']),
      warnings: asErrors(payload['warnings'])
    }
  } catch (error) {
    return fail(error)
  }
}

async function openReplay(supervisor: SidecarSupervisor, sourceId: string, matchId: string) {
  try {
    const payload = (await supervisor.request(
      '/gameplay/open',
      {
        method: 'POST',
        body: JSON.stringify({ source_id: sourceId, match_id: matchId })
      },
      180_000
    )) as Record<string, unknown>
    const status =
      payload['status'] === undefined || payload['status'] === null
        ? null
        : GameplayStatusSchema.parse(payload['status'])
    if (payload['ok'] === true && payload['session_reached_ready'] === true) {
      return {
        ok: true as const,
        session_phase: String(payload['session_phase'] ?? 'READY'),
        session_reached_ready: true as const,
        status: status ?? GameplayStatusSchema.parse(payload['status'])
      }
    }
    const typed = asError(payload['error'])
    return {
      ok: false as const,
      code: typed?.code ?? 'SOURCE_NOT_READY',
      message: typed?.message ?? 'Replay is not ready yet.',
      suggested_action: typed?.suggested_action ?? 'retry',
      session_phase: payload['session_phase'] == null ? null : String(payload['session_phase']),
      session_reached_ready: payload['session_reached_ready'] === true,
      error: typed,
      status
    }
  } catch (error) {
    const failed = sidecarReplayFail(error)
    return {
      ...failed,
      session_phase: null,
      session_reached_ready: false,
      status: null
    }
  }
}

async function closeReplay(supervisor: SidecarSupervisor, sourceId: string, matchId: string) {
  try {
    const payload = (await supervisor.request('/gameplay/close', {
      method: 'POST',
      body: JSON.stringify({ source_id: sourceId, match_id: matchId })
    })) as Record<string, unknown>
    return { ok: true as const, status: GameplayStatusSchema.parse(payload['status']) }
  } catch (error) {
    return fail(error)
  }
}

async function revealGameplay(
  supervisor: SidecarSupervisor,
  input: { sourceId: string; matchId: string; gameTMs: number; leadInMs?: number }
) {
  try {
    const payload = (await supervisor.request('/gameplay/reveal', {
      method: 'POST',
      body: JSON.stringify({
        source_id: input.sourceId,
        match_id: input.matchId,
        game_t_ms: input.gameTMs,
        lead_in_ms: input.leadInMs ?? 8_000
      })
    })) as Record<string, unknown>
    if (payload['ok'] === true) {
      return {
        ok: true as const,
        source_id: String(payload['source_id'] ?? input.sourceId),
        target_game_ms: Number(payload['target_game_ms']),
        lead_in_ms: Number(payload['lead_in_ms'] ?? 8_000),
        landed_source_ms:
          payload['landed_source_ms'] == null ? null : Number(payload['landed_source_ms']),
        clock_verified: payload['clock_verified'] === true,
        clock_confidence:
          payload['clock_confidence'] == null ? null : String(payload['clock_confidence']),
        playback: payload['playback'] ?? null,
        warnings: asErrors(payload['warnings']),
        status: GameplayStatusSchema.parse(payload['status'])
      }
    }
    const typed = asError(payload['error'])
    return {
      ok: false as const,
      code: typed?.code ?? 'SEEK_FAILED',
      message: typed?.message ?? 'Replay seek failed.',
      suggested_action: typed?.suggested_action ?? 'retry',
      error: typed,
      status:
        payload['status'] === undefined || payload['status'] === null
          ? null
          : GameplayStatusSchema.parse(payload['status'])
    }
  } catch (error) {
    return { ...sidecarReplayFail(error), status: null }
  }
}

function asError(value: unknown): ReplayErrorPayload | null {
  if (typeof value !== 'object' || value === null) {
    return null
  }
  const record = value as Record<string, unknown>
  if (typeof record['code'] !== 'string' || typeof record['message'] !== 'string') {
    return null
  }
  return {
    code: record['code'],
    message: record['message'],
    suggested_action: typeof record['suggested_action'] === 'string' ? record['suggested_action'] : null,
    recoverable: record['recoverable'] === true,
    severity: typeof record['severity'] === 'string' ? record['severity'] : 'fatal'
  }
}

function asErrors(value: unknown): ReplayErrorPayload[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .map((item) => asError(item))
    .filter((item): item is ReplayErrorPayload => item !== null)
}

function sidecarReplayFail(error: unknown): {
  ok: false
  code: string
  message: string
  suggested_action: string
  error: ReplayErrorPayload | null
} {
  const fallback = fail(error)
  return {
    ok: false,
    code: fallback.code,
    message: fallback.message,
    suggested_action: 'retry',
    error: null
  }
}

function fail(error: unknown, fallback: ErrorResult['code'] = 'UNKNOWN'): ErrorResult {
  if (error instanceof SidecarRequestError && error.status === 404) {
    return ErrorResultSchema.parse({ ok: false, code: 'NOT_FOUND', message: error.message })
  }
  if (error instanceof SidecarRequestError && error.status === 400) {
    return ErrorResultSchema.parse({
      ok: false,
      code: fallback === 'UNKNOWN' ? 'VALIDATION' : fallback,
      message: error.message
    })
  }
  const message = error instanceof Error ? error.message : 'Unexpected error'
  const code = message.includes('not ready') ? 'SIDECAR_UNAVAILABLE' : fallback
  return ErrorResultSchema.parse({ ok: false, code, message })
}
