/** Overlay UX preference persistence (R.10.5). No live-session state. */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { z } from 'zod'
import { DEFAULT_OVERLAY_PREFS, type OverlayPrefs } from './types'

const OverlayPrefsSchema = z
  .object({
    enabled: z.boolean(),
    detailOpen: z.boolean().optional(),
    /** Legacy R.10.5 field — maps to !detailOpen when detailOpen absent. */
    compact: z.boolean().optional(),
    opacity: z.number().min(0.4).max(1),
    position: z
      .object({
        x: z.number(),
        y: z.number()
      })
      .nullable(),
    launcherPosition: z
      .object({
        x: z.number(),
        y: z.number()
      })
      .nullable()
      .optional(),
    navigatorWidth: z.number().int().min(240).max(480).optional(),
    detailWidth: z.number().int().min(280).max(520).optional(),
    /** Legacy single width. */
    width: z.number().int().min(240).max(640).optional(),
    displayId: z.number().int().nullable()
  })
  .transform((raw): OverlayPrefs => {
    const detailOpen =
      raw.detailOpen ?? (raw.compact === undefined ? true : !raw.compact)
    return {
      enabled: raw.enabled,
      detailOpen,
      opacity: raw.opacity,
      position: raw.position,
      launcherPosition: raw.launcherPosition ?? null,
      navigatorWidth: raw.navigatorWidth ?? raw.width ?? DEFAULT_OVERLAY_PREFS.navigatorWidth,
      detailWidth: raw.detailWidth ?? DEFAULT_OVERLAY_PREFS.detailWidth,
      displayId: raw.displayId
    }
  })

export function prefsPath(userDataPath: string): string {
  return join(userDataPath, 'overlay-prefs.json')
}

export function loadOverlayPrefs(userDataPath: string): OverlayPrefs {
  const path = prefsPath(userDataPath)
  if (!existsSync(path)) {
    return { ...DEFAULT_OVERLAY_PREFS }
  }
  try {
    const raw = JSON.parse(readFileSync(path, 'utf8')) as unknown
    return OverlayPrefsSchema.parse(raw)
  } catch {
    return { ...DEFAULT_OVERLAY_PREFS }
  }
}

export function saveOverlayPrefs(userDataPath: string, prefs: OverlayPrefs): OverlayPrefs {
  const parsed = OverlayPrefsSchema.parse(prefs)
  const path = prefsPath(userDataPath)
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, `${JSON.stringify(parsed, null, 2)}\n`, 'utf8')
  return parsed
}

export function mergeOverlayPrefs(
  current: OverlayPrefs,
  patch: Partial<OverlayPrefs>
): OverlayPrefs {
  return OverlayPrefsSchema.parse({ ...current, ...patch })
}
