import { BrowserWindow, dialog, ipcMain } from 'electron'
import { z } from 'zod'
import {
  AnalyzeJobInputSchema,
  AnalyzeJobResultSchema,
  BuildManualSyncInputSchema,
  BuildManualSyncResultSchema,
  CloseReplayResultSchema,
  DesktopPlatformSchema,
  EnableReplayApiInputSchema,
  EnableReplayApiResultSchema,
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
  IngestMatchInputSchema,
  IngestMatchResultSchema,
  ListReviewsResultSchema,
  MatchParticipantsInputSchema,
  MatchParticipantsResultSchema,
  OpenFixtureInputSchema,
  OpenRealMatchReviewInputSchema,
  OpenReplayInputSchema,
  OpenReplayResultSchema,
  OverlayBoundsSchema,
  OverlayContextResultSchema,
  OverlayLifecycleEventSchema,
  OverlayOpenInputSchema,
  OverlayOpenResultSchema,
  OverlayPrefsSchema,
  OverlaySessionUpdateSchema,
  OverlayUserIntentSchema,
  PickRoflResultSchema,
  PickVodResultSchema,
  ProbeVodInputSchema,
  ProbeVodResultSchema,
  RevealGameplayInputSchema,
  RevealGameplayResultSchema,
  ReviewPresentationSchema,
  ReviewSummarySchema,
  RunAutoSyncInputSchema,
  RunAutoSyncResultSchema,
  SidecarStatusSchema,
  SignInResultSchema,
  SignInWithApiKeyInputSchema,
  SyncMapSchema,
  AuthSessionSchema,
  type ErrorResult,
  type ReplayErrorPayload
} from './channels'
import { mediaUrlForPath } from '../media/protocol'
import { logger } from '../logging'
import type { OverlayController } from '../overlay'
import { overlayCompanionSupported } from '../overlay/platform'
import type { AuthService } from '../auth/authService'
import { PLACEHOLDER_FIXTURE_B_REVIEW_ID, buildPlaceholderFixtureBReview } from '../fixtures/placeholderReview'
import { SidecarRequestError } from '../sidecar/client'
import type { SidecarSupervisor } from '../sidecar/supervisor'
import { SyncAnchorInconsistent, buildManualSync } from '../sync/syncMap'

