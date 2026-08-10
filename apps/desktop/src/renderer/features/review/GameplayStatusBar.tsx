import { useState, type ReactElement } from 'react'
import type { GameplayBarView } from './gameplayBar'
import type { ReplayActionId } from './replayErrors'

type Props = {
  view: GameplayBarView
  onOpen: () => void
  onClose: () => void
  onRetry: () => void
  onAction: (action: ReplayActionId) => void
}

const TONE: Record<GameplayBarView['tone'], string> = {
  neutral: 'border-slate-800 bg-slate-900/60 text-slate-300',
  info: 'border-sky-800/70 bg-sky-950/40 text-sky-100',
  ok: 'border-emerald-800/70 bg-emerald-950/40 text-emerald-100',
  warn: 'border-amber-800/70 bg-amber-950/40 text-amber-100',
  error: 'border-rose-800/70 bg-rose-950/40 text-rose-100'
}

export function GameplayStatusBar(props: Props): ReactElement {
  const [detailsOpen, setDetailsOpen] = useState(false)
  const { view } = props
  return (
    <section
      className={`mb-3 rounded border px-3 py-2 text-sm ${TONE[view.tone]}`}
      data-testid="gameplay-status-bar"
      data-bar-kind={view.kind}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p data-testid="gameplay-status-label">{view.label}</p>
          {view.syncLabel ? (
            <p className="text-xs opacity-80" data-testid="sync-confidence">
              {view.syncLabel}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {view.showOpen ? (
            <button
              type="button"
              data-testid="open-replay"
              className="rounded bg-sky-700 px-2 py-1 text-xs text-white"
              onClick={props.onOpen}
            >
              Open Replay
            </button>
          ) : null}
          {view.showClose ? (
            <button
              type="button"
              data-testid="close-replay"
              className="rounded bg-slate-800 px-2 py-1 text-xs"
              onClick={props.onClose}
            >
              Close Replay
            </button>
          ) : null}
          {view.showRetry ? (
            <button
              type="button"
              data-testid="retry-replay"
              className="rounded bg-slate-800 px-2 py-1 text-xs"
              onClick={props.onRetry}
            >
              Retry
            </button>
          ) : null}
          {view.actionId && view.actionLabel && !view.showRetry && view.actionId !== 'open_replay' ? (
            <button
              type="button"
              data-testid="gameplay-error-action"
              className="rounded bg-slate-800 px-2 py-1 text-xs"
              onClick={() => {
                if (view.actionId) {
                  props.onAction(view.actionId)
                }
              }}
            >
              {view.actionLabel}
            </button>
          ) : null}
          <button
            type="button"
            className="text-xs underline opacity-70"
            data-testid="sync-technical-toggle"
            onClick={() => setDetailsOpen((value) => !value)}
          >
            {detailsOpen ? 'Hide details' : 'Technical details'}
          </button>
        </div>
      </div>
      {detailsOpen ? (
        <dl className="mt-2 grid grid-cols-2 gap-1 text-xs opacity-80" data-testid="sync-technical-details">
          <div>offset_ms: {view.technical.offset_ms ?? '—'}</div>
          <div>residual_ms: {view.technical.residual_ms ?? '—'}</div>
          <div>anchor_count: {view.technical.anchor_count ?? '—'}</div>
          <div>method: {view.technical.clock_method ?? '—'}</div>
          <div>phase: {view.technical.session_phase ?? '—'}</div>
        </dl>
      ) : null}
    </section>
  )
}
