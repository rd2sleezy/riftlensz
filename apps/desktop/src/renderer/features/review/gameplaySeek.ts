import type { RevealGameplayResult } from '../../../main/ipc/channels'

/** Default R.8 / H.9 lead-in. Conversion stays in the sidecar. */
export const DEFAULT_REVEAL_LEAD_IN_MS = 8_000

export async function revealGameplayTimestamp(
  sourceId: string,
  matchId: string,
  gameTMs: number,
  leadInMs: number = DEFAULT_REVEAL_LEAD_IN_MS
): Promise<RevealGameplayResult> {
  return window.rift.revealGameplay({ sourceId, matchId, gameTMs, leadInMs })
}
