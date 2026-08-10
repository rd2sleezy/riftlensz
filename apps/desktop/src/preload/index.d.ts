import type {
  BuildManualSyncResult,
  CloseReplayResult,
  DesktopPlatform,
  GameplayEnvironmentResult,
  GameplayStatusResult,
  GetReviewResult,
  HealthPayload,
  ImportReplayResult,
  ListReviewsResult,
  OpenFixtureInput,
  OpenReplayResult,
  PickRoflResult,
  PickVodResult,
  ProbeVodResult,
  RevealGameplayResult,
  SidecarStatus
} from '../main/ipc/channels'

export interface RiftApi {
  getSidecarStatus: () => Promise<SidecarStatus>
  onSidecarStatus: (cb: (status: SidecarStatus) => void) => () => void
  health: () => Promise<HealthPayload>
  restartSidecar: () => Promise<SidecarStatus>
  listReviews: () => Promise<ListReviewsResult>
  getReview: (reviewId: string) => Promise<GetReviewResult>
  openFixtureReview: (input: OpenFixtureInput) => Promise<GetReviewResult>
  pickVod: () => Promise<PickVodResult>
  probeVod: (path: string) => Promise<ProbeVodResult>
  buildManualSync: (input: {
    matchId: string
    videoDurationMs: number
    matchDurationMs?: number | null
    mediaAssetId?: string
    anchors: { t_video_ms: number; t_game_ms: number }[]
  }) => Promise<BuildManualSyncResult>
  getDesktopPlatform: () => Promise<DesktopPlatform>
  pickRofl: () => Promise<PickRoflResult>
  importReplay: (path: string, matchId: string) => Promise<ImportReplayResult>
  getGameplayStatus: (matchId: string, sourceId?: string | null) => Promise<GameplayStatusResult>
  checkGameplayEnvironment: () => Promise<GameplayEnvironmentResult>
  openReplay: (sourceId: string, matchId: string) => Promise<OpenReplayResult>
  closeReplay: (sourceId: string, matchId: string) => Promise<CloseReplayResult>
  revealGameplay: (input: {
    sourceId: string
    matchId: string
    gameTMs: number
    leadInMs?: number
  }) => Promise<RevealGameplayResult>
}

declare global {
  interface Window {
    rift: RiftApi
  }
}

export {}
