/** Platform-specific BrowserWindow options for the R.10.5 coaching overlay. */

export type OverlayWindowPlatformOptions = {
  alwaysOnTop: true
  frame: false
  transparent: true
  skipTaskbar: true
  fullscreenable: false
  focusable: true
  hasShadow: false
  resizable: false
  maximizable: false
  minimizable: false
  /** Electron always-on-top level. */
  alwaysOnTopLevel: 'screen-saver' | 'floating' | 'normal' | 'pop-up-menu'
  visibleOnAllWorkspaces: boolean
  visibleOnFullScreen: boolean
  /** macOS-only Electron window type when supported. */
  type?: 'panel'
}

/**
 * Centralize darwin/win32 overlay window branching.
 * Renderer code must not read `process.platform` for overlay chrome.
 */
export function overlayWindowOptionsForPlatform(
  platform: NodeJS.Platform = process.platform
): OverlayWindowPlatformOptions {
  if (platform === 'darwin') {
    return {
      alwaysOnTop: true,
      frame: false,
      transparent: true,
      skipTaskbar: true,
      fullscreenable: false,
      focusable: true,
      hasShadow: false,
      resizable: false,
      maximizable: false,
      minimizable: false,
      alwaysOnTopLevel: 'floating',
      visibleOnAllWorkspaces: true,
      visibleOnFullScreen: true,
      type: 'panel'
    }
  }
  return {
    alwaysOnTop: true,
    frame: false,
    transparent: true,
    skipTaskbar: true,
    fullscreenable: false,
    focusable: true,
    hasShadow: false,
    resizable: false,
    maximizable: false,
    minimizable: false,
    alwaysOnTopLevel: 'screen-saver',
    visibleOnAllWorkspaces: true,
    visibleOnFullScreen: true
  }
}

/** True when the R.10.5 companion overlay is supported on this desktop platform. */
export function overlayCompanionSupported(
  platform: NodeJS.Platform = process.platform
): boolean {
  return platform === 'win32' || platform === 'darwin'
}
