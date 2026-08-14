/**
 * macOS League client window discovery for R.10.5 overlay placement.
 *
 * Uses System Events (osascript) for real window bounds when Accessibility
 * allows it. Falls back to the primary display when the game process is alive
 * but bounds are unavailable — HUD-safe placement still clamps to workArea.
 *
 * No injection, no hooks, no input synthesis.
 */

import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import type { LeagueWindowInfo, Rect } from './types'
import { LEAGUE_CACHE_MS, POWERSHELL_FALLBACK_COOLDOWN_MS } from './types'
import { classifyDisplayMode } from './leagueWindow.shared'

const execFileAsync = promisify(execFile)

function electronScreen(): typeof import('electron').screen {
  // Lazy require so unit tests that import shared helpers do not need Electron.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return require('electron').screen as typeof import('electron').screen
}

/** Game process names observed on Mac (spike + MacReplayHost). */
const MAC_LEAGUE_PROCESS_NAMES = ['LeagueofLegends', 'League of Legends'] as const

let cache: { at: number; value: LeagueWindowInfo | null } | null = null
let lastAsyncAt = 0
let asyncInFlight: Promise<LeagueWindowInfo | null> | null = null

/** Clear darwin caches (tests). */
export function resetDarwinLeagueWindowCache(): void {
  cache = null
  lastAsyncAt = 0
  asyncInFlight = null
}

/**
 * Synchronous lookup for the controller tick. Returns the short TTL cache only;
 * never blocks on osascript.
 */
export function findLeagueClientWindowDarwin(): LeagueWindowInfo | null {
  const now = Date.now()
  if (cache !== null && now - cache.at < LEAGUE_CACHE_MS) {
    return cache.value
  }
  scheduleDarwinRefresh()
  return cache?.value ?? null
}

/** Async refresh used after overlay open / recheck. */
export async function refreshLeagueClientWindowDarwinAsync(): Promise<LeagueWindowInfo | null> {
  const value = await probeDarwinLeagueWindow()
  cache = { at: Date.now(), value }
  return value
}

/** Exclusive D3D fullscreen does not exist on macOS; Spaces fullscreen is handled via bounds. */
export function isExclusiveFullscreenDarwin(): boolean {
  return false
}

function scheduleDarwinRefresh(): void {
  const now = Date.now()
  if (now - lastAsyncAt < POWERSHELL_FALLBACK_COOLDOWN_MS && cache !== null) {
    return
  }
  if (asyncInFlight !== null) {
    return
  }
  lastAsyncAt = now
  asyncInFlight = probeDarwinLeagueWindow().finally(() => {
    asyncInFlight = null
  })
  void asyncInFlight.then((value) => {
    cache = { at: Date.now(), value }
  })
}

async function probeDarwinLeagueWindow(): Promise<LeagueWindowInfo | null> {
  const viaScript = await findViaOsascript()
  if (viaScript !== null) {
    return viaScript
  }
  if (await isLeagueGameProcessRunning()) {
    return syntheticPrimaryDisplayWindow()
  }
  return null
}

async function isLeagueGameProcessRunning(): Promise<boolean> {
  try {
    const { stdout } = await execFileAsync('/bin/ps', ['-axco', 'command'], {
      encoding: 'utf8',
      timeout: 2_000
    })
    const lines = stdout.split('\n').map((line) => line.trim())
    return lines.some((name) =>
      MAC_LEAGUE_PROCESS_NAMES.some((hint) => name === hint || name.endsWith(hint))
    )
  } catch {
    return false
  }
}

function syntheticPrimaryDisplayWindow(): LeagueWindowInfo {
  const display = electronScreen().getPrimaryDisplay()
  const bounds: Rect = {
    x: display.bounds.x,
    y: display.bounds.y,
    width: display.bounds.width,
    height: display.bounds.height
  }
  return {
    title: 'League of Legends',
    minimized: false,
    bounds,
    displayMode: classifyDisplayMode({
      exclusiveD3d: false,
      bounds,
      displayBounds: {
        x: display.bounds.x,
        y: display.bounds.y,
        width: display.bounds.width,
        height: display.bounds.height
      }
    })
  }
}

async function findViaOsascript(): Promise<LeagueWindowInfo | null> {
  const script = `
set procNames to {"LeagueofLegends", "League of Legends"}
tell application "System Events"
  repeat with procName in procNames
    if exists process procName then
      tell process procName
        set winCount to count of windows
        if winCount is 0 then
          -- continue
        else
          set theWindow to window 1
          set p to position of theWindow
          set s to size of theWindow
          set minimizedFlag to value of attribute "AXMinimized" of theWindow
          set titleText to name of theWindow
          return (item 1 of p as text) & "," & (item 2 of p as text) & "," & (item 1 of s as text) & "," & (item 2 of s as text) & "," & (minimizedFlag as text) & "," & titleText
        end if
      end tell
    end if
  end repeat
end tell
return ""
`
  try {
    const { stdout } = await execFileAsync(
      '/usr/bin/osascript',
      ['-e', script],
      { encoding: 'utf8', timeout: 4_000 }
    )
    const trimmed = stdout.trim()
    if (!trimmed) {
      return null
    }
    const parts = trimmed.split(',')
    if (parts.length < 5) {
      return null
    }
    const x = Number(parts[0])
    const y = Number(parts[1])
    const width = Number(parts[2])
    const height = Number(parts[3])
    if (![x, y, width, height].every((n) => Number.isFinite(n))) {
      return null
    }
    if (width < 640 || height < 480) {
      return null
    }
    const minimized = String(parts[4]).toLowerCase() === 'true'
    const title = parts.slice(5).join(',').trim() || 'League of Legends'
    if (/riot client/i.test(title)) {
      return null
    }
    const bounds: Rect = { x, y, width, height }
    const display = electronScreen().getDisplayMatching({
      x: Math.round(x),
      y: Math.round(y),
      width: Math.max(1, Math.round(width)),
      height: Math.max(1, Math.round(height))
    })
    return {
      title,
      minimized,
      bounds,
      displayMode: classifyDisplayMode({
        exclusiveD3d: false,
        bounds,
        displayBounds: {
          x: display.bounds.x,
          y: display.bounds.y,
          width: display.bounds.width,
          height: display.bounds.height
        }
      })
    }
  } catch {
    return null
  }
}
