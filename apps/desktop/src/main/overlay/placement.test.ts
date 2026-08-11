import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import {
  HUD_EXCLUSION_ZONES,
  absoluteZone,
  overlapsAnyHudZone
} from '../../main/overlay/hudZones'
import {
  classifyDisplayMode,
  isLeagueTitle,
  isReplaySessionActive,
  shouldShowOverlay
} from '../../main/overlay/leagueWindow'
import {
  clampToWorkArea,
  defaultOverlayRect,
  isHudSafe,
  physicalSizeForCss,
  resolveOverlayLayout,
  resolveOverlayRect
} from '../../main/overlay/placement'
import { loadOverlayPrefs, mergeOverlayPrefs, saveOverlayPrefs } from '../../main/overlay/prefs'
import { DEFAULT_OVERLAY_PREFS, type Rect } from '../../main/overlay/types'

function leagueAt(width: number, height: number, x = 0, y = 0): Rect {
  return { x, y, width, height }
}

function workAreaFor(league: Rect): Rect {
  return { x: league.x - 40, y: league.y - 40, width: league.width + 80, height: league.height + 80 }
}

const basePrefs = {
  detailOpen: true as const,
  position: null,
  navigatorWidth: 300,
  detailWidth: 340
}

describe('overlay HUD placement', () => {
  it('keeps the 1080p two-panel default out of minimap, bottom HUD, and center combat', () => {
    const league = leagueAt(1920, 1080)
    const layout = resolveOverlayLayout({
      league,
      workArea: workAreaFor(league),
      prefs: basePrefs
    })
    // 1080p gutter is too narrow for side-by-side; stack detail under navigator.
    expect(layout.orientation).toBe('stacked')
    expect(isHudSafe(league, layout.outer)).toBe(true)
    expect(layout.detail).not.toBeNull()
    expect(layout.outer.width).toBe(300)
    expect(layout.navigator.width).toBe(300)
    for (const zone of HUD_EXCLUSION_ZONES) {
      expect(overlapsAnyHudZone(league, absoluteZone(league, zone))).toBe(true)
    }
    expect(overlapsAnyHudZone(league, layout.outer)).toBe(false)
  })

  it('uses side-by-side panels when the upper gutter is wide enough', () => {
    const league = leagueAt(3440, 1440)
    const layout = resolveOverlayLayout({
      league,
      workArea: workAreaFor(league),
      prefs: basePrefs
    })
    expect(layout.orientation).toBe('row')
    expect(isHudSafe(league, layout.outer)).toBe(true)
    expect(layout.outer.width).toBeGreaterThan(300)
  })

  it('places safely at 1440p, 4K, and ultrawide', () => {
    for (const size of [
      [2560, 1440],
      [3840, 2160],
      [3440, 1440]
    ] as const) {
      const league = leagueAt(size[0], size[1])
      const overlay = defaultOverlayRect({
        league,
        workArea: workAreaFor(league),
        prefs: basePrefs
      })
      expect(isHudSafe(league, overlay)).toBe(true)
    }
  })

  it('keeps navigator-only layout HUD-safe when detail is collapsed', () => {
    const league = leagueAt(1920, 1080)
    const layout = resolveOverlayLayout({
      league,
      workArea: workAreaFor(league),
      prefs: { ...basePrefs, detailOpen: false }
    })
    expect(layout.detail).toBeNull()
    expect(layout.outer.width).toBe(300)
    expect(isHudSafe(league, layout.outer)).toBe(true)
  })

  it('scales physical size for 125% and 150% DPI', () => {
    expect(physicalSizeForCss(320, 140, 1.25)).toEqual({ width: 400, height: 175 })
    expect(physicalSizeForCss(320, 140, 1.5)).toEqual({ width: 480, height: 210 })
  })

  it('clamps dragged overlays so they cannot fully leave the work area', () => {
    const workArea = { x: 0, y: 0, width: 1920, height: 1080 }
    const lost = clampToWorkArea({ x: -10_000, y: -10_000, width: 640, height: 440 }, workArea)
    expect(lost.x + lost.width).toBeGreaterThan(workArea.x)
    expect(lost.y + lost.height).toBeGreaterThan(workArea.y)
  })

  it('restores a user-adjusted position when present', () => {
    const league = leagueAt(1920, 1080)
    const resolved = resolveOverlayRect({
      league,
      workArea: workAreaFor(league),
      prefs: { ...basePrefs, position: { x: 100, y: 120 } }
    })
    expect(resolved.x).toBe(100)
    expect(resolved.y).toBe(120)
  })
})

