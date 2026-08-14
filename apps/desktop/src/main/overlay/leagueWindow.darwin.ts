/**
 * macOS League client window discovery for R.10.5 overlay placement.
 *
 * Probe order:
 * 1. CGWindowList via JXA (needs Screen Recording on modern macOS for other apps)
 * 2. System Events (needs Accessibility)
 * 3. Primary-display fallback when the LeagueofLegends process is alive
 *
 * Never treats the RiftLens/Electron main window as League.
 * No injection, no hooks, no input synthesis.
 */

import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import type { LeagueWindowInfo, Rect } from './types'
import { LEAGUE_CACHE_MS, POWERSHELL_FALLBACK_COOLDOWN_MS } from './types'
import { classifyDisplayMode } from './leagueWindow.shared'

const execFileAsync = promisify(execFile)

export type LeagueBoundsSource =
  | 'cgwindowlist'
  | 'system_events'
  | 'primary_fallback'
  | 'none'

export type DarwinLeagueProbeMeta = {
  boundsSource: LeagueBoundsSource
  processRunning: boolean
  accessibilityDenied: boolean
  screenRecordingLikelyDenied: boolean
  message: string | null
}

export const MAC_LEAGUE_BOUNDS_PERMISSION_MESSAGE =
  'RiftLens could not read the League window. Grant Screen Recording or Accessibility for RiftLens (System Settings → Privacy & Security), keep League in Windowed/Borderless, then Recheck.'

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
let lastMeta: DarwinLeagueProbeMeta = {
  boundsSource: 'none',
  processRunning: false,
  accessibilityDenied: false,
  screenRecordingLikelyDenied: false,
  message: null
}

/** Clear darwin caches (tests). */
export function resetDarwinLeagueWindowCache(): void {
  cache = null
  lastAsyncAt = 0
  asyncInFlight = null
  lastMeta = {
    boundsSource: 'none',
    processRunning: false,
    accessibilityDenied: false,
    screenRecordingLikelyDenied: false,
    message: null
  }
}

/** Latest probe diagnostics for overlay lifecycle messaging / acceptance. */
export function getDarwinLeagueProbeMeta(): DarwinLeagueProbeMeta {
  return { ...lastMeta }
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
  const processRunning = await isLeagueGameProcessRunning()
  let accessibilityDenied = false
  let screenRecordingLikelyDenied = false

  const viaCg = await findViaCgWindowList()
  if (viaCg.denied) {
    screenRecordingLikelyDenied = true
  }
  if (viaCg.window !== null) {
    lastMeta = {
      boundsSource: 'cgwindowlist',
      processRunning,
      accessibilityDenied: false,
      screenRecordingLikelyDenied: false,
      message: null
    }
    return annotate(viaCg.window, 'cgwindowlist')
  }

  const viaScript = await findViaSystemEvents()
  if (viaScript.denied) {
    accessibilityDenied = true
  }
  if (viaScript.window !== null) {
    lastMeta = {
      boundsSource: 'system_events',
      processRunning,
      accessibilityDenied: false,
      screenRecordingLikelyDenied,
      message: null
    }
    return annotate(viaScript.window, 'system_events')
  }

  if (processRunning) {
    lastMeta = {
      boundsSource: 'primary_fallback',
      processRunning: true,
      accessibilityDenied,
      screenRecordingLikelyDenied,
      message:
        accessibilityDenied || screenRecordingLikelyDenied
          ? MAC_LEAGUE_BOUNDS_PERMISSION_MESSAGE
          : 'League process found but window bounds were unavailable; placing overlay on the primary display.'
    }
    return annotate(syntheticPrimaryDisplayWindow(), 'primary_fallback')
  }

  lastMeta = {
    boundsSource: 'none',
    processRunning: false,
    accessibilityDenied,
    screenRecordingLikelyDenied,
    message: null
  }
  return null
}

function annotate(window: LeagueWindowInfo, source: LeagueBoundsSource): LeagueWindowInfo {
  return { ...window, boundsSource: source }
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
    }),
    boundsSource: 'primary_fallback'
  }
}

type ProbeAttempt = { window: LeagueWindowInfo | null; denied: boolean }

