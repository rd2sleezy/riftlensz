/**
 * Overlay-local hotkeys (R.10.5).
 *
 * These fire only while the overlay BrowserWindow has keyboard focus.
 * Do not use Electron global shortcuts — League must keep Esc/Space/transport.
 */

export type OverlayHotkeyAction =
  | 'prev_item'
  | 'next_item'
  | 'seek_selected'
  | 'minimize'
  | 'expand'

export type OverlayHotkeyEvent = {
  key: string
  code: string
  altKey: boolean
  metaKey: boolean
  ctrlKey: boolean
  shiftKey: boolean
  repeat: boolean
}

/**
 * Resolve a focused-overlay key event to a semantic action.
 * Alt/Option modifiers work on both Windows and macOS (event.altKey).
 */
export function resolveOverlayHotkey(event: OverlayHotkeyEvent): OverlayHotkeyAction | null {
  if (event.repeat) {
    return null
  }
  // Avoid Escape and bare Space (League / replay transport).
  if (event.code === 'Escape' || event.code === 'Space') {
    return null
  }
  if (event.altKey && !event.metaKey && !event.ctrlKey) {
    if (event.code === 'BracketLeft' || event.code === 'ArrowUp') {
      return 'prev_item'
    }
    if (event.code === 'BracketRight' || event.code === 'ArrowDown') {
      return 'next_item'
    }
    if (event.code === 'Enter') {
      return 'seek_selected'
    }
    if (event.code === 'KeyH') {
      return 'minimize'
    }
    if (event.code === 'KeyO') {
      return 'expand'
    }
  }
  // When overlay chrome is focused, arrows alone navigate without modifiers.
  if (!event.altKey && !event.metaKey && !event.ctrlKey && !event.shiftKey) {
    if (event.code === 'ArrowUp') {
      return 'prev_item'
    }
    if (event.code === 'ArrowDown') {
      return 'next_item'
    }
    if (event.code === 'Enter') {
      return 'seek_selected'
    }
  }
  return null
}

export const OVERLAY_HOTKEY_HELP = [
  'Alt+[ / ArrowUp — previous coaching item',
  'Alt+] / ArrowDown — next coaching item',
  'Alt+Enter / Enter — seek selected item',
  'Alt+H — minimize to Access Overlay',
  'Alt+O — expand Access Overlay'
] as const
