import type { GameplayStatus, ReplayErrorPayload } from '../../../main/ipc/channels'
import { replayErrorView, type ReplayActionId } from './replayErrors'

export type GameplayBarKind =
  | 'none'
  | 'video_manual'
  | 'replay_unavailable_platform'
  | 'replay_linked'
  | 'league_not_found'
  | 'replay_api_disabled'
  | 'replay_api_unavailable'
  | 'patch_warning'
  | 'launching'
  | 'connecting'
  | 'ready'
  | 'syncing'
  | 'ready_verified'
  | 'ready_degraded'
  | 'session_lost'
  | 'replay_error'

export type GameplayBarView = {
  kind: GameplayBarKind
  label: string
  tone: 'neutral' | 'info' | 'ok' | 'warn' | 'error'
  syncLabel: string | null
  showOpen: boolean
  showClose: boolean
  showRetry: boolean
  actionId: ReplayActionId | null
  actionLabel: string | null
  errorCode: string | null
  technical: {
    offset_ms: number | null
    residual_ms: number | null
    anchor_count: number | null
    clock_method: string | null
    session_phase: string | null
  }
}

export type GameplayBarInput = {
  status: GameplayStatus | null
  nativeReplaySupported: boolean
  hasInlineVideo: boolean
  videoSynced: boolean
  opening: boolean
  seeking: boolean
}

export function deriveGameplayBar(input: GameplayBarInput): GameplayBarView {
  const status = input.status
  const technical = {
    offset_ms: status?.offset_ms ?? null,
    residual_ms: status?.residual_ms ?? null,
    anchor_count: status?.anchor_count ?? null,
    clock_method: status?.clock_method ?? null,
    session_phase: status?.session_phase ?? null
  }
  const error = status?.error ?? null
  const errorView = error ? replayErrorView({
    code: error.code,
    message: error.message,
    suggestedAction: error.suggested_action
  }) : null
  const nativeCaps = hasNativeCapabilities(status)
  const linked = Boolean(status?.active_source_id) && nativeCaps
  const phase = status?.session_phase ?? 'IDLE'
  const ready = status?.session_reached_ready === true && isReadyPhase(phase)

  if (input.opening || phase === 'LAUNCHING') {
    return bar('launching', 'Opening replay…', 'info', {
      showClose: true,
      technical
    })
  }
  if (phase === 'CONNECTING' || (input.seeking && !ready && linked)) {
    return bar('connecting', 'Connecting to replay…', 'info', {
      showClose: true,
      technical
    })
  }
  if (phase === 'SEEKING' || input.seeking) {
    return bar('syncing', 'Seeking…', 'info', {
      showClose: true,
      syncLabel: syncLabel(status, input.videoSynced),
      technical
    })
  }
  if (error?.code === 'SESSION_LOST') {
    return bar('session_lost', errorView?.message ?? 'Replay window was closed.', 'error', {
      showRetry: true,
      actionId: 'reopen_replay',
      actionLabel: 'Reopen replay',
      errorCode: error.code,
      technical
    })
  }
  if (error && linked && !ready) {
    return errorBar(error, errorView, technical)
  }
  if (ready) {
    const verified = status?.clock_verified === true && !isDegraded(status)
    if (verified) {
      return bar('ready_verified', readyLabel(status, true), 'ok', {
        showClose: true,
        syncLabel: 'Verified replay sync',
        technical
      })
    }
    return bar('ready_degraded', readyLabel(status, false), 'warn', {
      showClose: true,
      syncLabel: degradedSyncLabel(status),
      technical
    })
  }
  if (error && !linked && input.hasInlineVideo) {
    return videoBar(input.videoSynced, technical)
  }
  if (error && !ready) {
    return errorBar(error, errorView, technical)
  }
  if (!input.nativeReplaySupported && linked) {
    return bar('replay_unavailable_platform', 'Replay unavailable on this platform', 'warn', {
      actionId: 'attach_video',
      actionLabel: 'Attach video instead',
      errorCode: 'PLATFORM_UNSUPPORTED',
      technical
    })
  }
  if (linked && status?.declared_patch && warningHas(status, 'PATCH_INCOMPATIBLE')) {
    return bar(
      'patch_warning',
      `Replay may not open — patch ${status.declared_patch}`,
      'warn',
      {
        showOpen: true,
        actionId: 'try_anyway',
        actionLabel: 'Try anyway',
        technical
      }
    )
  }
  if (linked) {
    const patch = status?.declared_patch ? ` · patch ${status.declared_patch}` : ''
    return bar('replay_linked', `Replay linked${patch}`, 'info', {
      showOpen: true,
      technical
    })
  }
  if (input.hasInlineVideo) {
    return videoBar(input.videoSynced, technical)
  }
  return bar('none', 'No gameplay attached', 'neutral', { technical })
}

