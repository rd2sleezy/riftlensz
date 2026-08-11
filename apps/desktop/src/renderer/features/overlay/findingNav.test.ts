import { describe, expect, it } from 'vitest'
import type { CoachingItem, ReviewPresentation } from '../../../main/ipc/channels'
import {
  buildOverlayNav,
  categoryLabel,
  coachingSections,
  findNavIndex,
  formatGameMmss,
  stepNav,
  stepTimestamp,
  timestampsForItem
} from './findingNav'

function item(partial: Partial<CoachingItem> & Pick<CoachingItem, 'id' | 'title'>): CoachingItem {
  return {
    root_concept_id: 'c',
    rank: 1,
    is_focus: false,
    is_strength: false,
    issue_type: 'timing',
    impact_score: 1,
    gold_equivalent: null,
    occurrences: 1,
    confidence: 0.8,
    certainty: 'HIGH',
    body: 'Body text',
    the_fix: 'Do this instead',
    next_game_check: 'Check next game',
    exemplar_finding_id: null,
    finding_ids: [],
    evidence_timestamps_ms: [60_000],
    timestamps: [],
    grouping_reason: 'x',
    cluster_id: 'cl',
    cost_summary: 'cost',
    exemplar: null,
    ...partial
  }
}

function review(overrides?: Partial<ReviewPresentation>): ReviewPresentation {
  return {
    id: 'rev',
    player_id: 'p',
    match_id: 'NA1_5617764200',
    participant_id: 9,
    champion: 'Kaisa',
    role: 'BOTTOM',
    rank: 'GOLD',
    patch: '16.15',
    duration_ms: 1_800_000,
    result: 'W',
    rule_pack_version: '1',
    engine_version: '1',
    llm_provider: 'none',
    status: 'complete',
    summary_text: null,
    unpaired_match_timeline: false,
    fixture_warning: null,
    created_at: 1,
    completed_at: 1,
    focus_items: [
      item({ id: 'f1', title: 'Focus A', is_focus: true, evidence_timestamps_ms: [10_000, 20_000] }),
      item({ id: 'f2', title: 'Focus B', is_focus: true }),
      item({ id: 'f3', title: 'Focus C', is_focus: true })
    ],
    secondary_items: [item({ id: 's1', title: 'Secondary' })],
    strengths: [
      item({
        id: 'st1',
        title: 'Strength',
        is_strength: true,
        the_fix: 'Keep doing this',
        next_game_check: 'Goal'
      })
    ],
    metrics: [],
    findings: [],
    sync_map: null,
    media: null,
    overall_scores: {},
    ...overrides
  }
}

describe('overlay finding navigation', () => {
  it('orders Focus, Secondary, then Strengths and supports prev/next', () => {
    const nav = buildOverlayNav(review())
    expect(nav.map((row) => row.item.id)).toEqual(['f1', 'f2', 'f3', 's1', 'st1'])
    expect(categoryLabel(nav[0]!.category)).toBe('Focus')
    expect(findNavIndex(nav, 's1')).toBe(3)
    expect(stepNav(nav, 0, -1)).toBe(4)
    expect(stepNav(nav, 4, 1)).toBe(0)
  })

  it('cycles multiple timestamps without reordering', () => {
    const stamps = timestampsForItem(review().focus_items[0]!)
    expect(stamps).toEqual([10_000, 20_000])
    expect(stepTimestamp(stamps, 0, 1)).toBe(1)
    expect(stepTimestamp(stamps, 1, 1)).toBe(0)
    expect(formatGameMmss(1110000)).toBe('18:30')
  })

  it('maps strength copy without an Instead section and issues with Why it matters', () => {
    const strength = review().strengths[0]!
    const sections = coachingSections(strength)
    expect(sections.map((s) => s.label)).toEqual([
      'What you did well',
      'Why it worked',
      'Keep doing this',
      'Next-game goal'
    ])
    const issue = review().focus_items[0]!
    const issueLabels = coachingSections(issue).map((s) => s.label)
    expect(issueLabels).toContain('What happened')
    expect(issueLabels).toContain('Why it matters')
    expect(issueLabels).toContain('What to do instead')
    expect(issueLabels).not.toContain('Instead')
  })
})

describe('overlay reveal contract', () => {
  it('uses gameplaySeek lead-in constant and never imports clock math helpers', async () => {
    const { DEFAULT_REVEAL_LEAD_IN_MS } = await import('../review/gameplaySeek')
    expect(DEFAULT_REVEAL_LEAD_IN_MS).toBe(8_000)
    const { readFileSync } = await import('node:fs')
    const { join } = await import('node:path')
    const source = readFileSync(join(__dirname, 'OverlayApp.tsx'), 'utf8')
    expect(source).toContain('revealGameplayTimestamp')
    expect(source).toContain('onActivate')
    expect(source).not.toMatch(/game_to_source|ClockMap|seekTarget\(/)
    expect(source).not.toMatch(/globalShortcut\.(register|registerAll)/)
    expect(source).not.toMatch(/from 'electron'/)
    expect(source).not.toMatch(/findLeagueClientWindow|powershell/i)
  })
})
