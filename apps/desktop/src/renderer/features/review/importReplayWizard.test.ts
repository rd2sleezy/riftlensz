import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { replayErrorView } from './replayErrors'

describe('ImportReplayWizard ingest flow', () => {
  const wizard = readFileSync(path.join(__dirname, './ImportReplayWizard.tsx'), 'utf8')

  it('calls ingestMatch when the user clicks Ingest this match', () => {
    expect(wizard).toContain('runIngestMatch')
    expect(wizard).toContain("actionId === 'ingest_match'")
    expect(wizard).toContain('void runIngestMatch()')
    expect(wizard).toContain('window.rift.ingestMatch(replayMatchId)')
  })

  it('shows MATCH_NOT_INGESTED before auto-advancing to participant picker', () => {
    expect(wizard).toContain("imported.code === 'MATCH_NOT_INGESTED'")
    expect(wizard).toContain('failWith(imported.code, imported.message, imported.suggested_action)')
  })

  it('surfaces expired Riot credential instead of looping ingest', () => {
    const view = replayErrorView({
      code: 'RIOT_CREDENTIAL_MISSING',
      message: 'your Riot API key may have expired — development keys expire every 24 hours'
    })
    expect(view.actionId).toBe('sign_in_api_key')
    expect(view.message.toLowerCase()).toContain('expired')
  })

  it('does not reference fixture fallback in the wizard', () => {
    expect(wizard.toLowerCase()).not.toContain('from-fixture')
    expect(wizard.toLowerCase()).not.toContain('fixture_a')
  })
})
