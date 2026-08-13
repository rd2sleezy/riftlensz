import type {
  AuthSession,
  BuildManualSyncResult,
  GetReviewResult,
  HealthPayload,
  ListReviewsResult,
  OpenFixtureInput,
  PickVodResult,
  ProbeVodResult,
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
}

declare global {
  interface Window {
    rift: RiftApi
  }
}

export {}
