/**
 * Mac overlay acceptance helpers (no Electron BrowserWindow).
 * Verifies capability, HUD-safe default placement, hotkeys, and seek targets
 * for the real NA1_5620410094 review — seeks themselves run via Python MacReplayHost.
 */

import { readFileSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { resolveOverlayHotkey } from '../../apps/desktop/src/main/overlay/hotkeys'
import {
  overlayCompanionSupported,
  overlayWindowOptionsForPlatform
} from '../../apps/desktop/src/main/overlay/platform'
import { isHudSafe, resolveLauncherRect, resolveOverlayRect } from '../../apps/desktop/src/main/overlay/placement'
import { DEFAULT_OVERLAY_PREFS } from '../../apps/desktop/src/main/overlay/types'
import { isReplaySessionActive } from '../../apps/desktop/src/main/overlay/leagueWindow.shared'

const REVIEW = join(
  homedir(),
  '.riftlens-integrate-ui-r1/reviews/01KZWSX7ZSADJD58K10MASN1BX.json'
)
const OUT = join(__dirname, 'mac_overlay_acceptance.json')
const LEAD_IN_MS = 8_000

type ReviewJson = {
  match_id: string
  fixture_id: string | null
  sync_map: unknown
  focus_items: Array<{
    title: string
    exemplar: { t_ms: number; t_mmss?: string }
  }>
}

function main(): void {
  const review = JSON.parse(readFileSync(REVIEW, 'utf8')) as ReviewJson
  const league = { x: 0, y: 0, width: 1512, height: 982 }
  const work = league
  const overlay = resolveOverlayRect({
    league,
    workArea: work,
    prefs: DEFAULT_OVERLAY_PREFS,
    height: 440
  })
  const launcher = resolveLauncherRect({
    league,
    workArea: work,
    launcherPosition: null
  })
  const seeks = review.focus_items.slice(0, 3).map((item, index) => {
    const expected = item.exemplar.t_ms
    return {
      index: index + 1,
      title: item.title,
      expected_t_ms: expected,
      t_mmss: item.exemplar.t_mmss ?? null,
      lead_in_ms: LEAD_IN_MS,
      expected_replay_target_ms: expected - LEAD_IN_MS
    }
  })
  const report = {
    match_id: review.match_id,
    fixture_involved: review.fixture_id != null && review.fixture_id !== '',
    sync_map_involved: review.sync_map != null,
    overlay_companion_supported_darwin: overlayCompanionSupported('darwin'),
    overlay_window_options: overlayWindowOptionsForPlatform('darwin'),
    replay_only: {
      playing_ready: isReplaySessionActive('PLAYING', true),
      idle_blocked: !isReplaySessionActive('IDLE', true),
      live_not_used: true
    },
    placement: {
      league,
      overlay,
      launcher,
      overlay_hud_safe: isHudSafe(league, overlay),
      launcher_hud_safe: isHudSafe(league, launcher)
    },
    hotkeys: {
      prev: resolveOverlayHotkey({
        key: '[',
        code: 'BracketLeft',
        altKey: true,
        metaKey: false,
        ctrlKey: false,
        shiftKey: false,
        repeat: false
      }),
      next: resolveOverlayHotkey({
        key: ']',
        code: 'BracketRight',
        altKey: true,
        metaKey: false,
        ctrlKey: false,
        shiftKey: false,
        repeat: false
      }),
      seek: resolveOverlayHotkey({
        key: 'Enter',
        code: 'Enter',
        altKey: true,
        metaKey: false,
        ctrlKey: false,
        shiftKey: false,
        repeat: false
      }),
      minimize: resolveOverlayHotkey({
        key: 'h',
        code: 'KeyH',
        altKey: true,
        metaKey: false,
        ctrlKey: false,
        shiftKey: false,
        repeat: false
      })
    },
    seek_plan: seeks,
    note:
      'Live Open Replay + verified clock deltas are recorded by mac_install_seek_acceptance.py; this report locks overlay contracts for the same review.'
  }
  writeFileSync(OUT, `${JSON.stringify(report, null, 2)}\n`, 'utf8')
  console.log(JSON.stringify(report, null, 2))
  if (
    !report.overlay_companion_supported_darwin ||
    !report.placement.overlay_hud_safe ||
    report.fixture_involved ||
    report.sync_map_involved
  ) {
    process.exit(1)
  }
}

main()
