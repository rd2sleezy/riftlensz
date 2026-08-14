export type {
  LeagueDisplayMode,
  OverlayContext,
  OverlayPrefs,
  Rect
} from './types'
export {
  DEFAULT_OVERLAY_PREFS,
  EXCLUSIVE_FULLSCREEN_MESSAGE,
  LAUNCHER_HEIGHT,
  LAUNCHER_WIDTH,
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
  resolveCompatRect,
  resolveLauncherRect,
  resolveOverlayLayout,
  resolveOverlayRect
} from './placement'
export {
  displayModeSwitchPolicy,
  BORDERLESS_REQUIRED_MESSAGE,
  MAC_BORDERLESS_STEPS
} from './displayModeAssist'
export {
  overlayCompanionSupported,
  overlayWindowOptionsForPlatform,
  applyOverlayWindowChrome
} from './platform'
export {
  OVERLAY_HOTKEY_HELP,
  resolveOverlayHotkey,
  type OverlayHotkeyAction
} from './hotkeys'
export {
  effectiveOverlayPresentation,
  nextUserIntent,
  resolveOverlayPresentation,
  type OverlayPresentation,
  type OverlayUserIntent
} from './visibilityState'
export { HUD_EXCLUSION_ZONES, absoluteZone, overlapsAnyHudZone } from './hudZones'
export { loadOverlayPrefs, mergeOverlayPrefs, saveOverlayPrefs } from './prefs'
