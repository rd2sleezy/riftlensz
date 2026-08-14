/**
 * League client window discovery (R.10.5).
 *
 * Platform branching stays here:
 * - win32: FindWindowW + rare PowerShell fallback + D3D exclusive probe
 * - darwin: System Events bounds + process/primary-display fallback
 *
 * Detects exclusive D3D fullscreen on Windows via SHQueryUserNotificationState
 * (no process injection).
 */

import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import type { LeagueWindowInfo, Rect } from './types'
import { LEAGUE_CACHE_MS, POWERSHELL_FALLBACK_COOLDOWN_MS } from './types'
import {
  findLeagueClientWindowDarwin,
  isExclusiveFullscreenDarwin,
  refreshLeagueClientWindowDarwinAsync,
  resetDarwinLeagueWindowCache
} from './leagueWindow.darwin'
import {
  classifyDisplayMode,
  isLeagueTitle,
  isReplaySessionActive,
  shouldShowOverlay
} from './leagueWindow.shared'

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
  resetDarwinLeagueWindowCache()
}

/** Clear caches (tests). */
export function resetLeagueWindowCache(): void {
  cache = null
  lastPowerShellAt = 0
  powerShellInFlight = null
  resetDarwinLeagueWindowCache()
}

/**
 * Synchronous lookup for the controller tick. Uses FindWindowW + short TTL cache
 * on Windows; darwin cache/async refresh on macOS.
 * Never runs PowerShell/osascript on the hot path.
 */
export function findLeagueClientWindow(): LeagueWindowInfo | null {
  if (cachedProbe !== null) {
    return cachedProbe()
  }
  if (process.platform === 'darwin') {
    return findLeagueClientWindowDarwin()
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
  if (process.platform === 'darwin') {
    return refreshLeagueClientWindowDarwinAsync()
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
  if (process.platform === 'darwin') {
    return isExclusiveFullscreenDarwin()
  }
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

export {
  classifyDisplayMode,
  isLeagueTitle,
  isReplaySessionActive,
  shouldShowOverlay
}

export { getDarwinLeagueProbeMeta, MAC_LEAGUE_BOUNDS_PERMISSION_MESSAGE } from './leagueWindow.darwin'