async function findViaCgWindowList(): Promise<ProbeAttempt> {
  const script = `
ObjC.import('CoreGraphics');
ObjC.import('Foundation');
var opts = $.kCGWindowListOptionOnScreenOnly | $.kCGWindowListExcludeDesktopElements;
var cfInfo = $.CGWindowListCopyWindowInfo(opts, $.kCGNullWindowID);
if (!cfInfo) { JSON.stringify({ ok: false, denied: true, windows: [] }); }
else {
  var arr = ObjC.deepUnwrap(ObjC.castRefToObject(cfInfo)) || [];
  var out = [];
  for (var i = 0; i < arr.length; i++) {
    var w = arr[i] || {};
    var owner = String(w.kCGWindowOwnerName || '');
    var name = String(w.kCGWindowName || '');
    var layer = Number(w.kCGWindowLayer || 0);
    var b = w.kCGWindowBounds || {};
    var width = Number(b.Width || 0);
    var height = Number(b.Height || 0);
    if (width < 640 || height < 480) continue;
    if (layer !== 0) continue;
    if (/riot client/i.test(owner) || /riot client/i.test(name)) continue;
    if (/electron/i.test(owner) || /riftlens/i.test(owner) || /cursor/i.test(owner)) continue;
    var isLeagueOwner = /leagueoflegends/i.test(owner) || /^league of legends$/i.test(owner);
    var isLeagueTitle = /league of legends/i.test(name);
    if (!isLeagueOwner && !isLeagueTitle) continue;
    out.push({
      owner: owner,
      title: name || owner,
      x: Number(b.X || 0),
      y: Number(b.Y || 0),
      width: width,
      height: height
    });
  }
  JSON.stringify({ ok: true, denied: false, windows: out });
}
`
  try {
    const { stdout, stderr } = await execFileAsync(
      '/usr/bin/osascript',
      ['-l', 'JavaScript', '-e', script],
      { encoding: 'utf8', timeout: 4_000 }
    )
    const trimmed = stdout.trim()
    if (!trimmed) {
      return { window: null, denied: /assistive|not allowed|permission/i.test(stderr) }
    }
    const parsed = JSON.parse(trimmed) as {
      ok: boolean
      denied?: boolean
      windows: Array<{ owner: string; title: string; x: number; y: number; width: number; height: number }>
    }
    const best = pickLargest(parsed.windows ?? [])
    if (best === null) {
      return { window: null, denied: parsed.denied === true }
    }
    return { window: toLeagueInfo(best.title || best.owner, best), denied: false }
  } catch (error) {
    const text = error instanceof Error ? error.message : String(error)
    return { window: null, denied: /assistive|not allowed|permission/i.test(text) }
  }
}

async function findViaSystemEvents(): Promise<ProbeAttempt> {
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
    const { stdout, stderr } = await execFileAsync(
      '/usr/bin/osascript',
      ['-e', script],
      { encoding: 'utf8', timeout: 4_000 }
    )
    const trimmed = stdout.trim()
    if (!trimmed) {
      return {
        window: null,
        denied: /assistive|not allowed to send key|not authorized|permission/i.test(stderr)
      }
    }
    const parts = trimmed.split(',')
    if (parts.length < 5) {
      return { window: null, denied: false }
    }
    const x = Number(parts[0])
    const y = Number(parts[1])
    const width = Number(parts[2])
    const height = Number(parts[3])
    if (![x, y, width, height].every((n) => Number.isFinite(n))) {
      return { window: null, denied: false }
    }
    if (width < 640 || height < 480) {
      return { window: null, denied: false }
    }
    const minimized = String(parts[4]).toLowerCase() === 'true'
    const title = parts.slice(5).join(',').trim() || 'League of Legends'
    if (/riot client/i.test(title) || /electron/i.test(title) || /riftlens/i.test(title)) {
      return { window: null, denied: false }
    }
    return {
      window: toLeagueInfo(title, { x, y, width, height }, minimized),
      denied: false
    }
  } catch (error) {
    const text = error instanceof Error ? error.message : String(error)
    return {
      window: null,
      denied: /assistive|not allowed|not authorized|permission/i.test(text)
    }
  }
}

function pickLargest(
  windows: Array<{ owner: string; title: string; x: number; y: number; width: number; height: number }>
): { owner: string; title: string; x: number; y: number; width: number; height: number } | null {
  let best: (typeof windows)[number] | null = null
  let bestArea = 0
  for (const window of windows) {
    const area = window.width * window.height
    if (area > bestArea) {
      best = window
      bestArea = area
    }
  }
  return best
}

function toLeagueInfo(
  title: string,
  bounds: Rect,
  minimized = false
): LeagueWindowInfo {
  const display = electronScreen().getDisplayMatching({
    x: Math.round(bounds.x),
    y: Math.round(bounds.y),
    width: Math.max(1, Math.round(bounds.width)),
    height: Math.max(1, Math.round(bounds.height))
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
}
