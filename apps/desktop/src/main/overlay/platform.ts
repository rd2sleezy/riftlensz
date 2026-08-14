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
  alwaysOnTopLevel: 'screen-saver' | 'floating' | 'normal' | 'pop-up-menu' | 'status'
  /** macOS relativeLevel for setAlwaysOnTop (0–1 recommended). */
  alwaysOnTopRelativeLevel: number
  visibleOnAllWorkspaces: boolean
  visibleOnFullScreen: boolean
  /** macOS-only Electron window type when supported. */
  type?: 'panel'
}

/**
 * Centralize darwin/win32 overlay window branching.
 * Renderer code must not read `process.platform` for overlay chrome.
 *
 * macOS note: levels from `floating` through `status` sit *below* the Dock and
 * typically below a Metal game window. Use `screen-saver` so the companion sits
 * above League in Windowed/Borderless.
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
      alwaysOnTopLevel: 'screen-saver',
      alwaysOnTopRelativeLevel: 1,
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
    alwaysOnTopRelativeLevel: 0,
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

/**
 * Apply macOS/Windows chrome that must stick after create/show/relayout.
 * Never parents the overlay to the main BrowserWindow.
 */
export function applyOverlayWindowChrome(
  win: {
    setFullScreenable: (allow: boolean) => void
    setVisibleOnAllWorkspaces: (
      visible: boolean,
      opts?: { visibleOnFullScreen?: boolean }
    ) => void
    setAlwaysOnTop: (
      flag: boolean,
      level?: OverlayWindowPlatformOptions['alwaysOnTopLevel'],
      relativeLevel?: number
    ) => void
    moveTop?: () => void
    setIgnoreMouseEvents: (ignore: boolean) => void
  },
  platform: NodeJS.Platform = process.platform
): OverlayWindowPlatformOptions {
  const opts = overlayWindowOptionsForPlatform(platform)
  // FullScreenAuxiliary collection behavior (required for Space/fullscreen compositing).
  win.setFullScreenable(opts.fullscreenable)
  if (opts.visibleOnAllWorkspaces) {
    win.setVisibleOnAllWorkspaces(true, {
      visibleOnFullScreen: opts.visibleOnFullScreen
    })
  }
  win.setAlwaysOnTop(true, opts.alwaysOnTopLevel, opts.alwaysOnTopRelativeLevel)
  win.setIgnoreMouseEvents(false)
  if (typeof win.moveTop === 'function') {
    win.moveTop()
  }
  return opts
}