export function hasNativeCapabilities(status: GameplayStatus | null): boolean {
  if (status === null || status.active_source_id === null) {
    return false
  }
  if (status.capabilities.includes('LIVE_CLIENT_DATA')) {
    return true
  }
  return status.capabilities.length === 0
}

export function nativeSessionReady(status: GameplayStatus | null): boolean {
  if (status === null || !hasNativeCapabilities(status)) {
    return false
  }
  return status.session_reached_ready && isReadyPhase(status.session_phase)
}

function videoBar(videoSynced: boolean, technical: GameplayBarView['technical']): GameplayBarView {
  return bar('video_manual', videoSynced ? 'Video · manual sync' : 'Video attached', 'info', {
    syncLabel: videoSynced ? 'Manual sync' : 'Sync unavailable',
    technical
  })
}

function errorBar(
  error: ReplayErrorPayload,
  errorView: ReturnType<typeof replayErrorView> | null,
  technical: GameplayBarView['technical']
): GameplayBarView {
  const kind = kindForError(error.code)
  return bar(kind, errorView?.message ?? error.message, kind === 'replay_error' ? 'error' : 'warn', {
    showRetry: errorView?.actionId === 'retry' || errorView?.actionId === 'reopen_replay',
    showOpen: errorView?.actionId === 'open_replay' || errorView?.actionId === 'try_anyway',
    actionId: errorView?.actionId ?? null,
    actionLabel: errorView?.actionLabel ?? null,
    errorCode: error.code,
    technical
  })
}

function kindForError(code: string): GameplayBarKind {
  if (code === 'PLATFORM_UNSUPPORTED') {
    return 'replay_unavailable_platform'
  }
  if (code === 'INSTALL_NOT_FOUND' || code === 'INSTALL_INVALID') {
    return 'league_not_found'
  }
  if (code === 'REPLAY_API_DISABLED') {
    return 'replay_api_disabled'
  }
  if (code === 'REPLAY_API_UNAVAILABLE') {
    return 'replay_api_unavailable'
  }
  if (code === 'PATCH_INCOMPATIBLE') {
    return 'patch_warning'
  }
  if (code === 'SESSION_LOST') {
    return 'session_lost'
  }
  return 'replay_error'
}

function readyLabel(status: GameplayStatus | null, verified: boolean): string {
  if (verified) {
    const residual = status?.residual_ms
    if (typeof residual === 'number') {
      const seconds = Math.max(0.1, Math.round(Math.abs(residual) / 100) / 10)
      return `Replay connected · auto-synced ±${seconds}s`
    }
    return 'Replay connected · auto-synced'
  }
  return 'Replay connected · sync estimated'
}

function syncLabel(status: GameplayStatus | null, videoSynced: boolean): string | null {
  if (status && nativeSessionReady(status)) {
    if (status.clock_verified === true && !isDegraded(status)) {
      return 'Verified replay sync'
    }
    return degradedSyncLabel(status)
  }
  if (videoSynced) {
    return 'Manual sync'
  }
  return null
}

function degradedSyncLabel(status: GameplayStatus | null): string {
  if (status?.clock_confidence === 'UNKNOWN' || status?.clock_verified === false) {
    if (status.clock_method?.includes('manual')) {
      return 'Manual sync'
    }
    return 'Estimated sync'
  }
  return 'Auto-synced'
}

function isDegraded(status: GameplayStatus | null): boolean {
  if (status === null) {
    return false
  }
  if (status.clock_verified !== true) {
    return true
  }
  return status.clock_confidence === 'DEGRADED' || status.clock_confidence === 'FAILED'
}

function isReadyPhase(phase: string): boolean {
  return phase === 'READY' || phase === 'PLAYING' || phase === 'PAUSED' || phase === 'SEEKING'
}

function warningHas(status: GameplayStatus, code: string): boolean {
  return status.warnings.some((item) => item.code === code)
}

function bar(
  kind: GameplayBarKind,
  label: string,
  tone: GameplayBarView['tone'],
  extra: Partial<GameplayBarView> & { technical: GameplayBarView['technical'] }
): GameplayBarView {
  return {
    kind,
    label,
    tone,
    syncLabel: extra.syncLabel ?? null,
    showOpen: extra.showOpen ?? false,
    showClose: extra.showClose ?? false,
    showRetry: extra.showRetry ?? false,
    actionId: extra.actionId ?? null,
    actionLabel: extra.actionLabel ?? null,
    errorCode: extra.errorCode ?? null,
    technical: extra.technical
  }
}