/** Register IPC handlers. Assumes supervisor.start() will run around the same time. */
export function registerIpcHandlers(
  supervisor: SidecarSupervisor,
  overlay: OverlayController,
  authService: AuthService
): void {
  for (const channel of Object.values(IPC)) {
    if (
      channel !== IPC.sidecarStatusEvent &&
      channel !== IPC.overlayLifecycleEvent &&
      channel !== IPC.authSessionEvent
    ) {
      ipcMain.removeHandler(channel)
    }
  }

  ipcMain.handle(IPC.getAuthSession, () => {
    return AuthSessionSchema.parse(authService.getSession())
  })

  ipcMain.handle(IPC.signIn, async () => {
    return SignInResultSchema.parse(await authService.signIn())
  })

  ipcMain.handle(IPC.signInWithApiKey, async (_event, raw: unknown) => {
    const input = SignInWithApiKeyInputSchema.parse(raw)
    return SignInResultSchema.parse(
      await authService.signInWithApiKey(input.apiKey, input.gameName, input.tagLine, input.region)
    )
  })

  ipcMain.handle(IPC.signOut, () => {
    return AuthSessionSchema.parse(authService.signOut())
  })

  authService.on('session', (session) => {
    const parsed = AuthSessionSchema.parse(session)
    for (const win of BrowserWindow.getAllWindows()) {
      win.webContents.send(IPC.authSessionEvent, parsed)
    }
  })

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

  ipcMain.handle(IPC.openRealMatchReview, async (_event, raw: unknown) => {
    const input = OpenRealMatchReviewInputSchema.parse(raw)
    return GetReviewResultSchema.parse(
      await openRealMatchReview(supervisor, authService, input)
    )
  })

  ipcMain.handle(IPC.startAnalyzeJob, async (_event, raw: unknown) => {
    const input = AnalyzeJobInputSchema.parse(raw)
    return AnalyzeJobResultSchema.parse(await startAnalyzeJob(supervisor, authService, input))
  })

  ipcMain.handle(IPC.getAnalyzeJob, async (_event, raw: unknown) => {
    const input = z.object({ jobId: z.string().min(1) }).parse(raw)
    return AnalyzeJobResultSchema.parse(await getAnalyzeJob(supervisor, input.jobId))
  })

  ipcMain.handle(IPC.cancelAnalyzeJob, async (_event, raw: unknown) => {
    const input = z.object({ jobId: z.string().min(1) }).parse(raw)
    return AnalyzeJobResultSchema.parse(await cancelAnalyzeJob(supervisor, input.jobId))
  })

  ipcMain.handle(IPC.listMatchParticipants, async (_event, raw: unknown) => {
    const input = MatchParticipantsInputSchema.parse(raw)
    return MatchParticipantsResultSchema.parse(
      await listMatchParticipants(supervisor, authService, input.matchId)
    )
  })

  ipcMain.handle(IPC.ingestMatch, async (_event, raw: unknown) => {
    const input = IngestMatchInputSchema.parse(raw)
    return IngestMatchResultSchema.parse(await ingestMatch(supervisor, authService, input.matchId))
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

  ipcMain.handle(IPC.runAutoSync, async (_event, raw: unknown) => {
    const input = RunAutoSyncInputSchema.parse(raw)
    return RunAutoSyncResultSchema.parse(await runAutoSync(supervisor, input))
  })

  ipcMain.handle(IPC.getDesktopPlatform, () => {
    return DesktopPlatformSchema.parse({
      platform: process.platform,
      nativeReplaySupported: process.platform === 'win32' || process.platform === 'darwin',
      overlayCompanionSupported: overlayCompanionSupported(),
      e2eMode: process.env['RIFTLENS_E2E'] === '1'
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

  ipcMain.handle(IPC.enableReplayApi, async (_event, raw: unknown) => {
    const input = EnableReplayApiInputSchema.parse(raw)
    return EnableReplayApiResultSchema.parse(await enableReplayApi(supervisor, input.consent))
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
    // Minimize to launcher — never a hover/idle hide, never closes the replay.
    return OverlayLifecycleEventSchema.parse(overlay.minimize())
  })

  ipcMain.handle(IPC.overlaySetPresentation, (_event, raw: unknown) => {
    const intent = OverlayUserIntentSchema.parse(raw)
    return OverlayLifecycleEventSchema.parse(overlay.setPresentation(intent))
  })

  ipcMain.handle(IPC.overlayRecheckDisplay, () => {
    return OverlayLifecycleEventSchema.parse(overlay.recheckDisplay())
  })

  ipcMain.handle(IPC.overlayAllowInteractionFocus, () => {
    return overlay.allowInteractionFocus()
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
  if (reviewId === PLACEHOLDER_FIXTURE_B_REVIEW_ID) {
    return { ok: true as const, review: buildPlaceholderFixtureBReview(5, 'UNRANKED') }
  }
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
    if (input.fixtureId === 'NA1_fixture_b') {
      logger.warn({ error: fail(error) }, 'sidecar unavailable for fixture B, serving placeholder review')
      return {
        ok: true as const,
        review: buildPlaceholderFixtureBReview(input.participantId, input.rank ?? 'UNRANKED')
      }
    }
    return fail(error)
  }
}

async function startAnalyzeJob(
  supervisor: SidecarSupervisor,
  authService: AuthService,
  input: { matchId: string; participantId: number; rank?: string; mediaAssetId?: string }
) {
  const apiKey = authService.getApiKeyForMain()
  try {
    const created = await supervisor.request(
      '/jobs/analyze',
      {
        method: 'POST',
        body: JSON.stringify({
          match_id: input.matchId,
          participant_id: input.participantId,
          rank: input.rank ?? 'UNRANKED',
          media_asset_id: input.mediaAssetId,
          api_key: apiKey
        })
      },
      30_000
    )
    const jobId = (created as { job_id: string }).job_id
    return await getAnalyzeJob(supervisor, jobId)
  } catch (error) {
    return fail(error)
  }
}

async function getAnalyzeJob(supervisor: SidecarSupervisor, jobId: string) {
  try {
    const payload = await supervisor.request(`/jobs/${jobId}`)
    return { ok: true as const, job: payload }
  } catch (error) {
    return fail(error)
  }
}

async function cancelAnalyzeJob(supervisor: SidecarSupervisor, jobId: string) {
  try {
    const payload = await supervisor.request(`/jobs/${jobId}`, { method: 'DELETE' })
    return { ok: true as const, job: payload }
  } catch (error) {
    return fail(error)
  }
}

async function openRealMatchReview(
  supervisor: SidecarSupervisor,
  authService: AuthService,
  input: { matchId: string; participantId: number; rank?: string }
) {
  const apiKey = authService.getApiKeyForMain()
  try {
    const payload = await supervisor.request(
      '/reviews/from-match',
      {
        method: 'POST',
        body: JSON.stringify({
          match_id: input.matchId,
          participant_id: input.participantId,
          rank: input.rank ?? 'UNRANKED',
          api_key: apiKey
        })
      },
      180_000
    )
    return { ok: true as const, review: ReviewPresentationSchema.parse(payload) }
  } catch (error) {
    if (apiKey === null) {
      return ErrorResultSchema.parse({
        ok: false,
        code: 'RIOT_CREDENTIAL_MISSING',
        message:
          'Riot access is required to download this match.'
      })
    }
    return fail(error)
  }
}

async function listMatchParticipants(
  supervisor: SidecarSupervisor,
  authService: AuthService,
  matchId: string
) {
  const apiKey = authService.getApiKeyForMain()
  try {
    const payload = (await supervisor.request(
      '/matches/participants',
      {
        method: 'POST',
        body: JSON.stringify({ match_id: matchId, api_key: apiKey })
      },
      180_000
    )) as Record<string, unknown>
    if (payload['ok'] === true && Array.isArray(payload['participants'])) {
      return {
        ok: true as const,
        match_id: String(payload['match_id'] ?? matchId),
        participants: payload['participants']
      }
    }
    const typed = asError(payload['error'])
    if (typed?.code === 'RIOT_CREDENTIAL_MISSING' || apiKey === null) {
      return {
        ok: false as const,
        code: 'RIOT_CREDENTIAL_MISSING',
        message:
          typed?.message ??
          'Riot access is required to download this match.'
      }
    }
    return {
      ok: false as const,
      code: typed?.code ?? 'UNKNOWN',
      message: typed?.message ?? 'Could not list match participants.'
    }
  } catch (error) {
    if (apiKey === null) {
      return {
        ok: false as const,
        code: 'RIOT_CREDENTIAL_MISSING',
        message:
          'Riot access is required to download this match.'
      }
    }
    const fallback = fail(error)
    return { ok: false as const, code: fallback.code, message: fallback.message }
  }
}

async function ingestMatch(
  supervisor: SidecarSupervisor,
  authService: AuthService,
  matchId: string
) {
  const apiKey = authService.getApiKeyForMain()
  try {
    const payload = (await supervisor.request(
      '/matches/ingest',
      {
        method: 'POST',
        body: JSON.stringify({ match_id: matchId, api_key: apiKey })
      },
      180_000
    )) as Record<string, unknown>
    if (payload['ok'] === true) {
      return {
        ok: true as const,
        match_id: String(payload['match_id'] ?? matchId),
        fetched: Boolean(payload['fetched'])
      }
    }
    const typed = asError(payload['error'])
    return {
      ok: false as const,
      code: typed?.code ?? (apiKey === null ? 'RIOT_CREDENTIAL_MISSING' : 'UNKNOWN'),
      message:
        typed?.message ??
        (apiKey === null
          ? 'Riot access is required to download this match.'
          : 'Match ingest failed.')
    }
  } catch (error) {
    if (apiKey === null) {
      return {
        ok: false as const,
        code: 'RIOT_CREDENTIAL_MISSING',
        message:
          'Riot access is required to download this match.'
      }
    }
    const fallback = fail(error)
    return { ok: false as const, code: fallback.code, message: fallback.message }
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

const AUTO_SYNC_CODES = new Set([
  'INSUFFICIENT_READINGS',
  'NO_STABLE_MODEL',
  'MULTIPLE_GAMES',
  'INCONSISTENT_OCR',
  'INSUFFICIENT_COVERAGE',
  'VERIFICATION_FAILED',
  'UNSUPPORTED_SOURCE',
  'MEDIA_UNAVAILABLE',
  'VALIDATION',
  'SYNC_INVALID',
  'UNKNOWN'
])

async function runAutoSync(
  supervisor: SidecarSupervisor,
  input: {
    matchId: string
    videoPath: string
    videoDurationMs: number
    matchDurationMs?: number | null
    contentHash?: string
    force?: boolean
  }
) {
  try {
    const payload = (await supervisor.request(
      '/sync/auto',
      {
        method: 'POST',
        body: JSON.stringify({
          match_id: input.matchId,
          video_path: input.videoPath,
          video_duration_ms: input.videoDurationMs,
          match_duration_ms: input.matchDurationMs ?? null,
          content_hash: input.contentHash ?? null,
          force: input.force === true
        })
      },
      600_000
    )) as Record<string, unknown>
    if (payload['ok'] === true && payload['sync_map'] !== undefined) {
      return {
        ok: true as const,
        sync_map: SyncMapSchema.parse(payload['sync_map']),
        quality: String(payload['quality'] ?? 'DEGRADED') as
          | 'EXCELLENT'
          | 'GOOD'
          | 'DEGRADED'
          | 'FAILED',
        cached: payload['cached'] === true,
        id: typeof payload['id'] === 'string' ? payload['id'] : null
      }
    }
    const codeRaw = typeof payload['code'] === 'string' ? payload['code'] : 'UNKNOWN'
    const code = AUTO_SYNC_CODES.has(codeRaw) ? codeRaw : 'UNKNOWN'
    const boundaries = payload['boundaries_video_ms']
    return {
      ok: false as const,
      code: code as ErrorResult['code'],
      message: typeof payload['message'] === 'string' ? payload['message'] : 'Automatic sync failed.',
      boundaries_video_ms: Array.isArray(boundaries)
        ? boundaries.filter((item): item is number => typeof item === 'number')
        : undefined
    }
  } catch (error) {
    return fail(error, 'UNKNOWN')
  }
}

async function importReplay(
  supervisor: SidecarSupervisor,
  path: string,
  matchId: string | null | undefined
) {
  try {
    const payload = (await supervisor.request('/gameplay/import', {
      method: 'POST',
      body: JSON.stringify({ path, match_id: matchId ?? null })
    })) as Record<string, unknown>
    if (payload['ok'] === true && typeof payload['source_id'] === 'string') {
      return {
        ok: true as const,
        source_id: payload['source_id'],
        match_id: String(payload['match_id'] ?? matchId ?? ''),
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
      match_id: typeof payload['match_id'] === 'string' ? payload['match_id'] : null,
      identity: payload['identity'] ?? null,
      error: typed
    }
  } catch (error) {
    return {
      ...sidecarReplayFail(error),
      match_id: null,
      identity: null
    }
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

async function enableReplayApi(supervisor: SidecarSupervisor, consent: true) {
  try {
    const payload = (await supervisor.request('/gameplay/enable-replay-api', {
      method: 'POST',
      body: JSON.stringify({ consent })
    })) as Record<string, unknown>
    return {
      ok: Boolean(payload['ok']),
      changed: Boolean(payload['changed']),
      requires_restart: Boolean(payload['requires_restart'] ?? true),
      backup_path: typeof payload['backup_path'] === 'string' ? payload['backup_path'] : null,
      path: typeof payload['path'] === 'string' ? payload['path'] : null,
      error: asError(payload['error']),
      details: payload['details']
    }
  } catch (error) {
    const failed = fail(error)
    return {
      ok: false,
      changed: false,
      requires_restart: false,
      backup_path: null,
      path: null,
      error: {
        code: failed.code,
        message: failed.message,
        suggested_action: null,
        recoverable: true,
        details: {}
      }
    }
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
    severity: typeof record['severity'] === 'string' ? record['severity'] : 'fatal',
    details:
      typeof record['details'] === 'object' && record['details'] !== null
        ? (record['details'] as Record<string, unknown>)
        : {}
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
