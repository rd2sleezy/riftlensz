/**
 * League client window discovery (R.10.5).
 * Win32 FindWindowW via koffi, with a PowerShell EnumWindows fallback.
 * No process injection.
 */

import { execFileSync } from 'node:child_process'
import type { LeagueWindowInfo, Rect } from './types'

const LEAGUE_TITLES = [
  'League of Legends (TM) Client',
  'League of Legends'
] as const

export type LeagueWindowProbe = () => LeagueWindowInfo | null

let cachedProbe: LeagueWindowProbe | null = null

/** Test seam: inject a fake bounds provider. */
export function setLeagueWindowProbeForTests(probe: LeagueWindowProbe | null): void {
  cachedProbe = probe
}

export function findLeagueClientWindow(): LeagueWindowInfo | null {
  if (cachedProbe !== null) {
    return cachedProbe()
  }
  if (process.platform !== 'win32') {
    return null
  }
  try {
    return findViaFindWindow() ?? findViaPowerShell()
  } catch {
    try {
      return findViaPowerShell()
    } catch {
      return null
    }
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
      title
    }
  }
  return null
}

function findViaPowerShell(): LeagueWindowInfo | null {
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
  const stdout = execFileSync(
    'powershell.exe',
    ['-NoProfile', '-NonInteractive', '-Command', script],
    { encoding: 'utf8', windowsHide: true, timeout: 8_000 }
  ).trim()
  if (!stdout) {
    return null
  }
  const parsed = JSON.parse(stdout) as {
    title: string
    minimized: boolean
    x: number
    y: number
    width: number
    height: number
  }
  return {
    title: parsed.title,
    minimized: parsed.minimized,
    bounds: {
      x: parsed.x,
      y: parsed.y,
      width: parsed.width,
      height: parsed.height
    }
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
