/** HUD-safe two-panel overlay placement (R.10.5). Pure — no Electron imports. */

import { overlapsAnyHudZone } from './hudZones'
import {
  COMPAT_HEIGHT,
  COMPAT_WIDTH,
  LAUNCHER_HEIGHT,
  LAUNCHER_WIDTH,
  NAVIGATOR_HEIGHT,
  type OverlayPrefs,
  type Rect
} from './types'

export type WorkArea = Rect & { scaleFactor?: number }

export type PlacementInput = {
  league: Rect
  workArea: WorkArea
  prefs: Pick<OverlayPrefs, 'detailOpen' | 'position' | 'navigatorWidth' | 'detailWidth'>
  height?: number
}

const MARGIN = 12
const MIN_GUTTER = 40
/** Keep the stack in the upper band: below scoreboard, above minimap/combat. */
const TOP_FRACTION = 0.09
const MAX_BOTTOM_FRACTION = 0.62
const PANEL_GAP = 8

function gutterCandidate(
  league: Rect,
  size: { width: number; height: number },
  corner: 'right' | 'left'
): Rect {
  const y = league.y + league.height * TOP_FRACTION
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

function placeInUpperGutter(
  league: Rect,
  workArea: WorkArea,
  size: { width: number; height: number },
  saved: { x: number; y: number } | null
): Rect {
  if (saved !== null) {
    return clampToWorkArea({ ...saved, width: size.width, height: size.height }, workArea)
  }
  const primary = gutterCandidate(league, size, 'right')
  const secondary = gutterCandidate(league, size, 'left')
  const chosen = overlapsAnyHudZone(league, primary) ? secondary : primary
  const safe = overlapsAnyHudZone(league, chosen)
    ? { ...chosen, x: league.x + MARGIN, y: league.y + league.height * TOP_FRACTION }
    : chosen
  return clampToWorkArea(safe, workArea)
}

/** Small Access Overlay pill — independent of the full coaching chrome. */
export function resolveLauncherRect(input: {
  league: Rect
  workArea: WorkArea
  launcherPosition: { x: number; y: number } | null
}): Rect {
  return placeInUpperGutter(
    input.league,
    input.workArea,
    { width: LAUNCHER_WIDTH, height: LAUNCHER_HEIGHT },
    input.launcherPosition
  )
}

/** Guided Borderless card shown when exclusive fullscreen is detected. */
export function resolveCompatRect(input: {
  league: Rect
  workArea: WorkArea
  position: { x: number; y: number } | null
}): Rect {
  return placeInUpperGutter(
    input.league,
    input.workArea,
    { width: COMPAT_WIDTH, height: COMPAT_HEIGHT },
    input.position
  )
}

export type OverlayLayout = {
  /** Combined BrowserWindow bounds. */
  outer: Rect
  navigator: Rect
  detail: Rect | null
  /** stacked = detail under navigator (HUD-safe on 1080p); row = detail left of navigator. */
  orientation: 'stacked' | 'row'
}

export function combinedSize(
  prefs: PlacementInput['prefs'],
  height: number,
  orientation: 'stacked' | 'row'
): { width: number; height: number } {
  const navW = Math.max(240, prefs.navigatorWidth)
  if (orientation === 'stacked') {
    const detailH = prefs.detailOpen ? Math.round(height * 0.48) : 0
    const navH = prefs.detailOpen ? height - detailH - PANEL_GAP : height
    return {
      width: navW,
      height: navH + detailH + (prefs.detailOpen ? PANEL_GAP : 0)
    }
  }
  const detailW = prefs.detailOpen ? Math.max(280, prefs.detailWidth) : 0
  const gap = prefs.detailOpen ? PANEL_GAP : 0
  return {
    width: navW + detailW + gap,
    height: Math.max(280, height)
  }
}

function chooseOrientation(league: Rect, prefs: PlacementInput['prefs']): 'stacked' | 'row' {
  if (!prefs.detailOpen) {
    return 'stacked'
  }
  const rowWidth = prefs.navigatorWidth + prefs.detailWidth + PANEL_GAP
  const rightGutter = league.width * 0.22
  const leftGutter = league.width * 0.22
  if (rightGutter >= rowWidth + MIN_GUTTER || leftGutter >= rowWidth + MIN_GUTTER) {
    return 'row'
  }
  return 'stacked'
}

function candidateOuter(
  league: Rect,
  size: { width: number; height: number },
  corner: 'right' | 'left'
): Rect {
  const maxH = Math.max(200, league.height * (MAX_BOTTOM_FRACTION - TOP_FRACTION))
  const height = Math.min(size.height, maxH)
  const y = league.y + league.height * TOP_FRACTION
  if (corner === 'right') {
    return {
      x: league.x + league.width - size.width - MARGIN,
      y,
      width: size.width,
      height
    }
  }
  return {
    x: league.x + MARGIN,
    y,
    width: size.width,
    height
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

function nudgeOutOfHud(league: Rect, rect: Rect): Rect {
  const nudged = { ...rect, y: league.y + league.height * TOP_FRACTION }
  if (!overlapsAnyHudZone(league, nudged)) {
    return nudged
  }
  return {
    ...rect,
    x: league.x + MARGIN,
    y: league.y + league.height * TOP_FRACTION
  }
}

/**
 * Default HUD-safe outer rect: stacked navigator+detail in the upper-right gutter
 * on typical 1080p widths; side-by-side only when the gutter is wide enough.
 */
export function defaultOverlayRect(input: PlacementInput): Rect {
  return resolveOverlayLayout(input).outer
}

export function resolveOverlayLayout(input: PlacementInput): OverlayLayout {
  const height = input.height ?? NAVIGATOR_HEIGHT
  const orientation = chooseOrientation(input.league, input.prefs)
  const size = combinedSize(input.prefs, height, orientation)
  let outer: Rect
  if (input.prefs.position !== null) {
    outer = clampToWorkArea(
      {
        x: input.prefs.position.x,
        y: input.prefs.position.y,
        width: size.width,
        height: size.height
      },
      input.workArea
    )
  } else {
    const preferRight =
      input.league.width * 0.22 >= size.width + MIN_GUTTER || orientation === 'stacked'
    const primary = candidateOuter(input.league, size, preferRight ? 'right' : 'left')
    const secondary = candidateOuter(input.league, size, preferRight ? 'left' : 'right')
    const chosen = overlapsAnyHudZone(input.league, primary) ? secondary : primary
    const safe = overlapsAnyHudZone(input.league, chosen)
      ? nudgeOutOfHud(input.league, chosen)
      : chosen
    outer = clampToWorkArea(safe, input.workArea)
  }

  if (orientation === 'stacked') {
    if (!input.prefs.detailOpen) {
      return {
        outer,
        navigator: { ...outer },
        detail: null,
        orientation
      }
    }
    const detailH = Math.round(outer.height * 0.48)
    const navH = outer.height - detailH - PANEL_GAP
    return {
      outer,
      navigator: { x: outer.x, y: outer.y, width: outer.width, height: navH },
      detail: {
        x: outer.x,
        y: outer.y + navH + PANEL_GAP,
        width: outer.width,
        height: detailH
      },
      orientation
    }
  }

  const navW = Math.max(240, input.prefs.navigatorWidth)
  const navigator: Rect = {
    x: outer.x + (input.prefs.detailOpen ? outer.width - navW : 0),
    y: outer.y,
    width: navW,
    height: outer.height
  }
  const detail: Rect | null = input.prefs.detailOpen
    ? {
        x: outer.x,
        y: outer.y,
        width: Math.max(280, outer.width - navW - PANEL_GAP),
        height: outer.height
      }
    : null
  return { outer, navigator, detail, orientation }
}

/** Apply a user-persisted offset when present; otherwise compute the default. */
export function resolveOverlayRect(input: PlacementInput): Rect {
  return resolveOverlayLayout(input).outer
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
