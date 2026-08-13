import { join } from 'node:path'
import { app, BrowserWindow, shell } from 'electron'
import { AuthService } from './auth/authService'
import { registerIpcHandlers } from './ipc/handlers'
import { logger } from './logging'
import { handleMediaProtocol, registerMediaScheme } from './media/protocol'
import { OverlayController, onlyOverlayWindowsRemain } from './overlay'
import { SidecarSupervisor } from './sidecar/supervisor'

registerMediaScheme()

const supervisor = new SidecarSupervisor()
const overlay = new OverlayController()
const authService = new AuthService()

function createWindow(): BrowserWindow {
  const mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true
    }
  })

  mainWindow.on('ready-to-show', () => {
    mainWindow.show()
  })

  mainWindow.webContents.setWindowOpenHandler((details) => {
    void shell.openExternal(details.url)
    return { action: 'deny' }
  })

  if (process.env['ELECTRON_RENDERER_URL']) {
    void mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    void mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }

  overlay.setMainWindow(mainWindow)
  mainWindow.on('closed', () => {
    overlay.setMainWindow(null)
    // Companion overlay must not outlive the main review app.
    overlay.close()
  })

  return mainWindow
}

app.whenReady().then(() => {
  handleMediaProtocol()
  authService.start()
  registerIpcHandlers(supervisor, overlay, authService)
  supervisor.start()
  createWindow()

  app.on('activate', () => {
    const windows = BrowserWindow.getAllWindows().filter((win) => !overlay.isOverlayWindow(win))
    if (windows.length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    overlay.close()
    app.quit()
  }
})

process.on('uncaughtException', (error) => {
  logger.error({ err: error }, 'uncaught exception')
})

export { onlyOverlayWindowsRemain }
