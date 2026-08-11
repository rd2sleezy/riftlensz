import { contextBridge, ipcRenderer } from 'electron'
import {
  BuildManualSyncInputSchema,
  BuildManualSyncResultSchema,
  CloseReplayResultSchema,
  DesktopPlatformSchema,
  GameplayEnvironmentResultSchema,
  GameplayMatchInputSchema,
  GameplayStatusResultSchema,
  GetReviewResultSchema,
  HealthSchema,
  IPC,
  ImportReplayInputSchema,
  ImportReplayResultSchema,
  ListReviewsResultSchema,
  OpenFixtureInputSchema,
  OpenReplayInputSchema,
  OpenReplayResultSchema,
  PickRoflResultSchema,
  PickVodResultSchema,
  ProbeVodInputSchema,
  ProbeVodResultSchema,
  RevealGameplayInputSchema,
  RevealGameplayResultSchema,
  OverlayBoundsSchema,
  OverlayContextResultSchema,
  OverlayLifecycleEventSchema,
  OverlayOpenInputSchema,
  OverlayOpenResultSchema,
  OverlayPrefsSchema,
  OverlaySessionUpdateSchema,
  SidecarStatusSchema,
  type BuildManualSyncResult,
  type CloseReplayResult,
  type DesktopPlatform,
  type GameplayEnvironmentResult,
  type GameplayStatusResult,
  type GetReviewResult,
  type HealthPayload,
  type ImportReplayResult,
  type ListReviewsResult,
  type OpenFixtureInput,
  type OpenReplayResult,
  type OverlayContextResult,
  type OverlayLifecycleEventPayload,
  type OverlayOpenResult,
  type OverlayPrefsPayload,
  type PickRoflResult,
  type PickVodResult,
  type ProbeVodResult,
  type RevealGameplayResult,
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
  },
  getDesktopPlatform(): Promise<DesktopPlatform> {
    return ipcRenderer
      .invoke(IPC.getDesktopPlatform)
      .then((value) => DesktopPlatformSchema.parse(value))
  },
  pickRofl(): Promise<PickRoflResult> {
    return ipcRenderer.invoke(IPC.pickRofl).then((value) => PickRoflResultSchema.parse(value))
  },
  importReplay(path: string, matchId: string): Promise<ImportReplayResult> {
    return ipcRenderer
      .invoke(IPC.importReplay, ImportReplayInputSchema.parse({ path, matchId }))
      .then((value) => ImportReplayResultSchema.parse(value))
  },
  getGameplayStatus(matchId: string, sourceId?: string | null): Promise<GameplayStatusResult> {
    return ipcRenderer
      .invoke(IPC.getGameplayStatus, GameplayMatchInputSchema.parse({ matchId, sourceId }))
      .then((value) => GameplayStatusResultSchema.parse(value))
  },
  checkGameplayEnvironment(): Promise<GameplayEnvironmentResult> {
    return ipcRenderer
      .invoke(IPC.checkGameplayEnvironment)
      .then((value) => GameplayEnvironmentResultSchema.parse(value))
  },
  openReplay(sourceId: string, matchId: string): Promise<OpenReplayResult> {
    return ipcRenderer
      .invoke(IPC.openReplay, OpenReplayInputSchema.parse({ sourceId, matchId }))
      .then((value) => OpenReplayResultSchema.parse(value))
  },
  closeReplay(sourceId: string, matchId: string): Promise<CloseReplayResult> {
    return ipcRenderer
      .invoke(IPC.closeReplay, OpenReplayInputSchema.parse({ sourceId, matchId }))
      .then((value) => CloseReplayResultSchema.parse(value))
  },
  revealGameplay(input: {
    sourceId: string
    matchId: string
    gameTMs: number
    leadInMs?: number
  }): Promise<RevealGameplayResult> {
    return ipcRenderer
      .invoke(IPC.revealGameplay, RevealGameplayInputSchema.parse(input))
      .then((value) => RevealGameplayResultSchema.parse(value))
  },
  overlayOpen(input: {
    reviewId: string
    matchId: string
    sourceId: string
    sessionPhase?: string | null
    sessionReachedReady?: boolean
    liveGame?: boolean
  }): Promise<OverlayOpenResult> {
    return ipcRenderer
      .invoke(IPC.overlayOpen, OverlayOpenInputSchema.parse(input))
      .then((value) => OverlayOpenResultSchema.parse(value))
  },
  overlayClose(): Promise<{ ok: true }> {
    return ipcRenderer.invoke(IPC.overlayClose)
  },
  overlayHide(): Promise<{ ok: true }> {
    return ipcRenderer.invoke(IPC.overlayHide)
  },
  overlayGetPrefs(): Promise<OverlayPrefsPayload> {
    return ipcRenderer
      .invoke(IPC.overlayGetPrefs)
      .then((value) => OverlayPrefsSchema.parse(value))
  },
  overlaySetPrefs(patch: Partial<OverlayPrefsPayload>): Promise<OverlayPrefsPayload> {
    return ipcRenderer
      .invoke(IPC.overlaySetPrefs, OverlayPrefsSchema.partial().parse(patch))
      .then((value) => OverlayPrefsSchema.parse(value))
  },
  overlayGetContext(): Promise<OverlayContextResult> {
    return ipcRenderer
      .invoke(IPC.overlayGetContext)
      .then((value) => OverlayContextResultSchema.parse(value))
  },
  overlaySetBounds(bounds: {
    x: number
    y: number
    width: number
    height: number
  }): Promise<OverlayPrefsPayload> {
    return ipcRenderer
      .invoke(IPC.overlaySetBounds, OverlayBoundsSchema.parse(bounds))
      .then((value) => OverlayPrefsSchema.parse(value))
  },
  overlayUpdateSession(update: {
    sessionPhase?: string | null
    sessionReachedReady?: boolean
    liveGame?: boolean
  }): Promise<{ ok: true }> {
    return ipcRenderer.invoke(
      IPC.overlayUpdateSession,
      OverlaySessionUpdateSchema.parse(update)
    )
  },
  overlayGetLifecycle(): Promise<OverlayLifecycleEventPayload> {
    return ipcRenderer
      .invoke(IPC.overlayGetLifecycle)
      .then((value) => OverlayLifecycleEventSchema.parse(value))
  },
  onOverlayLifecycle(cb: (event: OverlayLifecycleEventPayload) => void): () => void {
    const listener = (_event: Electron.IpcRendererEvent, value: unknown): void => {
      cb(OverlayLifecycleEventSchema.parse(value))
    }
    ipcRenderer.on(IPC.overlayLifecycleEvent, listener)
    return () => {
      ipcRenderer.removeListener(IPC.overlayLifecycleEvent, listener)
    }
  }
}

contextBridge.exposeInMainWorld('rift', rift)
