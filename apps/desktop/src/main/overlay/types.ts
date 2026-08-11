/** Shared overlay geometry and preference types (R.10.5). */

export type Rect = {
  x: number
  y: number
  width: number
  height: number
}

export type OverlayPrefs = {
  enabled: boolean
  compact: boolean
  opacity: number
  /** User-adjusted position relative to League client (or absolute when restored). */
  position: { x: number; y: number } | null
  width: number
  displayId: number | null
}

export const DEFAULT_OVERLAY_PREFS: OverlayPrefs = {
  enabled: true,
  compact: true,
  opacity: 0.94,
  position: null,
  width: 320,
  displayId: null
}

export type OverlayContext = {
  reviewId: string
  matchId: string
  sourceId: string
}

export type LeagueWindowInfo = {
  bounds: Rect
  minimized: boolean
  title: string
}

export const COMPACT_HEIGHT = 140
export const EXPANDED_HEIGHT = 420
export const OVERLAY_POLL_MS = 1_000
export const LEAGUE_MISSING_GRACE_POLLS = 3
