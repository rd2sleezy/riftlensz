import type { ReactElement, ReactNode } from 'react'

export function Card(props: {
  children: ReactNode
  className?: string
  testId?: string
}): ReactElement {
  return (
    <section
      data-testid={props.testId}
      className={`rounded-xl border border-rift-border bg-rift-surface shadow-card ${props.className ?? ''}`}
    >
      {props.children}
    </section>
  )
}

const BADGE_VARIANTS = {
  neutral: 'border-rift-edge bg-white/5 text-slate-300',
  accent: 'border-rift-accent/30 bg-rift-accent-soft text-rift-accent-strong',
  gold: 'border-rift-gold/30 bg-rift-gold-soft text-rift-gold',
  danger: 'border-rift-danger/30 bg-rift-danger-soft text-rift-danger',
  win: 'border-rift-win/30 bg-rift-win/10 text-rift-win',
  loss: 'border-rift-loss/30 bg-rift-loss/10 text-rift-loss'
} as const

export function Badge(props: {
  children: ReactNode
  variant?: keyof typeof BADGE_VARIANTS
  className?: string
}): ReactElement {
  const variant = props.variant ?? 'neutral'
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium ${BADGE_VARIANTS[variant]} ${props.className ?? ''}`}
    >
      {props.children}
    </span>
  )
}

export function SectionLabel(props: { children: ReactNode; className?: string }): ReactElement {
  return (
    <h2
      className={`text-xs font-semibold uppercase tracking-wider text-slate-500 ${props.className ?? ''}`}
    >
      {props.children}
    </h2>
  )
}

/** Progressive disclosure for technical/debug information — collapsed by default. */
export function Disclosure(props: {
  summary: ReactNode
  children: ReactNode
  testId?: string
}): ReactElement {
  return (
    <details className="group" data-testid={props.testId}>
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium text-slate-500 transition hover:text-slate-300">
        <svg
          viewBox="0 0 16 16"
          className="h-3 w-3 shrink-0 transition-transform group-open:rotate-90"
          fill="currentColor"
          aria-hidden="true"
        >
          <path d="M6 4l4 4-4 4V4z" />
        </svg>
        {props.summary}
      </summary>
      <div className="mt-2">{props.children}</div>
    </details>
  )
}

/** Riot Games' angular fist/crest icon on their brand red, stylized in SVG. */
export function RiotIcon(props: { className?: string }): ReactElement {
  return (
    <span
      className={`flex items-center justify-center rounded-[5px] bg-[#E2001C] ${props.className ?? 'h-4 w-4'}`}
    >
      <svg viewBox="0 0 100 100" className="h-[70%] w-[70%]" fill="#ffffff" aria-hidden="true">
        <path d="M50 14 26 38 34 74 42 44 50 78 58 44 66 74 74 38Z" />
        <path d="M70 62 92 72 92 92 70 82Z" />
      </svg>
    </span>
  )
}

/** Riot Games attribution mark for the sign-in surface (icon + wordmark). */
export function RiotMark(props: { className?: string }): ReactElement {
  return (
    <span className={`inline-flex items-center gap-1.5 ${props.className ?? ''}`}>
      <RiotIcon />
      <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">Riot Games</span>
    </span>
  )
}

export function EmptyState(props: {
  title: string
  body?: string
  action?: ReactNode
}): ReactElement {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-rift-border px-6 py-10 text-center">
      <p className="text-sm font-medium text-slate-300">{props.title}</p>
      {props.body ? <p className="max-w-sm text-xs text-slate-500">{props.body}</p> : null}
      {props.action ? <div className="mt-2">{props.action}</div> : null}
    </div>
  )
}
