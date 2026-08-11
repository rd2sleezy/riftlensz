import { describe, expect, it } from 'vitest'
import { onlyOverlayWindowsRemain } from './controller'

describe('overlay window bookkeeping', () => {
  it('detects when only companion overlay windows remain', () => {
    const overlay = { id: 1 } as never
    const main = { id: 2 } as never
    expect(onlyOverlayWindowsRemain([overlay], (win) => (win as { id: number }).id === 1)).toBe(true)
    expect(onlyOverlayWindowsRemain([overlay, main], (win) => (win as { id: number }).id === 1)).toBe(
      false
    )
    expect(onlyOverlayWindowsRemain([], () => true)).toBe(false)
  })
})