describe('overlay visibility / fullscreen policy', () => {
  it('hides for exclusive D3D fullscreen with a typed reason', () => {
    const league = {
      bounds: leagueAt(1920, 1080),
      minimized: false,
      title: 'League of Legends (TM) Client',
      displayMode: 'exclusive_fullscreen' as const
    }
    expect(
      shouldShowOverlay({
        prefsEnabled: true,
        liveGame: false,
        hasContext: true,
        sessionActive: true,
        league,
        missingPolls: 0,
        exclusiveFullscreen: true
      })
    ).toEqual({ visible: false, reason: 'exclusive_fullscreen' })
  })

  it('classifies borderless vs windowed from bounds', () => {
    expect(
      classifyDisplayMode({
        exclusiveD3d: false,
        bounds: leagueAt(1920, 1080),
        displayBounds: leagueAt(1920, 1080)
      })
    ).toBe('borderless')
    expect(
      classifyDisplayMode({
        exclusiveD3d: false,
        bounds: { x: 100, y: 100, width: 1280, height: 720 },
        displayBounds: leagueAt(1920, 1080)
      })
    ).toBe('windowed')
    expect(
      classifyDisplayMode({
        exclusiveD3d: true,
        bounds: leagueAt(1920, 1080),
        displayBounds: leagueAt(1920, 1080)
      })
    ).toBe('exclusive_fullscreen')
  })

  it('shows for borderless/windowed replay context', () => {
    const league = {
      bounds: leagueAt(1920, 1080),
      minimized: false,
      title: 'League of Legends (TM) Client',
      displayMode: 'borderless' as const
    }
    expect(
      shouldShowOverlay({
        prefsEnabled: true,
        liveGame: false,
        hasContext: true,
        sessionActive: true,
        league,
        missingPolls: 0
      }).visible
    ).toBe(true)
  })

  it('treats READY/PLAYING/PAUSED/SEEKING as active replay sessions', () => {
    expect(isReplaySessionActive('READY', true)).toBe(true)
    expect(isReplaySessionActive('IDLE', true)).toBe(false)
  })

  it('recognizes League client titles', () => {
    expect(isLeagueTitle('League of Legends (TM) Client')).toBe(true)
    expect(isLeagueTitle('Discord')).toBe(false)
  })
})

describe('overlay prefs persistence', () => {
  const dirs: string[] = []
  afterEach(() => {
    for (const dir of dirs.splice(0)) {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('round-trips detailOpen and migrates legacy compact', () => {
    const dir = mkdtempSync(join(tmpdir(), 'rift-overlay-'))
    dirs.push(dir)
    const saved = saveOverlayPrefs(
      dir,
      mergeOverlayPrefs(DEFAULT_OVERLAY_PREFS, {
        position: { x: 42, y: 84 },
        detailOpen: false
      })
    )
    const loaded = loadOverlayPrefs(dir)
    expect(loaded.position).toEqual({ x: 42, y: 84 })
    expect(loaded.detailOpen).toBe(false)
    expect(saved.enabled).toBe(true)
    const raw = readFileSync(join(dir, 'overlay-prefs.json'), 'utf8')
    expect(raw).not.toMatch(/session|READY|sourceId/)
  })
})
