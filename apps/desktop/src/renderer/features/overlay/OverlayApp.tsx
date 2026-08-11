import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from 'react'
import type {
  CoachingItem,
  GameplayStatus,
  OverlayLifecycleEventPayload,
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
  groupNavSections,
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
  const [timestampIndexByItem, setTimestampIndexByItem] = useState<Record<string, number>>({})
  const [seekingItemId, setSeekingItemId] = useState<string | null>(null)
  const [seekMessage, setSeekMessage] = useState<string | null>(null)
  const [techOpen, setTechOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lifecycle, setLifecycle] = useState<OverlayLifecycleEventPayload | null>(null)
  const seekInFlight = useRef(false)

  const detailOpen = prefs?.detailOpen ?? true

  const bootstrap = useCallback(async () => {
    const [ctx, life] = await Promise.all([
      window.rift.overlayGetContext(),
      window.rift.overlayGetLifecycle()
    ])
    setPrefs(ctx.prefs)
    setLifecycle(life)
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
    return window.rift.onOverlayLifecycle((event) => {
      setLifecycle(event)
    })
  }, [])

  // Low-frequency health poll only — never blocks selection/seek.
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
      void window.rift.overlayGetLifecycle().then(setLifecycle)
    }, 3_000)
    return () => window.clearInterval(handle)
  }, [matchId, sourceId])

  const nav = useMemo(() => (review === null ? [] : buildOverlayNav(review)), [review])
  const sections = useMemo(() => groupNavSections(nav), [nav])
  const navIndex = findNavIndex(nav, selectedItemId)
  const current: OverlayNavItem | null = nav[navIndex] ?? null

  const activeTsFor = useCallback(
    (item: CoachingItem): number | undefined => {
      const stamps = timestampsForItem(item)
      const idx = timestampIndexByItem[item.id] ?? 0
      return stamps[Math.min(idx, Math.max(0, stamps.length - 1))]
    },
    [timestampIndexByItem]
  )

  const bar = deriveGameplayBar({
    status,
    nativeReplaySupported: true,
    hasInlineVideo: false,
    videoSynced: false,
    opening: false,
    seeking: seekingItemId !== null
  })

  const seekTo = useCallback(
    (item: CoachingItem, gameTMs: number): void => {
      // Optimistic local UI — do not wait for sidecar or status poll.
      setSelectedItemId(item.id)
      if (sourceId === null || matchId === null) {
        setSeekMessage('Replay source missing.')
        setSeekingItemId(null)
        return
      }
      if (!nativeSessionReady(status) && status !== null) {
        setSeekMessage('Replay session is not ready.')
        setSeekingItemId(null)
        return
      }
      if (seekInFlight.current) {
        setSeekMessage('Seek in progress…')
        return
      }
      setSeekMessage('Seeking…')
      setSeekingItemId(item.id)
      seekInFlight.current = true
      void revealGameplayTimestamp(sourceId, matchId, gameTMs, DEFAULT_REVEAL_LEAD_IN_MS)
        .then((result) => {
          if (result.status) {
            setStatus(result.status)
          }
          setSeekMessage(result.ok ? null : result.message)
        })
        .finally(() => {
          seekInFlight.current = false
          setSeekingItemId(null)
        })
    },
    [matchId, sourceId, status]
  )

  const onRowActivate = (row: OverlayNavItem): void => {
    const ts = activeTsFor(row.item)
    if (ts === undefined) {
      setSelectedItemId(row.item.id)
      return
    }
    seekTo(row.item, ts)
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

  const setDetailOpen = async (next: boolean): Promise<void> => {
    // Optimistic prefs for instant layout feel.
    setPrefs((prev) => (prev === null ? prev : { ...prev, detailOpen: next }))
    const updated = await window.rift.overlaySetPrefs({ detailOpen: next })
    setPrefs(updated)
  }

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

  if (review === null) {
    return (
      <div className="overlay-shell">
        <div className="overlay-panel overlay-muted">Loading coaching…</div>
      </div>
    )
  }

  return (
    <div className="overlay-shell" data-testid="overlay-root">
      {lifecycle?.displayMode === 'exclusive_fullscreen' || lifecycle?.reason === 'exclusive_fullscreen' ? (
        <div className="overlay-banner" data-testid="overlay-exclusive-fs">
          {lifecycle.message ??
            'RiftLens overlay requires Borderless or Windowed replay mode.'}
        </div>
      ) : null}

      <div className="overlay-chrome" style={{ opacity: prefs?.opacity ?? 0.94 }}>
        <aside className="overlay-navigator" data-testid="overlay-navigator">
          <header className="overlay-drag" data-testid="overlay-drag">
            <div className="overlay-title-row">
              <span className="overlay-badge">Issues</span>
              <span className={`overlay-sync tone-${bar.tone}`} data-testid="overlay-sync">
                {seekingItemId !== null ? 'Seeking…' : bar.syncLabel ?? bar.label}
              </span>
            </div>
          </header>

          <div className="overlay-nav-scroll" data-testid="overlay-nav-scroll">
            <NavSection
              title="Focus"
              rows={sections.focus}
              selectedId={selectedItemId}
              seekingItemId={seekingItemId}
              timestampIndexByItem={timestampIndexByItem}
              onActivate={onRowActivate}
              onCycleTimestamp={(itemId, stamps) => {
                setTimestampIndexByItem((prev) => ({
                  ...prev,
                  [itemId]: stepTimestamp(stamps, prev[itemId] ?? 0, 1)
                }))
              }}
            />
            <NavSection
              title="Secondary"
              rows={sections.secondary}
              selectedId={selectedItemId}
              seekingItemId={seekingItemId}
              timestampIndexByItem={timestampIndexByItem}
              onActivate={onRowActivate}
              onCycleTimestamp={(itemId, stamps) => {
                setTimestampIndexByItem((prev) => ({
                  ...prev,
                  [itemId]: stepTimestamp(stamps, prev[itemId] ?? 0, 1)
                }))
              }}
            />
            <NavSection
              title="Strengths"
              rows={sections.strengths}
              selectedId={selectedItemId}
              seekingItemId={seekingItemId}
              timestampIndexByItem={timestampIndexByItem}
              onActivate={onRowActivate}
              onCycleTimestamp={(itemId, stamps) => {
                setTimestampIndexByItem((prev) => ({
                  ...prev,
                  [itemId]: stepTimestamp(stamps, prev[itemId] ?? 0, 1)
                }))
              }}
            />
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

          <footer className="overlay-footer">
            <button
              type="button"
              className="overlay-btn"
              data-testid="overlay-toggle-detail"
              onClick={() => void setDetailOpen(!detailOpen)}
            >
              {detailOpen ? 'Hide detail' : 'Show detail'}
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
        </aside>

        {detailOpen && current !== null ? (
          <DetailPanel
            current={current}
            activeTs={activeTsFor(current.item)}
            techOpen={techOpen}
            onToggleTech={() => setTechOpen((v) => !v)}
            onCollapse={() => void setDetailOpen(false)}
          />
        ) : null}
      </div>
    </div>
  )
}

