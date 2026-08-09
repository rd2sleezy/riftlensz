import { contextBridge, ipcRenderer } from 'electron'
import {
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
  type BuildManualSyncResult,
  type GetReviewResult,
  type HealthPayload,
  type ListReviewsResult,
  type OpenFixtureInput,
  type PickVodResult,
  type ProbeVodResult,
  type SidecarStatus
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
  }
}

contextBridge.exposeInMainWorld('rift', rift)
