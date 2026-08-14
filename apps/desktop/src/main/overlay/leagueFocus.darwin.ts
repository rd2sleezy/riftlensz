/**
 * Restore League replay focus on macOS after overlay chrome actions.
 *
 * Uses NSRunningApplication.activate — not keystroke injection, not AppleScript
 * System Events UI scripting. Replay-only callers must gate this themselves.
 */

import { execFile } from 'node:child_process'
import { promisify } from 'node:util'

const execFileAsync = promisify(execFile)

export type LeagueFocusRestoreResult = {
  ok: boolean
  method: 'nsrunningapplication' | 'none'
  appName: string | null
  error: string | null
}

/**
 * Activate the League of Legends game process if it is running.
 * Skips Riot Client. Never fabricates keystrokes.
 */
export async function restoreLeagueReplayFocusDarwin(): Promise<LeagueFocusRestoreResult> {
  if (process.platform !== 'darwin') {
    return { ok: false, method: 'none', appName: null, error: 'not_darwin' }
  }
  const script = `
ObjC.import('AppKit');
ObjC.import('Foundation');
var running = $.NSWorkspace.sharedWorkspace.runningApplications;
var count = running.count;
var chosen = null;
var chosenName = null;
for (var i = 0; i < count; i++) {
  var app = running.objectAtIndex(i);
  var name = ObjC.unwrap(app.localizedName) || '';
  var bundle = ObjC.unwrap(app.bundleIdentifier) || '';
  if (/riot\\s*client/i.test(name) || /riotclient/i.test(bundle)) continue;
  var isGame =
    name === 'LeagueofLegends' ||
    /^league of legends$/i.test(name) ||
    /leagueoflegends/i.test(bundle);
  if (!isGame) continue;
  chosen = app;
  chosenName = name;
  if (name === 'LeagueofLegends') break;
}
if (!chosen) {
  JSON.stringify({ ok: false, appName: null });
} else {
  // NSApplicationActivateIgnoringOtherApps = 1 << 1
  chosen.activateWithOptions(2);
  JSON.stringify({ ok: true, appName: chosenName });
}
`
  try {
    const { stdout } = await execFileAsync(
      '/usr/bin/osascript',
      ['-l', 'JavaScript', '-e', script],
      { encoding: 'utf8', timeout: 3_000 }
    )
    const parsed = JSON.parse(stdout.trim()) as { ok: boolean; appName: string | null }
    return {
      ok: parsed.ok === true,
      method: parsed.ok ? 'nsrunningapplication' : 'none',
      appName: parsed.appName,
      error: parsed.ok ? null : 'league_app_not_running'
    }
  } catch (error) {
    return {
      ok: false,
      method: 'none',
      appName: null,
      error: error instanceof Error ? error.message : String(error)
    }
  }
}
