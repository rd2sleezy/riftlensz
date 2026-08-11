/**
 * League client window discovery (R.10.5).
 * Fast FindWindowW path + rare PowerShell fallback. Detects exclusive D3D fullscreen
 * via SHQueryUserNotificationState (no process injection).
 */

import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import type { LeagueDisplayMode, LeagueWindowInfo, Rect } from './types'
import { LEAGUE_CACHE_MS, POWERSHELL_FALLBACK_COOLDOWN_MS } from './types'

const execFileAsync = promisify(execFile)

const LEAGUE_TITLES = [
  'League of Legends (TM) Client',
  'League of Legends'
] as const

/** QUNS_RUNNING_D3D_FULL_SCREEN — exclusive Direct3D fullscreen. */
const QUNS_RUNNING_D3D_FULL_SCREEN = 3

export type LeagueWindowProbe = () => LeagueWindowInfo | null

let cachedProbe: LeagueWindowProbe | null = null
let cache: { at: number; value: LeagueWindowInfo | null } | null = null
let lastPowerShellAt = 0
let powerShellInFlight: Promise<LeagueWindowInfo | null> | null = null

/** Test seam: inject a fake bounds provider. */
export function setLeagueWindowProbeForTests(probe: LeagueWindowProbe | null): void {
  cachedProbe = probe
  cache = null
}

/** Clear caches (tests). */
export function resetLeagueWindowCache(): void {
  cache = null
  lastPowerShellAt = 0
  powerShellInFlight = null
}

/**
 * Synchronous lookup for the controller tick. Uses FindWindowW + short TTL cache.
 * Never runs PowerShell on the hot path (that was a major lag source).
 */
export function findLeagueClientWindow(): LeagueWindowInfo | null {
  if (cachedProbe !== null) {
    return cachedProbe()
  }
  if (process.platform !== 'win32') {
    return null
  }
  const now = Date.now()
  if (cache !== null && now - cache.at < LEAGUE_CACHE_MS) {
    return cache.value
  }
  let value: LeagueWindowInfo | null = null
  try {
    value = findViaFindWindow()
  } catch {
    value = null
  }
  cache = { at: now, value }
  if (value === null) {
    schedulePowerShellFallback()
  }
  return value
}

/** Async refresh used when FindWindow misses; never awaited on UI clicks. */
export async function refreshLeagueClientWindowAsync(): Promise<LeagueWindowInfo | null> {
  if (cachedProbe !== null) {
    return cachedProbe()
  }
  if (process.platform !== 'win32') {
    return null
  }
  try {
    const viaFind = findViaFindWindow()
    if (viaFind !== null) {
      cache = { at: Date.now(), value: viaFind }
      return viaFind
    }
  } catch {
    // fall through
  }
  const viaPs = await runPowerShellFallback()
  cache = { at: Date.now(), value: viaPs }
  return viaPs
}

export function isExclusiveD3dFullscreen(): boolean {
  if (process.platform !== 'win32') {
    return false
  }
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const koffi = require('koffi') as typeof import('koffi')
    const shell32 = koffi.load('shell32.dll')
    const SHQueryUserNotificationState = shell32.func(
      'long __stdcall SHQueryUserNotificationState(_Out_ int *pquns)'
    )
    const state = [0]
    const hr = SHQueryUserNotificationState(state)
    if (hr !== 0) {
      return false
    }
    return state[0] === QUNS_RUNNING_D3D_FULL_SCREEN
  } catch {
    return false
  }
}

export function classifyDisplayMode(input: {
  exclusiveD3d: boolean
  bounds: Rect
  displayBounds: Rect | null
}): LeagueDisplayMode {
  if (input.exclusiveD3d) {
    return 'exclusive_fullscreen'
  }
  if (input.displayBounds === null) {
    return 'unknown'
  }
  const covers =
    Math.abs(input.bounds.width - input.displayBounds.width) <= 2 &&
    Math.abs(input.bounds.height - input.displayBounds.height) <= 48 &&
    Math.abs(input.bounds.x - input.displayBounds.x) <= 2 &&
    Math.abs(input.bounds.y - input.displayBounds.y) <= 2
  return covers ? 'borderless' : 'windowed'
}

function findViaFindWindow(): LeagueWindowInfo | null {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const koffi = require('koffi') as typeof import('koffi')
  const user32 = koffi.load('user32.dll')
  koffi.struct('RECT', {
    left: 'long',
    top: 'long',
    right: 'long',
    bottom: 'long'
  })
  const FindWindowW = user32.func('void * __stdcall FindWindowW(void *lpClassName, str16 lpWindowName)')
  const IsWindowVisible = user32.func('bool __stdcall IsWindowVisible(void *hWnd)')
  const IsIconic = user32.func('bool __stdcall IsIconic(void *hWnd)')
  const GetWindowRect = user32.func('bool __stdcall GetWindowRect(void *hWnd, _Out_ RECT *lpRect)')
  const exclusive = isExclusiveD3dFullscreen()

  for (const title of LEAGUE_TITLES) {
    const hWnd = FindWindowW(null, title)
    if (!hWnd || !IsWindowVisible(hWnd)) {
      continue
    }
    const rect = {} as { left: number; top: number; right: number; bottom: number }
    if (!GetWindowRect(hWnd, rect)) {
      continue
    }
    const bounds = toBounds(rect)
    if (bounds.width < 640 || bounds.height < 480) {
      continue
    }
    return {
      bounds,
      minimized: Boolean(IsIconic(hWnd)),
      title,
      displayMode: exclusive ? 'exclusive_fullscreen' : 'unknown'
    }
  }
  return null
}

