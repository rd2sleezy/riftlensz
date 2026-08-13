// Presentation-layer label translation only. Never changes underlying values —
// only how ids/enums the backend already returns are displayed to a player.

const KNOWN_METRIC_LABELS: Record<string, string> = {
  cs_per_min: 'CS/min'
}

const KNOWN_PHASE_LABELS: Record<string, string> = {
  early: 'Early game',
  mid: 'Mid game',
  late: 'Late game'
}

const ACRONYMS = new Set(['cs', 'kda', 'gpm', 'xpm', 'kp', 'id', 'vod'])

function titleCaseWords(words: string[]): string {
  return words
    .filter(Boolean)
    .map((word) => {
      const lower = word.toLowerCase()
      if (ACRONYMS.has(lower)) {
        return lower.toUpperCase()
      }
      return lower.charAt(0).toUpperCase() + lower.slice(1)
    })
    .join(' ')
}

function splitIdentifier(raw: string): string[] {
  return raw
    .replace(/[._-]+/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .trim()
    .split(/\s+/)
}

/** Turns a snake_case / SCREAMING_SNAKE / dotted backend id into a readable label. */
export function humanizeIdentifier(raw: string | null | undefined): string {
  if (raw === null || raw === undefined || raw.length === 0) {
    return '—'
  }
  return titleCaseWords(splitIdentifier(raw))
}

export function humanizeMetricId(metricId: string): string {
  return KNOWN_METRIC_LABELS[metricId] ?? humanizeIdentifier(metricId)
}

export function humanizePhase(phase: string | null): string | null {
  if (phase === null) {
    return null
  }
  return KNOWN_PHASE_LABELS[phase.toLowerCase()] ?? humanizeIdentifier(phase)
}

export function humanizeConceptId(conceptId: string): string {
  // Concept ids look like "LANING.FARM" — last segment is the specific concept.
  const segment = conceptId.split('.').pop() ?? conceptId
  return humanizeIdentifier(segment)
}

export function formatConfidencePct(confidence: number): string {
  return `${Math.round(confidence * 100)}%`
}

const ROLE_LABELS: Record<string, string> = {
  TOP: 'Top',
  JUNGLE: 'Jungle',
  MIDDLE: 'Mid',
  BOTTOM: 'Bottom',
  UTILITY: 'Support'
}

export function humanizeRole(role: string): string {
  return ROLE_LABELS[role.toUpperCase()] ?? humanizeIdentifier(role)
}

export function formatResult(result: string | null): string {
  if (result === null) {
    return 'Unscored'
  }
  const upper = result.toUpperCase()
  if (upper === 'WIN') {
    return 'Victory'
  }
  if (upper === 'LOSS' || upper === 'LOSE') {
    return 'Defeat'
  }
  return humanizeIdentifier(result)
}
