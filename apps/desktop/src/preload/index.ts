import { contextBridge, ipcRenderer } from 'electron'
import {
  AuthSessionSchema,
  BuildManualSyncInputSchema,
  BuildManualSyncResultSchema,
  GetReviewResultSchema,
  HealthSchema,
  IPC,
  ListReviewsResultSchema,
  OpenFixtureInputSchema,
  PickVodResultSchema,
  ProbeVodInputSchema,
  ProbeVodResultSchema,
  SidecarStatusSchema,
  SignInResultSchema,
  type AuthSession,
  type BuildManualSyncResult,
  type GetReviewResult,
  type HealthPayload,
  type ListReviewsResult,
  type OpenFixtureInput,
  type PickVodResult,
  type ProbeVodResult,
  type SidecarStatus,
  type SignInResult
} from '../main/ipc/channels'

const rift = {
  getSidecarStatus(): Promise<SidecarStatus> {
    return ipcRenderer.invoke(IPC.getSidecarStatus).then((value) => SidecarStatusSchema.parse(value))
  },
  onSidecarStatus(cb: (status: SidecarStatus) => void): () => void {
    const listener = (_event: Electron.IpcRendererEvent, value: unknown): void => {
      cb(SidecarStatusSchema.parse(value))
    }
    ipcRenderer.on(IPC.sidecarStatusEvent, listener)
    return () => {
      ipcRenderer.removeListener(IPC.sidecarStatusEvent, listener)
    }
  },
  health(): Promise<HealthPayload> {
    return ipcRenderer.invoke(IPC.health).then((value) => HealthSchema.parse(value))
  },
  restartSidecar(): Promise<SidecarStatus> {
    return ipcRenderer.invoke(IPC.restartSidecar).then((value) => SidecarStatusSchema.parse(value))
  },
  listReviews(): Promise<ListReviewsResult> {
    return ipcRenderer.invoke(IPC.listReviews).then((value) => ListReviewsResultSchema.parse(value))
  },
  getReview(reviewId: string): Promise<GetReviewResult> {
    return ipcRenderer
      .invoke(IPC.getReview, { reviewId })
      .then((value) => GetReviewResultSchema.parse(value))
  },
  openFixtureReview(input: OpenFixtureInput): Promise<GetReviewResult> {
    return ipcRenderer
      .invoke(IPC.openFixtureReview, OpenFixtureInputSchema.parse(input))
      .then((value) => GetReviewResultSchema.parse(value))
  },
  pickVod(): Promise<PickVodResult> {
    return ipcRenderer.invoke(IPC.pickVod).then((value) => PickVodResultSchema.parse(value))
  },
  probeVod(path: string): Promise<ProbeVodResult> {
    return ipcRenderer
      .invoke(IPC.probeVod, ProbeVodInputSchema.parse({ path }))
      .then((value) => ProbeVodResultSchema.parse(value))
  },
  buildManualSync(input: {
    matchId: string
    videoDurationMs: number
    matchDurationMs?: number | null
    mediaAssetId?: string
    anchors: { t_video_ms: number; t_game_ms: number }[]
  }): Promise<BuildManualSyncResult> {
    return ipcRenderer
      .invoke(IPC.buildManualSync, BuildManualSyncInputSchema.parse(input))
      .then((value) => BuildManualSyncResultSchema.parse(value))
  },
  getAuthSession(): Promise<AuthSession> {
    return ipcRenderer.invoke(IPC.getAuthSession).then((value) => AuthSessionSchema.parse(value))
  },
  signIn(): Promise<SignInResult> {
    return ipcRenderer.invoke(IPC.signIn).then((value) => SignInResultSchema.parse(value))
  },
  signOut(): Promise<AuthSession> {
    return ipcRenderer.invoke(IPC.signOut).then((value) => AuthSessionSchema.parse(value))
  },
  onAuthSession(cb: (session: AuthSession) => void): () => void {
    const listener = (_event: Electron.IpcRendererEvent, value: unknown): void => {
      cb(AuthSessionSchema.parse(value))
    }
    ipcRenderer.on(IPC.authSessionEvent, listener)
    return () => {
      ipcRenderer.removeListener(IPC.authSessionEvent, listener)
    }
  }
}

contextBridge.exposeInMainWorld('rift', rift)
