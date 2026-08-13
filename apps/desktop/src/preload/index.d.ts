import type {
  AuthSession,
  BuildManualSyncResult,
  CloseReplayResult,
  DesktopPlatform,
  EnableReplayApiResult,
  GameplayEnvironmentResult,
  GameplayStatusResult,
  GetReviewResult,
  HealthPayload,
  ImportReplayResult,
  ListReviewsResult,
  OpenFixtureInput,
  OpenReplayResult,
  OverlayContextResult,
  OverlayLifecycleEventPayload,
  OverlayOpenResult,
  OverlayPrefsPayload,
  OverlayUserIntentPayload,
  PickRoflResult,
  PickVodResult,
  ProbeVodResult,
  RevealGameplayResult,
  SidecarStatus,
  SignInResult,
  SignInWithApiKeyInput
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
  getAuthSession: () => Promise<AuthSession>
  signIn: () => Promise<SignInResult>
  signInWithApiKey: (input: SignInWithApiKeyInput) => Promise<SignInResult>
  signOut: () => Promise<AuthSession>
  onAuthSession: (cb: (session: AuthSession) => void) => () => void
  getDesktopPlatform: () => Promise<DesktopPlatform>
  pickRofl: () => Promise<PickRoflResult>
  importReplay: (path: string, matchId: string) => Promise<ImportReplayResult>
  getGameplayStatus: (matchId: string, sourceId?: string | null) => Promise<GameplayStatusResult>
  checkGameplayEnvironment: () => Promise<GameplayEnvironmentResult>
  enableReplayApi: () => Promise<EnableReplayApiResult>
  openReplay: (sourceId: string, matchId: string) => Promise<OpenReplayResult>
  closeReplay: (sourceId: string, matchId: string) => Promise<CloseReplayResult>
  revealGameplay: (input: {
    sourceId: string
    matchId: string
    gameTMs: number
    leadInMs?: number
  }) => Promise<RevealGameplayResult>
  overlayOpen: (input: {
    reviewId: string
    matchId: string
    sourceId: string
    sessionPhase?: string | null
    sessionReachedReady?: boolean
    liveGame?: boolean
  }) => Promise<OverlayOpenResult>
  overlayClose: () => Promise<{ ok: true }>
  overlayHide: () => Promise<OverlayLifecycleEventPayload>
  overlaySetPresentation: (intent: OverlayUserIntentPayload) => Promise<OverlayLifecycleEventPayload>
  overlayRecheckDisplay: () => Promise<OverlayLifecycleEventPayload>
  overlayGetPrefs: () => Promise<OverlayPrefsPayload>
  overlaySetPrefs: (patch: Partial<OverlayPrefsPayload>) => Promise<OverlayPrefsPayload>
  overlayGetContext: () => Promise<OverlayContextResult>
  overlaySetBounds: (bounds: {
    x: number
    y: number
    width: number
    height: number
  }) => Promise<OverlayPrefsPayload>
  overlayUpdateSession: (update: {
    sessionPhase?: string | null
    sessionReachedReady?: boolean
    liveGame?: boolean
  }) => Promise<{ ok: true }>
  overlayGetLifecycle: () => Promise<OverlayLifecycleEventPayload>
  onOverlayLifecycle: (cb: (event: OverlayLifecycleEventPayload) => void) => () => void
}

declare global {
  interface Window {
    rift: RiftApi
  }
}

export {}
