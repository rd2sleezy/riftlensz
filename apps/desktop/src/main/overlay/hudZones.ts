/** HUD exclusion zones as fractions of the League client client-area rect (R.10.5). */

import type { Rect } from './types'

export type HudZoneId = 'minimap' | 'bottomHud' | 'topScoreboard' | 'centerCombat'

export type HudZone = {
  id: HudZoneId
  /** Fraction of League width/height in [0,1]. */
  rect: { x: number; y: number; width: number; height: number }
}

/**
 * Conservative League/replay HUD exclusions.
 * Coordinates are relative to League window bounds (0 = left/top, 1 = full span).
 */
export const HUD_EXCLUSION_ZONES: readonly HudZone[] = [
  { id: 'topScoreboard', rect: { x: 0.15, y: 0, width: 0.7, height: 0.08 } },
  { id: 'bottomHud', rect: { x: 0, y: 0.78, width: 1, height: 0.22 } },
  { id: 'minimap', rect: { x: 0.78, y: 0.68, width: 0.22, height: 0.32 } },
  { id: 'centerCombat', rect: { x: 0.3, y: 0.25, width: 0.4, height: 0.45 } }
]

export function absoluteZone(league: Rect, zone: HudZone): Rect {
  return {
    x: league.x + zone.rect.x * league.width,
    y: league.y + zone.rect.y * league.height,
    width: zone.rect.width * league.width,
    height: zone.rect.height * league.height
  }
}

export function rectsOverlap(a: Rect, b: Rect, pad = 0): boolean {
  return !(
    a.x + a.width + pad <= b.x ||
    b.x + b.width + pad <= a.x ||
    a.y + a.height + pad <= b.y ||
    b.y + b.height + pad <= a.y
  )
}

export function overlapsAnyHudZone(league: Rect, candidate: Rect, pad = 4): boolean {
  return HUD_EXCLUSION_ZONES.some((zone) => rectsOverlap(candidate, absoluteZone(league, zone), pad))
}

export function pointInRect(x: number, y: number, rect: Rect): boolean {
  return x >= rect.x && y >= rect.y && x < rect.x + rect.width && y < rect.y + rect.height
}
