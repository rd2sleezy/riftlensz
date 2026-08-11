/** Shared overlay geometry and preference types (R.10.5). */

export type Rect = {
  x: number
  y: number
  width: number
  height: number
}

export type OverlayPrefs = {
  enabled: boolean
  /** When false, detail panel is collapsed; navigator remains. */
  detailOpen: boolean
  opacity: number
  /** User-adjusted top-left of the combined overlay chrome. */
  position: { x: number; y: number } | null
  navigatorWidth: number
  detailWidth: number
  displayId: number | null
}

export const DEFAULT_OVERLAY_PREFS: OverlayPrefs = {
  enabled: true,
  detailOpen: true,
  opacity: 0.94,
  position: null,
  navigatorWidth: 300,
  detailWidth: 340,
  displayId: null
}

export type OverlayContext = {
  reviewId: string
  matchId: string
  sourceId: string
}

export type LeagueDisplayMode = 'windowed' | 'borderless' | 'exclusive_fullscreen' | 'unknown'

export type LeagueWindowInfo = {
  bounds: Rect
  minimized: boolean
  title: string
  displayMode: LeagueDisplayMode
}

/** Combined chrome sizes (navigator + optional detail). */
export const NAVIGATOR_HEIGHT = 440
export const OVERLAY_POLL_MS = 3_000
export const LEAGUE_MISSING_GRACE_POLLS = 3
export const LEAGUE_CACHE_MS = 750
export const POWERSHELL_FALLBACK_COOLDOWN_MS = 12_000

/** @deprecated kept for older tests — prefer NAVIGATOR_HEIGHT */
export const COMPACT_HEIGHT = 140
export const EXPANDED_HEIGHT = 420

export const EXCLUSIVE_FULLSCREEN_MESSAGE =
  'RiftLens overlay requires Borderless or Windowed replay mode.'
