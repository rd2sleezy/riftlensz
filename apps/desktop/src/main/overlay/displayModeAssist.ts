/**
 * Exclusive-fullscreen compatibility policy (R.10.5).
 *
 * True exclusive Direct3D fullscreen cannot composite an external Electron overlay.
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

export type DisplayModeSwitchPolicy = {
  automaticSwitchAvailable: boolean
  rememberChoiceAvailable: boolean
  reason: string
  playerMessage: string
  steps: readonly string[]
  liveMatchSafe: boolean
}

export function displayModeSwitchPolicy(): DisplayModeSwitchPolicy {
  return {
    automaticSwitchAvailable: false,
    rememberChoiceAvailable: false,
    reason: 'no_safe_in_session_switch',
    playerMessage: BORDERLESS_REQUIRED_MESSAGE,
    steps: BORDERLESS_STEPS,
    liveMatchSafe: true
  }
}

export function shouldOfferRememberChoice(policy: DisplayModeSwitchPolicy): boolean {
  return policy.automaticSwitchAvailable && policy.rememberChoiceAvailable
}
