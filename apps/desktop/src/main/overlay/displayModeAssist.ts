/**
 * Exclusive-fullscreen compatibility policy (R.10.5).
 *
 * Windows: true exclusive Direct3D fullscreen cannot composite an external Electron overlay.
 * macOS: a separate fullscreen Space often cannot keep an always-on-top companion visible;
 * Borderless / Windowed is the reliable path. RiftLens does not hack Spaces or inject into League.
 *
 * A safe *in-session* switch to Borderless is not available without:
 * - writing League `game.cfg` WindowMode (global — would also affect live matches,
 *   and only applies after a client restart that kills the replay)
 * - sending Alt+Enter / keybd input to League
 * - changing HWND styles / injecting into the game process
 *
 * Those are out of bounds. Guided Borderless + Recheck is the player path.
 */

export const BORDERLESS_REQUIRED_MESSAGE = 'RiftLens Overlay requires Borderless display mode.'

export const BORDERLESS_STEPS = [
  'Open League video settings.',
  'Change Window Mode to Borderless.',
  'Return to the replay.'
] as const

export const MAC_BORDERLESS_STEPS = [
  'Open League video settings.',
  'Use Borderless or Windowed (not a separate fullscreen Space).',
  'Return to the replay, then Recheck.'
] as const

export type DisplayModeSwitchPolicy = {
  automaticSwitchAvailable: boolean
  rememberChoiceAvailable: boolean
  reason: string
  playerMessage: string
  steps: readonly string[]
  liveMatchSafe: boolean
}

export function displayModeSwitchPolicy(
  platform: NodeJS.Platform | string = process.platform
): DisplayModeSwitchPolicy {
  return {
    automaticSwitchAvailable: false,
    rememberChoiceAvailable: false,
    reason: 'no_safe_in_session_switch',
    playerMessage: BORDERLESS_REQUIRED_MESSAGE,
    steps: platform === 'darwin' ? MAC_BORDERLESS_STEPS : BORDERLESS_STEPS,
    liveMatchSafe: true
  }
}

export function shouldOfferRememberChoice(policy: DisplayModeSwitchPolicy): boolean {
  return policy.automaticSwitchAvailable && policy.rememberChoiceAvailable
}
