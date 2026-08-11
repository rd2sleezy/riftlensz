/** HUD-safe overlay placement heuristics (R.10.5). Pure — no Electron imports. */

import { overlapsAnyHudZone } from './hudZones'
import {
  COMPACT_HEIGHT,
  EXPANDED_HEIGHT,
  type OverlayPrefs,
  type Rect
} from './types'

export type WorkArea = Rect & { scaleFactor?: number }

export type PlacementInput = {
  league: Rect
  workArea: WorkArea
  prefs: Pick<OverlayPrefs, 'compact' | 'position' | 'width'>
  /** Physical pixels preferred; CSS px are scaled by workArea.scaleFactor when provided. */
  height?: number
}

const MARGIN = 12
const MIN_GUTTER = 40

function overlaySize(prefs: PlacementInput['prefs'], height: number): { width: number; height: number } {
  const scale = 1
  return {
    width: Math.max(240, Math.round(prefs.width * scale)),
    height: Math.max(100, Math.round(height * scale))
  }
}

function candidateAt(league: Rect, size: { width: number; height: number }, corner: 'right' | 'left'): Rect {
  const y = league.y + league.height * 0.1
  if (corner === 'right') {
    return {
      x: league.x + league.width - size.width - MARGIN,
      y,
      width: size.width,
      height: size.height
    }
  }
  return {
    x: league.x + MARGIN,
    y,
    width: size.width,
    height: size.height
  }
}

/** Clamp so the overlay stays at least partially visible inside workArea. */
export function clampToWorkArea(rect: Rect, workArea: WorkArea): Rect {
  const minVisible = 48
  const maxX = workArea.x + workArea.width - minVisible
  const maxY = workArea.y + workArea.height - minVisible
  const minX = workArea.x + minVisible - rect.width
  const minY = workArea.y + minVisible - rect.height
  return {
    x: Math.min(maxX, Math.max(minX, rect.x)),
    y: Math.min(maxY, Math.max(minY, rect.y)),
    width: rect.width,
    height: rect.height
  }
}

/**
 * Choose a default HUD-safe rect relative to the League window.
 * Prefers upper-right gutter; falls back to upper-left; never invents center combat.
 */
export function defaultOverlayRect(input: PlacementInput): Rect {
  const height =
    input.height ?? (input.prefs.compact ? COMPACT_HEIGHT : EXPANDED_HEIGHT)
  const size = overlaySize(input.prefs, height)
  const rightGutter = input.league.width * 0.22
  const preferRight = rightGutter >= size.width + MIN_GUTTER
  const primary = candidateAt(input.league, size, preferRight ? 'right' : 'left')
  const secondary = candidateAt(input.league, size, preferRight ? 'left' : 'right')
  const chosen = overlapsAnyHudZone(input.league, primary) ? secondary : primary
  const safe = overlapsAnyHudZone(input.league, chosen)
    ? nudgeOutOfHud(input.league, chosen)
    : chosen
  return clampToWorkArea(safe, input.workArea)
}

function nudgeOutOfHud(league: Rect, rect: Rect): Rect {
  // Slide upward into the upper gutter if we still overlap.
  const nudged = { ...rect, y: league.y + league.height * 0.09 }
  if (!overlapsAnyHudZone(league, nudged)) {
    return nudged
  }
  return {
    ...rect,
    x: league.x + MARGIN,
    y: league.y + league.height * 0.09
  }
}

/** Apply a user-persisted offset when present; otherwise compute the default. */
export function resolveOverlayRect(input: PlacementInput): Rect {
  const height =
    input.height ?? (input.prefs.compact ? COMPACT_HEIGHT : EXPANDED_HEIGHT)
  const size = overlaySize(input.prefs, height)
  if (input.prefs.position !== null) {
    return clampToWorkArea(
      {
        x: input.prefs.position.x,
        y: input.prefs.position.y,
        width: size.width,
        height: size.height
      },
      input.workArea
    )
  }
  return defaultOverlayRect(input)
}

/** True when the candidate does not intersect configured HUD exclusion zones. */
export function isHudSafe(league: Rect, overlay: Rect): boolean {
  return !overlapsAnyHudZone(league, overlay)
}

export function physicalSizeForCss(
  cssWidth: number,
  cssHeight: number,
  scaleFactor: number
): { width: number; height: number } {
  const scale = scaleFactor > 0 ? scaleFactor : 1
  return {
    width: Math.round(cssWidth * scale),
    height: Math.round(cssHeight * scale)
  }
}
