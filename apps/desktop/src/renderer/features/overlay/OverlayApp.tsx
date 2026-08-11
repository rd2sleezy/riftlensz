import { useCallback, useEffect, useMemo, useState, type ReactElement } from 'react'
import type {
  CoachingItem,
  GameplayStatus,
  OverlayPrefsPayload,
  ReviewPresentation
} from '../../../main/ipc/channels'
import { deriveGameplayBar, nativeSessionReady } from '../review/gameplayBar'
import { DEFAULT_REVEAL_LEAD_IN_MS, revealGameplayTimestamp } from '../review/gameplaySeek'
import {
  buildOverlayNav,
  categoryLabel,
  coachingSections,
  findNavIndex,
  formatGameMmss,
  stepNav,
  stepTimestamp,
  timestampsForItem,
  type OverlayNavItem
} from './findingNav'

export function OverlayApp(): ReactElement {
  const [review, setReview] = useState<ReviewPresentation | null>(null)
  const [status, setStatus] = useState<GameplayStatus | null>(null)
  const [prefs, setPrefs] = useState<OverlayPrefsPayload | null>(null)
  const [sourceId, setSourceId] = useState<string | null>(null)
  const [matchId, setMatchId] = useState<string | null>(null)
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null)
  const [timestampIndex, setTimestampIndex] = useState(0)
  const [seeking, setSeeking] = useState(false)
  const [seekMessage, setSeekMessage] = useState<string | null>(null)
  const [techOpen, setTechOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const compact = prefs?.compact ?? true

  const bootstrap = useCallback(async () => {
    const ctx = await window.rift.overlayGetContext()
    setPrefs(ctx.prefs)
    if (ctx.context === null) {
      setError('No active replay coaching context.')
      return
    }
    setSourceId(ctx.context.sourceId)
    setMatchId(ctx.context.matchId)
    const reviewResult = await window.rift.getReview(ctx.context.reviewId)
    if (!reviewResult.ok) {
      setError(reviewResult.message)
      return
    }
    setReview(reviewResult.review)
    setSelectedItemId(reviewResult.review.focus_items[0]?.id ?? null)
    const statusResult = await window.rift.getGameplayStatus(
      ctx.context.matchId,
      ctx.context.sourceId
    )
    if (statusResult.ok) {
      setStatus(statusResult.status)
    }
    setError(null)
  }, [])

  useEffect(() => {
    void bootstrap()
  }, [bootstrap])

  useEffect(() => {
    if (matchId === null) {
      return
    }
    const handle = window.setInterval(() => {
      void window.rift.getGameplayStatus(matchId, sourceId).then((result) => {
        if (result.ok) {
          setStatus(result.status)
          void window.rift.overlayUpdateSession({
            sessionPhase: result.status.session_phase,
            sessionReachedReady: result.status.session_reached_ready,
            liveGame: false
          })
        }
      })
      void window.rift.checkGameplayEnvironment().then((env) => {
        if (env.ok && env.live_game) {
          void window.rift.overlayUpdateSession({ liveGame: true })
        }
      })
    }, 2_000)
    return () => window.clearInterval(handle)
  }, [matchId, sourceId])

  const nav = useMemo(() => (review === null ? [] : buildOverlayNav(review)), [review])
  const navIndex = findNavIndex(nav, selectedItemId)
  const current: OverlayNavItem | null = nav[navIndex] ?? null
  const timestamps = current === null ? [] : timestampsForItem(current.item)
  const activeTs = timestamps[Math.min(timestampIndex, Math.max(0, timestamps.length - 1))]

  useEffect(() => {
    setTimestampIndex(0)
  }, [selectedItemId])

  const bar = deriveGameplayBar({
    status,
    nativeReplaySupported: true,
    hasInlineVideo: false,
    videoSynced: false,
    opening: false,
    seeking
  })

  const selectItem = (item: CoachingItem): void => {
    setSelectedItemId(item.id)
    setSeekMessage(null)
  }

  const jump = async (): Promise<void> => {
    if (sourceId === null || matchId === null || activeTs === undefined) {
      return
    }
    if (!nativeSessionReady(status)) {
      setSeekMessage('Replay session is not ready.')
      return
    }
    setSeeking(true)
    setSeekMessage('Seeking…')
    const result = await revealGameplayTimestamp(sourceId, matchId, activeTs, DEFAULT_REVEAL_LEAD_IN_MS)
    if (result.status) {
      setStatus(result.status)
    }
    setSeeking(false)
    setSeekMessage(result.ok ? null : result.message)
  }

  const reopen = async (): Promise<void> => {
    if (sourceId === null || matchId === null) {
      return
    }
    setSeekMessage('Reopening replay…')
    const result = await window.rift.openReplay(sourceId, matchId)
    if (result.status) {
      setStatus(result.status)
    }
    setSeekMessage(result.ok ? null : result.message)
    void window.rift.overlayUpdateSession({
      sessionPhase: result.status?.session_phase ?? null,
      sessionReachedReady: result.session_reached_ready,
      liveGame: false
    })
  }

  const setCompact = async (next: boolean): Promise<void> => {
    const updated = await window.rift.overlaySetPrefs({ compact: next })
    setPrefs(updated)
  }

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      // Overlay-focused only — never registered as globalShortcut.
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) {
        return
      }
      if (event.key === 'ArrowLeft') {
        event.preventDefault()
        const next = stepNav(nav, navIndex, -1)
        const row = nav[next]
        if (row) {
          selectItem(row.item)
        }
      }
      if (event.key === 'ArrowRight') {
        event.preventDefault()
        const next = stepNav(nav, navIndex, 1)
        const row = nav[next]
        if (row) {
          selectItem(row.item)
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [nav, navIndex])

  if (error !== null) {
    return (
      <div className="overlay-shell" data-testid="overlay-error">
        <div className="overlay-panel">
          <p className="overlay-muted">{error}</p>
          <button type="button" className="overlay-btn" onClick={() => void window.rift.overlayHide()}>
            Hide
          </button>
        </div>
      </div>
    )
  }

  if (review === null || current === null) {
    return (
      <div className="overlay-shell">
        <div className="overlay-panel overlay-muted">Loading coaching…</div>
      </div>
    )
  }

  return (
    <div className={`overlay-shell ${compact ? 'is-compact' : 'is-expanded'}`} data-testid="overlay-root">
      <div className="overlay-panel" style={{ opacity: prefs?.opacity ?? 0.94 }}>
        <header className="overlay-drag" data-testid="overlay-drag">
          <div className="overlay-title-row">
            <span className="overlay-badge" data-testid="overlay-category">
              {categoryLabel(current.category)}
              {current.category === 'focus'
                ? ` ${current.indexInCategory + 1}/${review.focus_items.length || 1}`
                : ''}
            </span>
            <span className={`overlay-sync tone-${bar.tone}`} data-testid="overlay-sync">
              {seeking ? 'Seeking…' : bar.syncLabel ?? bar.label}
            </span>
          </div>
          <h1 className="overlay-heading" data-testid="overlay-title">
            {current.item.title}
          </h1>
          <div className="overlay-meta">
            <span data-testid="overlay-timestamp">
              {activeTs === undefined ? '—' : formatGameMmss(activeTs)}
              {timestamps.length > 1 ? ` (${timestampIndex + 1}/${timestamps.length})` : ''}
            </span>
            <span className="overlay-muted">
              {navIndex + 1}/{nav.length}
            </span>
          </div>
        </header>

        <div className="overlay-controls" data-testid="overlay-controls">
          <button
            type="button"
            className="overlay-btn"
            data-testid="overlay-prev"
            onClick={() => {
              const row = nav[stepNav(nav, navIndex, -1)]
              if (row) selectItem(row.item)
            }}
          >
            Prev
          </button>
          <button
            type="button"
            className="overlay-btn overlay-btn-primary"
            data-testid="overlay-jump"
            disabled={seeking || activeTs === undefined}
            onClick={() => void jump()}
          >
            Jump
          </button>
          <button
            type="button"
            className="overlay-btn"
            data-testid="overlay-next"
            onClick={() => {
              const row = nav[stepNav(nav, navIndex, 1)]
              if (row) selectItem(row.item)
            }}
          >
            Next
          </button>
          {timestamps.length > 1 ? (
            <button
              type="button"
              className="overlay-btn"
              data-testid="overlay-next-ts"
              onClick={() => setTimestampIndex((i) => stepTimestamp(timestamps, i, 1))}
            >
              Next time
            </button>
          ) : null}
        </div>

        {seekMessage !== null ? (
          <p className="overlay-message" data-testid="overlay-seek-message">
            {seekMessage}
          </p>
        ) : null}

        {bar.kind === 'session_lost' ? (
          <button
            type="button"
            className="overlay-btn overlay-btn-primary"
            data-testid="overlay-reopen"
            onClick={() => void reopen()}
          >
            Reopen replay
          </button>
        ) : null}

        {!compact ? (
          <ExpandedBody
            review={review}
            current={current}
            selectedItemId={selectedItemId}
            onSelect={selectItem}
            techOpen={techOpen}
            onToggleTech={() => setTechOpen((v) => !v)}
          />
        ) : null}

        <footer className="overlay-footer">
          <button
            type="button"
            className="overlay-btn"
            data-testid="overlay-toggle-compact"
            onClick={() => void setCompact(!compact)}
          >
            {compact ? 'Expand' : 'Compact'}
          </button>
          <button
            type="button"
            className="overlay-btn"
            data-testid="overlay-hide"
            onClick={() => void window.rift.overlayHide()}
          >
            Hide
          </button>
        </footer>
      </div>
    </div>
  )
}

