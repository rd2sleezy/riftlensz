import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { replayErrorView } from './replayErrors'

describe('production home / fixture separation', () => {
  const dashboard = readFileSync(path.join(__dirname, '../home/Dashboard.tsx'), 'utf8')
  const reviewScreen = readFileSync(path.join(__dirname, './ReviewScreen.tsx'), 'utf8')
  const wizard = readFileSync(path.join(__dirname, './ImportReplayWizard.tsx'), 'utf8')

  it('shows a zero-review empty state with Import League Replay', () => {
    expect(dashboard).toContain('No matches reviewed yet.')
    expect(dashboard).toContain('Import League Replay')
    expect(dashboard).toContain('home-empty-state')
    expect(dashboard).toContain('home-empty-import')
    expect(dashboard).toContain('home-import-replay')
  })

  it('keeps fixture open controls behind e2eMode only', () => {
    expect(dashboard).toContain('e2eMode')
    expect(dashboard).toContain('dev-fixtures')
    expect(dashboard).toMatch(/e2eMode \? \(/)
    expect(dashboard).not.toMatch(/Open a fixture review/)
  })

  it('starts .rofl import from home with no open review match id', () => {
    expect(dashboard).toContain('matchId=""')
    expect(dashboard).toContain('ImportReplayWizard')
    expect(wizard).toContain('importReplay(picked.path, null)')
  })

  it('redirects fixture deep-links out of production ReviewScreen', () => {
    expect(reviewScreen).toContain("matchId.startsWith('NA1_fixture_')")
    expect(reviewScreen).toContain("window.location.hash = '#/'")
    expect(reviewScreen).toContain('e2eMode')
  })

  it('surfaces Riot credential missing without fixture fallback', () => {
    const view = replayErrorView({ code: 'RIOT_CREDENTIAL_MISSING' })
    expect(view.message).toBe('Riot access is required to download this match.')
    expect(view.actionId).toBe('sign_in_api_key')
    expect(wizard.toLowerCase()).not.toContain('from-fixture')
  })
})
