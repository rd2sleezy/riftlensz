import { BrowserWindow, ipcMain } from 'electron'
import { HealthSchema, IPC, SidecarStatusSchema } from './channels'
import type { SidecarSupervisor } from '../sidecar/supervisor'
import { logger } from '../logging'

/** Register IPC handlers. Assumes supervisor.start() will run around the same time. */
export function registerIpcHandlers(supervisor: SidecarSupervisor): void {
  ipcMain.removeHandler(IPC.getSidecarStatus)
  ipcMain.removeHandler(IPC.health)
  ipcMain.removeHandler(IPC.restartSidecar)

  ipcMain.handle(IPC.getSidecarStatus, () => {
    return SidecarStatusSchema.parse(supervisor.getStatus())
  })

  ipcMain.handle(IPC.health, async () => {
    const payload = await supervisor.health()
    return HealthSchema.parse(payload)
  })

  ipcMain.handle(IPC.restartSidecar, async () => {
    logger.info('manual sidecar restart requested')
    await supervisor.restart()
    return SidecarStatusSchema.parse(supervisor.getStatus())
  })

  supervisor.on('status', (status) => {
    const parsed = SidecarStatusSchema.parse(status)
    for (const win of BrowserWindow.getAllWindows()) {
      win.webContents.send(IPC.sidecarStatusEvent, parsed)
    }
  })
}
