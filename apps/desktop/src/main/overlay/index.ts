export type { OverlayContext, OverlayPrefs, Rect } from './types'
export { DEFAULT_OVERLAY_PREFS } from './types'
export { OverlayController, onlyOverlayWindowsRemain } from './controller'
export {
  findLeagueClientWindow,
  isLeagueTitle,
  isReplaySessionActive,
  setLeagueWindowProbeForTests,
  shouldShowOverlay
} from './leagueWindow'
export {
  clampToWorkArea,
  defaultOverlayRect,
  isHudSafe,
  physicalSizeForCss,
  resolveOverlayRect
} from './placement'
export { HUD_EXCLUSION_ZONES, absoluteZone, overlapsAnyHudZone } from './hudZones'
export { loadOverlayPrefs, mergeOverlayPrefs, saveOverlayPrefs } from './prefs'