function NavSection(props: {
  title: string
  rows: OverlayNavItem[]
  selectedId: string | null
  seekingItemId: string | null
  timestampIndexByItem: Record<string, number>
  onActivate: (row: OverlayNavItem) => void
  onCycleTimestamp: (itemId: string, stamps: number[]) => void
}): ReactElement {
  return (
    <section className="overlay-nav-section" data-testid={`overlay-section-${props.title.toLowerCase()}`}>
      <h2>{props.title}</h2>
      {props.rows.length === 0 ? (
        <p className="overlay-muted">None</p>
      ) : (
        <ul className="overlay-item-list">
          {props.rows.map((row) => {
            const stamps = timestampsForItem(row.item)
            const idx = props.timestampIndexByItem[row.item.id] ?? 0
            const ts = stamps[Math.min(idx, Math.max(0, stamps.length - 1))]
            const selected = props.selectedId === row.item.id
            const seeking = props.seekingItemId === row.item.id
            return (
              <li key={row.item.id}>
                <button
                  type="button"
                  className={`overlay-row ${selected ? 'is-selected' : ''} ${seeking ? 'is-seeking' : ''}`}
                  data-testid={`overlay-row-${row.item.id}`}
                  onClick={() => props.onActivate(row)}
                >
                  <span className="overlay-row-meta">
                    <span className="overlay-row-cat">{categoryLabel(row.category)}</span>
                    <span className="overlay-row-ts">
                      {ts === undefined ? '—' : formatGameMmss(ts)}
                      {seeking ? ' · Seeking…' : ''}
                    </span>
                  </span>
                  <span className="overlay-row-title">{row.item.title}</span>
                </button>
                {stamps.length > 1 ? (
                  <button
                    type="button"
                    className="overlay-btn overlay-btn-tiny"
                    data-testid={`overlay-cycle-ts-${row.item.id}`}
                    onClick={(event) => {
                      event.stopPropagation()
                      props.onCycleTimestamp(row.item.id, stamps)
                    }}
                  >
                    Time {idx + 1}/{stamps.length}
                  </button>
                ) : null}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

function DetailPanel(props: {
  current: OverlayNavItem
  activeTs: number | undefined
  techOpen: boolean
  onToggleTech: () => void
  onCollapse: () => void
}): ReactElement {
  const copy = coachingSections(props.current.item)
  return (
    <section className="overlay-detail" data-testid="overlay-detail">
      <header className="overlay-drag">
        <div className="overlay-title-row">
          <span className="overlay-badge">{categoryLabel(props.current.category)}</span>
          <button type="button" className="overlay-btn overlay-btn-tiny" onClick={props.onCollapse}>
            Collapse
          </button>
        </div>
        <h1 className="overlay-heading" data-testid="overlay-title">
          {props.current.item.title}
        </h1>
        <div className="overlay-meta" data-testid="overlay-timestamp">
          {props.activeTs === undefined ? '—' : formatGameMmss(props.activeTs)}
        </div>
      </header>
      <article className="overlay-copy" data-testid="overlay-copy">
        {copy.map((section) => (
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
    </section>
  )
}
