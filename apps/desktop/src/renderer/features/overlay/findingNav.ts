/** Pure finding navigation helpers for the coaching overlay (R.10.5). */

import type { CoachingItem, ReviewPresentation } from '../../../main/ipc/channels'

export type OverlayCategory = 'focus' | 'secondary' | 'strength'

export type OverlayNavItem = {
  item: CoachingItem
  category: OverlayCategory
  indexInCategory: number
  flatIndex: number
}

export function buildOverlayNav(review: ReviewPresentation): OverlayNavItem[] {
  const rows: OverlayNavItem[] = []
  review.focus_items.forEach((item, indexInCategory) => {
    rows.push({ item, category: 'focus', indexInCategory, flatIndex: rows.length })
  })
  review.secondary_items.forEach((item, indexInCategory) => {
    rows.push({ item, category: 'secondary', indexInCategory, flatIndex: rows.length })
  })
  review.strengths.forEach((item, indexInCategory) => {
    rows.push({ item, category: 'strength', indexInCategory, flatIndex: rows.length })
  })
  return rows
}

export function categoryLabel(category: OverlayCategory): string {
  if (category === 'focus') {
    return 'Focus'
  }
  if (category === 'secondary') {
    return 'Secondary'
  }
  return 'Strength'
}

export function findNavIndex(nav: OverlayNavItem[], itemId: string | null): number {
  if (itemId === null) {
    return 0
  }
  const index = nav.findIndex((row) => row.item.id === itemId)
  return index >= 0 ? index : 0
}

export function stepNav(nav: OverlayNavItem[], currentIndex: number, delta: number): number {
  if (nav.length === 0) {
    return 0
  }
  const next = currentIndex + delta
  if (next < 0) {
    return nav.length - 1
  }
  if (next >= nav.length) {
    return 0
  }
  return next
}

export function timestampsForItem(item: CoachingItem): number[] {
  return [...item.evidence_timestamps_ms]
}

export function stepTimestamp(timestamps: number[], currentIndex: number, delta: number): number {
  if (timestamps.length === 0) {
    return 0
  }
  const next = currentIndex + delta
  if (next < 0) {
    return timestamps.length - 1
  }
  if (next >= timestamps.length) {
    return 0
  }
  return next
}

export function formatGameMmss(tMs: number): string {
  const total = Math.max(0, Math.floor(tMs / 1000))
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${minutes}:${seconds.toString().padStart(2, '0')}`
}

/** Map H.8 fields to overlay coaching section labels. */
export function coachingSections(
  item: CoachingItem
): { label: string; body: string }[] {
  if (item.is_strength) {
    const sections: { label: string; body: string }[] = [
      { label: 'What you did well', body: item.title },
      { label: 'Why it worked', body: item.body }
    ]
    if (item.the_fix) {
      sections.push({ label: 'Keep doing this', body: item.the_fix })
    }
    if (item.next_game_check) {
      sections.push({ label: 'Next-game goal', body: item.next_game_check })
    }
    return sections
  }
  const sections: { label: string; body: string }[] = [
    { label: 'What happened', body: item.body }
  ]
  if (item.cost_summary.trim().length > 0) {
    sections.push({ label: 'Why it matters', body: item.cost_summary })
  }
  if (item.the_fix) {
    sections.push({ label: 'What to do instead', body: item.the_fix })
  }
  if (item.next_game_check) {
    sections.push({ label: 'Next-game goal', body: item.next_game_check })
  }
  return sections
}

/** Group flat nav into section buckets for the scrollable navigator. */
export function groupNavSections(nav: OverlayNavItem[]): {
  focus: OverlayNavItem[]
  secondary: OverlayNavItem[]
  strengths: OverlayNavItem[]
} {
  return {
    focus: nav.filter((row) => row.category === 'focus'),
    secondary: nav.filter((row) => row.category === 'secondary'),
    strengths: nav.filter((row) => row.category === 'strength')
  }
}
