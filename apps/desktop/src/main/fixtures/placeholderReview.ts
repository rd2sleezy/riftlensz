import type { CoachingItem, Finding, ReviewPresentation } from '../ipc/channels'

/**
 * Static stand-in for the H.8 sidecar review, used only when NA1_fixture_b is
 * requested and the Python analysis sidecar is unreachable. Lets UI work
 * proceed without a local Python/uv setup. Clearly labeled via
 * fixture_warning/title so it's never mistaken for a real analysis result.
 */
export const PLACEHOLDER_FIXTURE_B_REVIEW_ID = 'placeholder-fixture-b'

function coachingItem(overrides: Partial<CoachingItem> & Pick<CoachingItem, 'id' | 'title' | 'body'>): CoachingItem {
  return {
    root_concept_id: 'LANING.FARM',
    rank: 1,
    is_focus: true,
    is_strength: false,
    issue_type: 'placeholder',
    impact_score: 0.5,
    gold_equivalent: null,
    occurrences: 1,
    confidence: 0.5,
    certainty: 'medium',
    the_fix: null,
    next_game_check: null,
    exemplar_finding_id: null,
    finding_ids: [],
    evidence_timestamps_ms: [],
    timestamps: [],
    grouping_reason: 'Placeholder data — the analysis sidecar was unavailable when this was opened.',
    cluster_id: overrides.id,
    cost_summary: 'Placeholder',
    exemplar: null,
    ...overrides
  }
}

function placeholderFinding(id: string, t_ms: number, t_mmss: string, title: string): Finding {
  return {
    id,
    rule_id: 'PLACEHOLDER',
    rule_version: 0,
    concept_id: 'LANING.FARM',
    t_ms,
    t_end_ms: null,
    t_mmss,
    severity: 'info',
    confidence: 0.5,
    title,
    gold_equivalent: null,
    outcome: null,
    map_x: null,
    map_y: null,
    explanation: null,
    alternative: null,
    explanation_source: 'placeholder',
    suppressed: false,
    suppressed_by: null,
    evidence: [
      {
        kind: 'placeholder',
        label: 'note',
        value: 'No sidecar connection — this is static sample data.',
        source: 'placeholder',
        t_ms,
        confidence: null,
        provenance: null,
        quarantined: true
      }
    ]
  }
}

export function buildPlaceholderFixtureBReview(participantId: number, rank: string): ReviewPresentation {
  return {
    id: PLACEHOLDER_FIXTURE_B_REVIEW_ID,
    player_id: 'placeholder-player',
    match_id: 'NA1_PLACEHOLDER',
    participant_id: participantId,
    champion: 'Ahri',
    role: 'MIDDLE',
    rank,
    patch: '0.0.0',
    duration_ms: 1_874_000,
    result: 'WIN',
    rule_pack_version: 'placeholder',
    engine_version: 'placeholder',
    llm_provider: 'none',
    status: 'complete',
    summary_text: null,
    unpaired_match_timeline: false,
    fixture_warning:
      'Placeholder fixture — the Python analysis sidecar is not running, so this is static sample ' +
      'data for UI development only, not a real coaching review.',
    fixture_id: 'NA1_fixture_b',
    created_at: 0,
    completed_at: 0,
    focus_items: [
      coachingItem({
        id: 'placeholder-f1',
        rank: 1,
        issue_type: 'missed_farm',
        title: 'Left safe waves to group early',
        body: 'Sample coaching item. Connect the analysis sidecar (uv sync --project services/analysis) to see real findings here.',
        the_fix: 'This is placeholder text standing in for a real "what to do instead."',
        next_game_check: 'This is placeholder text standing in for a real next-game goal.',
        cost_summary: '~220 gold lost (placeholder)',
        exemplar_finding_id: 'placeholder-find-1',
        evidence_timestamps_ms: [840_000, 1_260_000]
      }),
      coachingItem({
        id: 'placeholder-f2',
        rank: 2,
        issue_type: 'late_objective_setup',
        title: 'Arrived late to Drake fights',
        body: 'Sample coaching item showing a second focus card layout with a shorter body.',
        the_fix: 'Placeholder "what to do instead" text.',
        next_game_check: 'Placeholder next-game goal text.',
        cost_summary: '2 lost objective fights (placeholder)',
        confidence: 0.6,
        evidence_timestamps_ms: [1_040_000]
      }),
      coachingItem({
        id: 'placeholder-f3',
        rank: 3,
        issue_type: 'overextension',
        title: 'Pushed too far without vision',
        body: 'Sample coaching item showing a third focus card so the primary coaching grid fills out.',
        the_fix: 'Placeholder "what to do instead" text.',
        next_game_check: 'Placeholder next-game goal text.',
        cost_summary: '1 death (placeholder)',
        confidence: 0.55
      })
    ],
    secondary_items: [
      coachingItem({
        id: 'placeholder-s1',
        is_focus: false,
        issue_type: 'ability_usage',
        title: 'Missed a poke opportunity',
        body: 'Sample secondary observation.',
        cost_summary: 'Minor (placeholder)'
      })
    ],
    strengths: [
      coachingItem({
        id: 'placeholder-w1',
        is_focus: false,
        is_strength: true,
        issue_type: 'objective_preparation',
        title: 'Strong vision before objectives',
        body: 'Sample strength item — shown with the positive coaching structure (no "instead" section).',
        next_game_check: 'Placeholder next-game goal text.',
        cost_summary: 'Consistent habit (placeholder)',
        confidence: 0.8
      })
    ],
    metrics: [
      {
        metric_id: 'cs_per_min',
        value: 7.4,
        unit: 'cs/min',
        phase: 'early',
        confidence: 1,
        baseline_percentile: 62,
        sample_context: 'placeholder',
        detail: {},
        quarantined: true
      }
    ],
    findings: [placeholderFinding('placeholder-find-1', 840_000, '14:00', 'Placeholder finding')],
    sync_map: null,
    media: null,
    overall_scores: {}
  }
}
