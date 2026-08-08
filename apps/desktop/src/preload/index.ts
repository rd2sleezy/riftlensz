import { contextBridge, ipcRenderer } from 'electron'
import {
  HealthSchema,
  IPC,
  SidecarStatusSchema,
  type HealthPayload,
  type SidecarStatus
} from '../main/ipc/channels'

const rift = {
  getSidecarStatus(): Promise<SidecarStatus> {
    return ipcRenderer.invoke(IPC.getSidecarStatus).then((value) => SidecarStatusSchema.parse(value))
  },
  onSidecarStatus(cb: (status: SidecarStatus) => void): () => void {
    const listener = (_event: Electron.IpcRendererEvent, value: unknown): void => {
      cb(SidecarStatusSchema.parse(value))
    }
    ipcRenderer.on(IPC.sidecarStatusEvent, listener)
    return () => {
      ipcRenderer.removeListener(IPC.sidecarStatusEvent, listener)
    }
  },
  health(): Promise<HealthPayload> {
    return ipcRenderer.invoke(IPC.health).then((value) => HealthSchema.parse(value))
  },
  restartSidecar(): Promise<SidecarStatus> {
    return ipcRenderer.invoke(IPC.restartSidecar).then((value) => SidecarStatusSchema.parse(value))
  }
}

contextBridge.exposeInMainWorld('rift', rift)
