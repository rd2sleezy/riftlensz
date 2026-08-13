export type ReplayActionId =
  | 'choose_file'
  | 'retry'
  | 'find_league_install'
  | 'enable_replay_api'
  | 'attach_video'
  | 'continue_without_replay'
  | 'reopen_replay'
  | 'open_replay'
  | 'try_anyway'
  | 'ingest_match'
  | 'open_replay_match'
  | 'sign_in_api_key'
  | 'choose_participant'
  | 'retry_after_live_game'
  | 'pick_match'

export type ReplayErrorView = {
  code: string
  message: string
  actionId: ReplayActionId
  actionLabel: string
}

const ACTION_LABELS: Record<ReplayActionId, string> = {
  choose_file: 'Choose another file',
  retry: 'Retry',
  find_league_install: 'Find League install',
  enable_replay_api: 'Enable Replay API',
  attach_video: 'Attach video instead',
  continue_without_replay: 'Continue without replay',
  reopen_replay: 'Reopen replay',
  open_replay: 'Open Replay',
  try_anyway: 'Try anyway',
  ingest_match: 'Ingest this match',
  open_replay_match: 'Open its review?',
  sign_in_api_key: 'Sign in with API key',
  choose_participant: 'Choose participant',
  retry_after_live_game: 'Retry after the live game',
  pick_match: 'Choose another file'
}

const CODE_DEFAULTS: Record<string, { message: string; actionId: ReplayActionId }> = {
  PLATFORM_UNSUPPORTED: {
    message: 'League replay import is available on Windows and macOS.',
    actionId: 'attach_video'
  },
  ROFL_UNREADABLE: {
    message: 'Replay file exists but could not be read.',
    actionId: 'choose_file'
  },
  ROFL_NOT_RECOGNISED: {
    message: "This file doesn't look like a League replay.",
    actionId: 'choose_file'
  },
  ROFL_INVALID: {
    message: 'Replay file is not a valid .rofl.',
    actionId: 'choose_file'
  },
  ROFL_MISSING: {
    message: 'Replay file is missing.',
    actionId: 'choose_file'
  },
  MATCH_ID_UNRESOLVED: {
    message: 'Could not determine which match this replay belongs to.',
    actionId: 'choose_file'
  },
  MATCH_NOT_INGESTED: {
    message: "This replay's match is not in RiftLens yet. Ingest the match first.",
    actionId: 'ingest_match'
  },
  MATCH_IDENTITY_MISMATCH: {
    message: 'This replay belongs to a different match. Open its review?',
    actionId: 'open_replay_match'
  },
  RIOT_CREDENTIAL_MISSING: {
    message: 'A Riot API key is required to download this match. Sign in with a developer key first.',
    actionId: 'sign_in_api_key'
  },
  PARTICIPANT_REQUIRED: {
    message: 'Choose which participant this review should coach.',
    actionId: 'choose_participant'
  },
  INSTALL_NOT_FOUND: {
    message: 'League of Legends installation was not found.',
    actionId: 'find_league_install'
  },
  INSTALL_INVALID: {
    message: 'League of Legends installation is incomplete.',
    actionId: 'find_league_install'
  },
  REPLAY_API_DISABLED: {
    message: 'Replay API is not enabled in the game client.',
    actionId: 'enable_replay_api'
  },
  REPLAY_API_UNAVAILABLE: {
    message: 'Local Replay API is not reachable.',
    actionId: 'retry'
  },
  LIVE_GAME_IN_PROGRESS: {
    message: 'A live League game or queue is active; replay launch was refused.',
    actionId: 'retry_after_live_game'
  },
  PATCH_INCOMPATIBLE: {
    message: 'Replay patch does not match the installed client.',
    actionId: 'try_anyway'
  },
  LAUNCH_FAILED: {
    message: 'Failed to launch the replay in the game client.',
    actionId: 'retry'
  },
  SESSION_LOST: {
    message: 'Replay window was closed. Reopen the replay to continue.',
    actionId: 'reopen_replay'
  },
  CLOCK_CALIBRATION_FAILED: {
    message: 'Automatic replay clock calibration failed; using an estimated or manual map.',
    actionId: 'continue_without_replay'
  },
  SEEK_FAILED: {
    message: 'Replay seek did not change playback time.',
    actionId: 'retry'
  },
  SOURCE_NOT_READY: {
    message: 'Gameplay source is not ready.',
    actionId: 'open_replay'
  },
  SIDECAR_UNAVAILABLE: {
    message: 'RiftLens analysis sidecar is not ready.',
    actionId: 'retry'
  }
}

const ACTION_ALIASES: Record<string, ReplayActionId> = {
  choose_file: 'choose_file',
  retry: 'retry',
  find_league_install: 'find_league_install',
  browse_to_install: 'find_league_install',
  enable_replay_api: 'enable_replay_api',
  enable_replay_api_and_restart_client: 'enable_replay_api',
  attach_video: 'attach_video',
  continue_without_replay: 'continue_without_replay',
  reopen_replay: 'reopen_replay',
  open_replay: 'open_replay',
  try_anyway: 'try_anyway',
  ingest_match: 'ingest_match',
  open_replay_match: 'open_replay_match',
  sign_in_api_key: 'sign_in_api_key',
  choose_participant: 'choose_participant',
  retry_after_live_game: 'retry_after_live_game',
  pick_match: 'pick_match',
  ask_user_to_pick_match: 'pick_match'
}

export function replayErrorView(input: {
  code: string
  message?: string | null
  suggestedAction?: string | null
}): ReplayErrorView {
  const defaults = CODE_DEFAULTS[input.code]
  const actionId = resolveAction(input.suggestedAction, defaults?.actionId ?? 'retry')
  const message = (input.message && input.message.trim()) || defaults?.message || knownFallback(input.code)
  return {
    code: input.code,
    message,
    actionId,
    actionLabel: ACTION_LABELS[actionId]
  }
}

export function knownReplayErrorCodes(): string[] {
  return Object.keys(CODE_DEFAULTS)
}

function resolveAction(suggested: string | null | undefined, fallback: ReplayActionId): ReplayActionId {
  if (suggested && ACTION_ALIASES[suggested]) {
    return ACTION_ALIASES[suggested]
  }
  return fallback
}

function knownFallback(code: string): string {
  return `${code.replaceAll('_', ' ').toLowerCase()}.`
}
