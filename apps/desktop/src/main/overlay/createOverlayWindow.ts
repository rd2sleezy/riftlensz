/** Create the frameless always-on-top coaching overlay BrowserWindow (R.10.5). */

import { join } from 'node:path'
import { BrowserWindow, screen } from 'electron'
import { logger } from '../logging'
import { applyOverlayWindowChrome, overlayWindowOptionsForPlatform } from './platform'
import { NAVIGATOR_HEIGHT, type Rect } from './types'

export type CreateOverlayWindowOptions = {
  preloadPath: string
  /** Dev server origin for the main renderer (electron-vite). Overlay loads `/overlay.html`. */
  rendererDevUrl: string | null
  initialBounds: Rect
  onMoved: (bounds: Rect) => void
  platform?: NodeJS.Platform
}

export function createOverlayWindow(options: CreateOverlayWindowOptions): BrowserWindow {
  const platform = options.platform ?? process.platform
  const platformOpts = overlayWindowOptionsForPlatform(platform)
  // Intentionally NOT parented to the RiftLens main window — a parented child
  // stays tied to the main app Space/z-order on macOS.
  const win = new BrowserWindow({
    width: options.initialBounds.width,
    height: options.initialBounds.height,
    x: options.initialBounds.x,
    y: options.initialBounds.y,
    show: false,
    frame: platformOpts.frame,
    transparent: platformOpts.transparent,
    backgroundColor: '#00000000',
    resizable: platformOpts.resizable,
    maximizable: platformOpts.maximizable,
    minimizable: platformOpts.minimizable,
    fullscreenable: platformOpts.fullscreenable,
    skipTaskbar: platformOpts.skipTaskbar,
    alwaysOnTop: platformOpts.alwaysOnTop,
    hasShadow: platformOpts.hasShadow,
    focusable: platformOpts.focusable,
    ...(platformOpts.type !== undefined ? { type: platformOpts.type } : {}),
    webPreferences: {
      preload: options.preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true
    }
  })

  applyOverlayWindowChrome(win, platform)

  let dragMoved = false
  win.on('move', () => {
    dragMoved = true
  })
  win.on('moved', () => {
    if (!dragMoved) {
      return
    }
    dragMoved = false
    const position = win.getPosition()
    const size = win.getSize()
    options.onMoved({
      x: position[0] ?? 0,
      y: position[1] ?? 0,
      width: size[0] ?? NAVIGATOR_HEIGHT,
      height: size[1] ?? NAVIGATOR_HEIGHT
    })
  })

  void loadOverlay(win, options.rendererDevUrl)

  win.webContents.on('did-fail-load', (_event, code, desc) => {
    logger.error({ code, desc }, 'overlay failed to load')
  })

  return win
}

async function loadOverlay(win: BrowserWindow, rendererDevUrl: string | null): Promise<void> {
  if (rendererDevUrl) {
    const base = rendererDevUrl.replace(/\/$/, '')
    await win.loadURL(`${base}/overlay.html`)
    return
  }
  await win.loadFile(join(__dirname, '../renderer/overlay.html'))
}

export function applyOverlayBounds(win: BrowserWindow, bounds: Rect): void {
  win.setBounds({
    x: Math.round(bounds.x),
    y: Math.round(bounds.y),
    width: Math.round(bounds.width),
    height: Math.round(bounds.height)
  })
}

export function workAreaForRect(rect: Rect): Rect {
  const display = screen.getDisplayMatching({
    x: Math.round(rect.x),
    y: Math.round(rect.y),
    width: Math.max(1, Math.round(rect.width)),
    height: Math.max(1, Math.round(rect.height))
  })
  return {
    x: display.workArea.x,
    y: display.workArea.y,
    width: display.workArea.width,
    height: display.workArea.height
  }
}

export function primaryWorkArea(): Rect {
  const display = screen.getPrimaryDisplay()
  return {
    x: display.workArea.x,
    y: display.workArea.y,
    width: display.workArea.width,
    height: display.workArea.height
  }
}

export { NAVIGATOR_HEIGHT }