function schedulePowerShellFallback(): void {
  const now = Date.now()
  if (now - lastPowerShellAt < POWERSHELL_FALLBACK_COOLDOWN_MS) {
    return
  }
  if (powerShellInFlight !== null) {
    return
  }
  lastPowerShellAt = now
  powerShellInFlight = runPowerShellFallback().finally(() => {
    powerShellInFlight = null
  })
  void powerShellInFlight.then((value) => {
    if (value !== null) {
      cache = { at: Date.now(), value }
    }
  })
}

async function runPowerShellFallback(): Promise<LeagueWindowInfo | null> {
  const script = `
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class RiftLeagueWin {
  public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder sb, int max);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
}
"@
$found = $null
[RiftLeagueWin]::EnumWindows({
  param($h, $l)
  if (-not [RiftLeagueWin]::IsWindowVisible($h)) { return $true }
  $sb = New-Object System.Text.StringBuilder 512
  if ([RiftLeagueWin]::GetWindowText($h, $sb, $sb.Capacity) -le 0) { return $true }
  $t = $sb.ToString()
  if ($t -notmatch 'League of Legends') { return $true }
  if ($t -match 'Riot Client') { return $true }
  $rect = New-Object RiftLeagueWin+RECT
  if (-not [RiftLeagueWin]::GetWindowRect($h, [ref]$rect)) { return $true }
  $w = $rect.Right - $rect.Left
  $hgt = $rect.Bottom - $rect.Top
  if ($w -lt 640 -or $hgt -lt 480) { return $true }
  $obj = [ordered]@{
    title = $t
    minimized = [bool]([RiftLeagueWin]::IsIconic($h))
    x = $rect.Left; y = $rect.Top; width = $w; height = $hgt
  }
  if ($t -like '*(TM) Client*' -or $null -eq $found) { $script:found = $obj }
  return $true
}, [IntPtr]::Zero) | Out-Null
if ($null -eq $found) { '' } else { $found | ConvertTo-Json -Compress }
`
  try {
    const { stdout } = await execFileAsync(
      'powershell.exe',
      ['-NoProfile', '-NonInteractive', '-Command', script],
      { encoding: 'utf8', windowsHide: true, timeout: 8_000 }
    )
    const trimmed = stdout.trim()
    if (!trimmed) {
      return null
    }
    const parsed = JSON.parse(trimmed) as {
      title: string
      minimized: boolean
      x: number
      y: number
      width: number
      height: number
    }
    const exclusive = isExclusiveD3dFullscreen()
    return {
      title: parsed.title,
      minimized: parsed.minimized,
      bounds: {
        x: parsed.x,
        y: parsed.y,
        width: parsed.width,
        height: parsed.height
      },
      displayMode: exclusive ? 'exclusive_fullscreen' : 'unknown'
    }
  } catch {
    return null
  }
}

function toBounds(rect: { left: number; top: number; right: number; bottom: number }): Rect {
  return {
    x: rect.left,
    y: rect.top,
    width: Math.max(0, rect.right - rect.left),
    height: Math.max(0, rect.bottom - rect.top)
  }
}

export function isLeagueTitle(title: string): boolean {
  const normalized = title.trim()
  if (normalized.length === 0) {
    return false
  }
  if (/riot client/i.test(normalized)) {
    return false
  }
  return LEAGUE_TITLES.some((hint) => normalized.includes(hint))
}

/** Visibility policy used by the controller (pure, testable). */
export function shouldShowOverlay(input: {
  prefsEnabled: boolean
  liveGame: boolean
  hasContext: boolean
  sessionActive: boolean
  league: LeagueWindowInfo | null
  missingPolls: number
  gracePolls?: number
  exclusiveFullscreen?: boolean
}): { visible: boolean; reason: string } {
  if (!input.prefsEnabled) {
    return { visible: false, reason: 'prefs_disabled' }
  }
  if (input.liveGame) {
    return { visible: false, reason: 'live_game' }
  }
  if (!input.hasContext) {
    return { visible: false, reason: 'no_context' }
  }
  if (!input.sessionActive) {
    return { visible: false, reason: 'session_inactive' }
  }
  if (
    input.exclusiveFullscreen === true ||
    input.league?.displayMode === 'exclusive_fullscreen'
  ) {
    return { visible: false, reason: 'exclusive_fullscreen' }
  }
  if (input.league === null) {
    const grace = input.gracePolls ?? 3
    if (input.missingPolls > grace) {
      return { visible: false, reason: 'league_missing' }
    }
    return { visible: true, reason: 'league_grace' }
  }
  if (input.league.minimized) {
    return { visible: false, reason: 'league_minimized' }
  }
  return { visible: true, reason: 'ok' }
}

export function isReplaySessionActive(phase: string | null | undefined, reachedReady: boolean): boolean {
  if (!reachedReady) {
    return false
  }
  return phase === 'READY' || phase === 'PLAYING' || phase === 'PAUSED' || phase === 'SEEKING'
}