function ExpandedBody(props: {
  review: ReviewPresentation
  current: OverlayNavItem
  selectedItemId: string | null
  onSelect: (item: CoachingItem) => void
  techOpen: boolean
  onToggleTech: () => void
}): ReactElement {
  const sections = coachingSections(props.current.item)
  return (
    <div className="overlay-expanded" data-testid="overlay-expanded">
      <section>
        <h2>Focus</h2>
        <ItemButtons
          items={props.review.focus_items}
          selectedId={props.selectedItemId}
          onSelect={props.onSelect}
          testId="overlay-focus-list"
        />
      </section>
      <section>
        <h2>Secondary</h2>
        <ItemButtons
          items={props.review.secondary_items}
          selectedId={props.selectedItemId}
          onSelect={props.onSelect}
          testId="overlay-secondary-list"
        />
      </section>
      <section>
        <h2>Strengths</h2>
        <ItemButtons
          items={props.review.strengths}
          selectedId={props.selectedItemId}
          onSelect={props.onSelect}
          testId="overlay-strength-list"
        />
      </section>
      <article className="overlay-copy" data-testid="overlay-copy">
        {sections.map((section) => (
          <div key={section.label}>
            <h3>{section.label}</h3>
            <p>{section.body}</p>
          </div>
        ))}
      </article>
      <button type="button" className="overlay-btn" onClick={props.onToggleTech}>
        {props.techOpen ? 'Hide technical' : 'Technical evidence'}
      </button>
      {props.techOpen ? (
        <pre className="overlay-tech" data-testid="overlay-tech">
          {props.current.item.cost_summary}
          {'\n'}
          certainty={props.current.item.certainty}
          {'\n'}
          concept={props.current.item.root_concept_id}
        </pre>
      ) : null}
    </div>
  )
}

function ItemButtons(props: {
  items: CoachingItem[]
  selectedId: string | null
  onSelect: (item: CoachingItem) => void
  testId: string
}): ReactElement {
  if (props.items.length === 0) {
    return <p className="overlay-muted">None</p>
  }
  return (
    <ul className="overlay-item-list" data-testid={props.testId}>
      {props.items.map((item, index) => (
        <li key={item.id}>
          <button
            type="button"
            className={props.selectedId === item.id ? 'is-selected' : undefined}
            onClick={() => props.onSelect(item)}
          >
            {index + 1}. {item.title}
          </button>
        </li>
      ))}
    </ul>
  )
}
