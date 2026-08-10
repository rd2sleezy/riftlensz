import { BrowserWindow, dialog, ipcMain } from 'electron'
import { z } from 'zod'
import {
  AuthSessionSchema,
  BuildManualSyncInputSchema,
  BuildManualSyncResultSchema,
  ErrorResultSchema,
  GetReviewResultSchema,
  HealthSchema,
  IPC,
  ListReviewsResultSchema,
  OpenFixtureInputSchema,
  PickVodResultSchema,
  ProbeVodInputSchema,
  ProbeVodResultSchema,
  ReviewPresentationSchema,
  ReviewSummarySchema,
  SidecarStatusSchema,
  SignInResultSchema,
  SyncMapSchema,
  type ErrorResult
} from './channels'
import { mediaUrlForPath } from '../media/protocol'
import { logger } from '../logging'
import { SidecarRequestError } from '../sidecar/client'
import type { SidecarSupervisor } from '../sidecar/supervisor'
import { SyncAnchorInconsistent, buildManualSync } from '../sync/syncMap'
import { PLACEHOLDER_FIXTURE_B_REVIEW_ID, buildPlaceholderFixtureBReview } from '../fixtures/placeholderReview'
import type { AuthService } from '../auth/authService'

/** Register IPC handlers. Assumes supervisor.start() and authService.start() will run around the same time. */
export function registerIpcHandlers(supervisor: SidecarSupervisor, authService: AuthService): void {
  for (const channel of Object.values(IPC)) {
    if (channel !== IPC.sidecarStatusEvent && channel !== IPC.authSessionEvent) {
      ipcMain.removeHandler(channel)
    }
  }

  ipcMain.handle(IPC.getAuthSession, () => {
    return AuthSessionSchema.parse(authService.getSession())
  })

  ipcMain.handle(IPC.signIn, async () => {
    return SignInResultSchema.parse(await authService.signIn())
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
