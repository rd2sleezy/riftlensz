import type { HealthPayload, SidecarStatus } from '../main/ipc/channels'

export interface RiftApi {
  getSidecarStatus: () => Promise<SidecarStatus>
  onSidecarStatus: (cb: (status: SidecarStatus) => void) => () => void
  health: () => Promise<HealthPayload>
  restartSidecar: () => Promise<SidecarStatus>
}

declare global {
  interface Window {
    rift: RiftApi
  }
}

export {}
