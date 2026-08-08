import { z } from 'zod'

export const IPC = {
  getSidecarStatus: 'rift:sidecar:get-status',
  sidecarStatusEvent: 'rift:sidecar:status',
  health: 'rift:sidecar:health',
  restartSidecar: 'rift:sidecar:restart'
} as const

export const SidecarStateSchema = z.enum([
  'starting',
  'ready',
  'unhealthy',
  'restarting',
  'failed'
])

export const SidecarStatusSchema = z.object({
  state: SidecarStateSchema,
  version: z.string().optional(),
  port: z.number().int().optional(),
  pid: z.number().int().optional(),
  dbPath: z.string().optional(),
  error: z.string().optional()
})

export const HealthSchema = z.object({
  status: z.literal('ok'),
  version: z.string(),
  python: z.string(),
  db_path: z.string(),
  uptime_ms: z.number().int()
})

export type SidecarState = z.infer<typeof SidecarStateSchema>
export type SidecarStatus = z.infer<typeof SidecarStatusSchema>
export type HealthPayload = z.infer<typeof HealthSchema>
