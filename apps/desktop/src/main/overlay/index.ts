export type {
  LeagueDisplayMode,
  OverlayContext,
  OverlayPrefs,
  Rect
} from './types'
export {
  DEFAULT_OVERLAY_PREFS,
  EXCLUSIVE_FULLSCREEN_MESSAGE,
  NAVIGATOR_HEIGHT
} from './types'
export { OverlayController, onlyOverlayWindowsRemain } from './controller'
export type { OverlayLifecycleEvent } from './controller'
export {
  classifyDisplayMode,
  findLeagueClientWindow,
  isExclusiveD3dFullscreen,
  isLeagueTitle,
  isReplaySessionActive,
  refreshLeagueClientWindowAsync,
  resetLeagueWindowCache,
  setLeagueWindowProbeForTests,
  shouldShowOverlay
} from './leagueWindow'
export {
  clampToWorkArea,
  combinedSize,
  defaultOverlayRect,
  isHudSafe,
  physicalSizeForCss,
  resolveOverlayLayout,
  resolveOverlayRect
} from './placement'
export { HUD_EXCLUSION_ZONES, absoluteZone, overlapsAnyHudZone } from './hudZones'
export { loadOverlayPrefs, mergeOverlayPrefs, saveOverlayPrefs } from './prefs'
