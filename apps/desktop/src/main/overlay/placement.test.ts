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
  isLeagueTitle,
  isReplaySessionActive,
  shouldShowOverlay
} from '../../main/overlay/leagueWindow'
import {
  clampToWorkArea,
  defaultOverlayRect,
  isHudSafe,
  physicalSizeForCss,
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

describe('overlay HUD placement', () => {
  it('keeps the 1080p default out of minimap, bottom HUD, and center combat', () => {
    const league = leagueAt(1920, 1080)
    const overlay = defaultOverlayRect({
      league,
      workArea: workAreaFor(league),
      prefs: { compact: true, position: null, width: 320 }
    })
    expect(isHudSafe(league, overlay)).toBe(true)
    for (const zone of HUD_EXCLUSION_ZONES) {
      expect(overlapsAnyHudZone(league, absoluteZone(league, zone))).toBe(true)
    }
    expect(overlapsAnyHudZone(league, overlay)).toBe(false)
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
        prefs: { compact: true, position: null, width: 320 }
      })
      expect(isHudSafe(league, overlay)).toBe(true)
    }
  })

  it('scales physical size for 125% and 150% DPI', () => {
    expect(physicalSizeForCss(320, 140, 1.25)).toEqual({ width: 400, height: 175 })
    expect(physicalSizeForCss(320, 140, 1.5)).toEqual({ width: 480, height: 210 })
  })

  it('clamps dragged overlays so they cannot fully leave the work area', () => {
    const workArea = { x: 0, y: 0, width: 1920, height: 1080 }
    const lost = clampToWorkArea({ x: -10_000, y: -10_000, width: 320, height: 140 }, workArea)
    expect(lost.x + lost.width).toBeGreaterThan(workArea.x)
    expect(lost.y + lost.height).toBeGreaterThan(workArea.y)
    const far = clampToWorkArea({ x: 50_000, y: 50_000, width: 320, height: 140 }, workArea)
    expect(far.x).toBeLessThan(workArea.x + workArea.width)
    expect(far.y).toBeLessThan(workArea.y + workArea.height)
  })

  it('restores a user-adjusted position when present', () => {
    const league = leagueAt(1920, 1080)
    const resolved = resolveOverlayRect({
      league,
      workArea: workAreaFor(league),
      prefs: { compact: true, position: { x: 100, y: 120 }, width: 320 }
    })
    expect(resolved.x).toBe(100)
    expect(resolved.y).toBe(120)
  })
})

describe('overlay visibility policy', () => {
  it('shows only for replay/review context and hides on live game or session close', () => {
    const league = {
      bounds: leagueAt(1920, 1080),
      minimized: false,
      title: 'League of Legends (TM) Client'
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
    expect(
      shouldShowOverlay({
        prefsEnabled: true,
        liveGame: true,
        hasContext: true,
        sessionActive: true,
        league,
        missingPolls: 0
      }).reason
    ).toBe('live_game')
    expect(
      shouldShowOverlay({
        prefsEnabled: true,
        liveGame: false,
        hasContext: true,
        sessionActive: false,
        league,
        missingPolls: 0
      }).reason
    ).toBe('session_inactive')
    expect(
      shouldShowOverlay({
        prefsEnabled: true,
        liveGame: false,
        hasContext: true,
        sessionActive: true,
        league: { ...league, minimized: true },
        missingPolls: 0
      }).reason
    ).toBe('league_minimized')
    expect(
      shouldShowOverlay({
        prefsEnabled: true,
        liveGame: false,
        hasContext: true,
        sessionActive: true,
        league: null,
        missingPolls: 4
      }).reason
    ).toBe('league_missing')
  })

  it('treats READY/PLAYING/PAUSED/SEEKING as active replay sessions', () => {
    expect(isReplaySessionActive('READY', true)).toBe(true)
    expect(isReplaySessionActive('IDLE', true)).toBe(false)
    expect(isReplaySessionActive('READY', false)).toBe(false)
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

  it('round-trips user drag position without claiming a live session', () => {
    const dir = mkdtempSync(join(tmpdir(), 'rift-overlay-'))
    dirs.push(dir)
    const saved = saveOverlayPrefs(
      dir,
      mergeOverlayPrefs(DEFAULT_OVERLAY_PREFS, {
        position: { x: 42, y: 84 },
        compact: false
      })
    )
    const loaded = loadOverlayPrefs(dir)
    expect(loaded.position).toEqual({ x: 42, y: 84 })
    expect(loaded.compact).toBe(false)
    expect(saved.enabled).toBe(true)
    const raw = readFileSync(join(dir, 'overlay-prefs.json'), 'utf8')
    expect(raw).not.toMatch(/session|READY|sourceId/)
  })
})
