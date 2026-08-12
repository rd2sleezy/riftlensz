import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  BORDERLESS_REQUIRED_MESSAGE,
  displayModeSwitchPolicy,
  shouldOfferRememberChoice
} from './displayModeAssist'

describe('fullscreen display-mode assist', () => {
  it('does not offer automatic Borderless switching or remember-choice', () => {
    const policy = displayModeSwitchPolicy()
    expect(policy.automaticSwitchAvailable).toBe(false)
    expect(policy.rememberChoiceAvailable).toBe(false)
    expect(shouldOfferRememberChoice(policy)).toBe(false)
    expect(policy.playerMessage).toBe(BORDERLESS_REQUIRED_MESSAGE)
    expect(policy.steps).toHaveLength(3)
    expect(policy.liveMatchSafe).toBe(true)
  })

  it('never writes WindowMode, sends key input, or injects into League', () => {
    const roots = [
      'controller.ts',
      'leagueWindow.ts',
      'displayModeAssist.ts',
      'createOverlayWindow.ts',
      '../index.ts'
    ]
    for (const file of roots) {
      const source = readFileSync(path.join(__dirname, file), 'utf8')
      expect(source).not.toMatch(/WindowMode\s*=/)
      expect(source).not.toMatch(/keybd_event|SendInput|SendKeys|keybdEvent/i)
      expect(source).not.toMatch(/WriteProcessMemory|SetWindowsHook|dll inject/i)
      expect(source).not.toMatch(/EnableReplayApi/)
    }
  })
})
