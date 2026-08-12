import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from 'react'
import type {
  CoachingItem,
  Finding,
  GameplayStatus,
  MediaProbe,
  ReviewPresentation
} from '../../../main/ipc/channels'
import { type SyncMapData, formatMmss, seekTarget } from '../../../main/sync/syncMap'
import { AddGameplayMenu } from './AddGameplayMenu'
import { GameplayStatusBar } from './GameplayStatusBar'
import { ImportReplayWizard } from './ImportReplayWizard'
import { deriveGameplayBar, hasNativeCapabilities, nativeSessionReady } from './gameplayBar'
import { revealGameplayTimestamp } from './gameplaySeek'
import type { ReplayActionId } from './replayErrors'
import { VideoPlayer } from './VideoPlayer'

export function ReviewScreen({ reviewId }: { reviewId: string }): ReactElement {
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null)
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null)
  const [playheadMs, setPlayheadMs] = useState(0)
  const [seekRequestMs, setSeekRequestMs] = useState<number | null>(null)
  const [sync, setSync] = useState<SyncMapData | null>(null)
  const [mediaUrl, setMediaUrl] = useState<string | null>(null)
  const [probe, setProbe] = useState<MediaProbe | null>(null)
  const [vodError, setVodError] = useState<string | null>(null)
  const [vodWarning, setVodWarning] = useState<string | null>(null)
  const [clockInput, setClockInput] = useState('0:00')
  const [syncMessage, setSyncMessage] = useState<string | null>(null)
  const [rate, setRate] = useState(1)
  const [gameplayStatus, setGameplayStatus] = useState<GameplayStatus | null>(null)
  const [nativeReplaySupported, setNativeReplaySupported] = useState(false)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [openingReplay, setOpeningReplay] = useState(false)
  const [seekingMs, setSeekingMs] = useState<number | null>(null)
  const [playingTargetMs, setPlayingTargetMs] = useState<number | null>(null)
  const [pendingRevealMs, setPendingRevealMs] = useState<number | null>(null)
  const [activeMode, setActiveMode] = useState<'auto' | 'replay' | 'video'>('auto')
  const [overlayNotice, setOverlayNotice] = useState<string | null>(null)
  const pendingRevealRef = useRef<number | null>(null)

  const reviewQuery = useQuery({
    queryKey: ['review', reviewId],
    queryFn: async () => {
      const result = await window.rift.getReview(reviewId)
      if (!result.ok) {
        throw new Error(result.message)
      }
      return result.review
    }
  })

  const review = reviewQuery.data
  useEffect(() => {
    if (review?.sync_map) {
      setSync(review.sync_map)
    }
  }, [review?.sync_map])

  useEffect(() => {
    void window.rift.getDesktopPlatform().then((platform) => {
      setNativeReplaySupported(platform.nativeReplaySupported)
    })
  }, [])

  const refreshGameplay = useCallback(async (matchId: string, sourceId?: string | null) => {
    const result = await window.rift.getGameplayStatus(matchId, sourceId)
    if (result.ok) {
      setGameplayStatus(result.status)
      return result.status
    }
    return null
  }, [])

  useEffect(() => {
    if (review === undefined) {
      return
    }
    void refreshGameplay(review.match_id)
  }, [refreshGameplay, review])

  useEffect(() => {
    if (review === undefined) {
      return
    }
    const phase = gameplayStatus?.session_phase
    const shouldPoll =
      openingReplay ||
      phase === 'LAUNCHING' ||
      phase === 'CONNECTING' ||
      phase === 'SEEKING' ||
      nativeSessionReady(gameplayStatus)
    if (!shouldPoll) {
      return
    }
    const handle = window.setInterval(() => {
      void refreshGameplay(review.match_id, gameplayStatus?.active_source_id)
    }, openingReplay || phase === 'LAUNCHING' || phase === 'CONNECTING' ? 400 : 2_000)
    return () => window.clearInterval(handle)
  }, [gameplayStatus, openingReplay, refreshGameplay, review])

  const selectedItem = useMemo(() => {
    if (review === undefined) {
      return null
    }
    const items = [...review.focus_items, ...review.secondary_items, ...review.strengths]
    return items.find((item) => item.id === selectedItemId) ?? review.focus_items[0] ?? null
  }, [review, selectedItemId])

  const selectedFinding = useMemo(() => {
    if (review === undefined) {
      return null
    }
    if (selectedFindingId !== null) {
      return review.findings.find((item) => item.id === selectedFindingId) ?? null
    }
    if (selectedItem?.exemplar_finding_id) {
      return review.findings.find((item) => item.id === selectedItem.exemplar_finding_id) ?? null
    }
    return null
  }, [review, selectedFindingId, selectedItem])

  const preferNative =
    activeMode !== 'video' && hasNativeCapabilities(gameplayStatus) && nativeReplaySupported

  const openReplay = useCallback(async (): Promise<boolean> => {
    const sourceId = gameplayStatus?.active_source_id
    if (!review || sourceId === null || sourceId === undefined) {
      setSyncMessage('Link a League replay before opening it.')
      return false
    }
    setOpeningReplay(true)
    setSyncMessage(null)
    const result = await window.rift.openReplay(sourceId, review.match_id)
    if (result.status) {
      setGameplayStatus(result.status)
    }
    setOpeningReplay(false)
    if (!result.ok || !result.session_reached_ready) {
      setSyncMessage(result.ok ? 'Replay is not ready yet.' : result.message)
      return false
    }
    return true
  }, [gameplayStatus?.active_source_id, review])

  const revealNative = useCallback(
    async (tGameMs: number) => {
      const sourceId = gameplayStatus?.active_source_id
      if (!review || sourceId === null || sourceId === undefined) {
        return
      }
      setSeekingMs(tGameMs)
      setPlayingTargetMs(null)
      const result = await revealGameplayTimestamp(sourceId, review.match_id, tGameMs)
      if (result.status) {
        setGameplayStatus(result.status)
      }
      setSeekingMs(null)
      if (!result.ok) {
        setSyncMessage(result.message)
        return
      }
      setPlayingTargetMs(tGameMs)
      setSyncMessage(null)
    },
    [gameplayStatus?.active_source_id, review]
  )

  const seekToGame = useCallback(
    (tGameMs: number) => {
      if (preferNative) {
        if (nativeSessionReady(gameplayStatus)) {
          void revealNative(tGameMs)
          return
        }
        pendingRevealRef.current = tGameMs
        setPendingRevealMs(tGameMs)
        setSyncMessage('Opening replay to jump here…')
        void openReplay().then((ready) => {
          const pending = pendingRevealRef.current
          if (ready && pending !== null) {
            pendingRevealRef.current = null
            setPendingRevealMs(null)
            void revealNative(pending)
          }
        })
        return
      }
      const target = seekTarget(sync, tGameMs)
      if (!target.covered || target.seek_video_ms === null) {
        setSyncMessage(target.reason ?? 'Cannot seek — sync does not cover this timestamp.')
        return
      }
      setSeekRequestMs(target.seek_video_ms)
      setSyncMessage(target.uncertain ? target.reason : null)
    },
    [gameplayStatus, openReplay, preferNative, revealNative, sync]
  )

  const handleReplayAction = useCallback(
    (action: ReplayActionId) => {
      if (action === 'attach_video') {
        void attachVod(setVodError, setVodWarning, setMediaUrl, setProbe)
        setActiveMode('video')
        return
      }
      if (action === 'choose_file' || action === 'pick_match') {
        setWizardOpen(true)
        return
      }
      if (action === 'open_replay' || action === 'reopen_replay' || action === 'retry' || action === 'try_anyway') {
        void openReplay()
      }
    },
    [openReplay]
  )

  useEffect(() => {
    if (review === undefined) {
      return
    }
    const ready = nativeSessionReady(gameplayStatus)
    const sourceId = gameplayStatus?.active_source_id
    if (!ready || sourceId === null || sourceId === undefined || !preferNative) {
      return
    }
    let cancelled = false
    void (async () => {
      const env = await window.rift.checkGameplayEnvironment()
      if (cancelled) {
        return
      }
      if (env.ok && env.live_game && !nativeSessionReady(gameplayStatus)) {
        void window.rift.overlayClose()
        return
      }
      void window.rift.overlayOpen({
        reviewId,
        matchId: review.match_id,
        sourceId,
        sessionPhase: gameplayStatus?.session_phase ?? null,
        sessionReachedReady: true,
        liveGame: false
      })
    })()
    return () => {
      cancelled = true
    }
  }, [
    gameplayStatus?.active_source_id,
    gameplayStatus?.session_phase,
    gameplayStatus,
    preferNative,
    review,
    reviewId
  ])

  useEffect(() => {
    const phase = gameplayStatus?.session_phase
    const lost =
      gameplayStatus?.error?.code === 'SESSION_LOST' ||
      phase === 'CLOSED' ||
      phase === 'FAILED' ||
      phase === 'IDLE'
    if (lost && !openingReplay) {
      void window.rift.overlayUpdateSession({
        sessionPhase: phase ?? null,
        sessionReachedReady: false
      })
    } else if (gameplayStatus !== null) {
      void window.rift.overlayUpdateSession({
        sessionPhase: gameplayStatus.session_phase,
        sessionReachedReady: gameplayStatus.session_reached_ready
      })
    }
  }, [gameplayStatus, openingReplay])

  useEffect(() => {
    return () => {
      void window.rift.overlayClose()
    }
  }, [reviewId])

  useEffect(() => {
    return window.rift.onOverlayLifecycle((event) => {
      if (event.needsCompat || event.displayMode === 'exclusive_fullscreen') {
        setOverlayNotice(
          event.message ?? 'RiftLens Overlay requires Borderless display mode.'
        )
        return
      }
      setOverlayNotice(null)
    })
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) {
        return
      }
      if (event.code === 'Space') {
        event.preventDefault()
        const video = document.querySelector('video')
        if (video instanceof HTMLVideoElement) {
          if (video.paused) {
            void video.play()
          } else {
            video.pause()
          }
        }
      }
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        const delta = event.key === 'ArrowLeft' ? -5_000 : 5_000
        setSeekRequestMs(Math.max(0, playheadMs + delta))
      }
      if (review && ['1', '2', '3'].includes(event.key)) {
        const item = review.focus_items[Number(event.key) - 1]
        if (item !== undefined) {
          setSelectedItemId(item.id)
          const first = item.evidence_timestamps_ms[0]
          if (first !== undefined) {
            seekToGame(first)
          }
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [playheadMs, review, seekToGame])

  if (reviewQuery.isError) {
    return (
      <main className="min-h-screen bg-slate-950 p-8 text-slate-100">
        <BackLink />
        <p className="mt-6 text-rose-400" data-testid="review-error">
          {reviewQuery.error instanceof Error ? reviewQuery.error.message : 'Review unavailable'}
        </p>
      </main>
    )
  }

  if (review === undefined) {
    return (
      <main className="min-h-screen bg-slate-950 p-8 text-slate-100">
        <BackLink />
        <p className="mt-6 text-slate-400">Loading review…</p>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-slate-950 p-4 text-slate-100">
      <header className="mb-3 flex items-center justify-between gap-4">
        <div>
          <BackLink />
          <h1 className="mt-2 text-xl font-semibold" data-testid="review-identity">
            {review.champion} {review.role} · {review.result ?? 'unknown result'} ·{' '}
            {formatMmss(review.duration_ms)} · Patch {review.patch} · pid {review.participant_id}
          </h1>
          <p className="text-xs text-slate-400">
            {review.match_id} · rank {review.rank} · {review.engine_version} · LLM {review.llm_provider}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <AddGameplayMenu
            nativeReplaySupported={nativeReplaySupported}
            onImportReplay={() => setWizardOpen(true)}
            onAttachVideo={() => {
              setActiveMode('video')
              void attachVod(setVodError, setVodWarning, setMediaUrl, setProbe)
            }}
          />
          {sync ? (
            <p className="text-xs text-slate-300" data-testid="sync-status">
              Sync {sync.quality.verdict}
              {sync.quality.verdict === 'DEGRADED' || !sync.verified ? ' · uncertain' : ''}
            </p>
          ) : (
            <p className="text-xs text-slate-500">No VOD sync</p>
          )}
        </div>
      </header>

      <GameplayStatusBar
        view={deriveGameplayBar({
          status: gameplayStatus,
          nativeReplaySupported,
          hasInlineVideo: mediaUrl !== null,
          videoSynced: sync !== null,
          opening: openingReplay,
          seeking: seekingMs !== null
        })}
        onOpen={() => {
          void openReplay()
        }}
        onClose={() => {
          const sourceId = gameplayStatus?.active_source_id
          if (!review || sourceId === null || sourceId === undefined) {
            return
          }
          void window.rift.closeReplay(sourceId, review.match_id).then((result) => {
            if (result.ok) {
              setGameplayStatus(result.status)
              setPlayingTargetMs(null)
              setPendingRevealMs(null)
              pendingRevealRef.current = null
              void window.rift.overlayClose()
            } else {
              setSyncMessage(result.message)
            }
          })
        }}
        onRetry={() => {
          void openReplay()
        }}
        onAction={handleReplayAction}
      />
      {overlayNotice !== null ? (
        <div
          className="mb-3 rounded border border-amber-700/60 bg-amber-950/50 px-3 py-2 text-xs text-amber-100"
          data-testid="overlay-exclusive-fs-notice"
        >
          <p className="font-medium">{overlayNotice}</p>
          <ol className="mt-1 list-decimal pl-4 text-amber-50/90">
            <li>Open League video settings.</li>
            <li>Change Window Mode to Borderless.</li>
            <li>Return to the replay.</li>
          </ol>
          <button
            type="button"
            className="mt-2 rounded bg-amber-800 px-2 py-1 text-xs text-amber-50 hover:bg-amber-700"
            data-testid="overlay-recheck-main"
            onClick={() => void window.rift.overlayRecheckDisplay()}
          >
            Recheck
          </button>
        </div>
      ) : null}
      {pendingRevealMs !== null ? (
        <p className="mb-3 text-xs text-sky-200" data-testid="pending-reveal-hint">
          Open replay to jump to {formatMmss(pendingRevealMs)}
        </p>
      ) : null}
      {seekingMs !== null ? (
        <p className="mb-3 text-xs text-sky-200" data-testid="seeking-indicator">
          Seeking…
        </p>
      ) : null}

      <ImportReplayWizard
        open={wizardOpen}
        matchId={review.match_id}
        onClose={() => setWizardOpen(false)}
        onLinked={(sourceId) => {
          setActiveMode('replay')
          void refreshGameplay(review.match_id, sourceId)
        }}
        onAction={handleReplayAction}
      />

      {review.fixture_warning ? (
        <p
          className="mb-3 rounded border border-amber-700/70 bg-amber-950/50 px-3 py-2 text-sm text-amber-100"
          data-testid="fixture-warning"
        >
          {review.fixture_warning}
        </p>
      ) : null}

      <div className="grid grid-cols-12 gap-3">
        <div className="col-span-8 space-y-3">
          <VideoPlayer
            src={mediaUrl}
            playheadMs={playheadMs}
            onTimeMs={setPlayheadMs}
            seekRequestMs={seekRequestMs}
            error={vodError}
            warning={vodWarning}
            playbackRate={rate}
            onPlaybackRate={setRate}
            onAttach={() => {
              void attachVod(setVodError, setVodWarning, setMediaUrl, setProbe)
            }}
          />
          <ManualSyncBar
            clockInput={clockInput}
            onClockInput={setClockInput}
            disabled={probe === null}
            message={syncMessage}
            onConfirm={() => {
              void confirmSync({
                review,
                probe,
                playheadMs,
                clockInput,
                setSync,
                setSyncMessage
              })
            }}
          />
          <MarkerTrack
            review={review}
            sync={sync}
            nativeReady={preferNative}
            playheadMs={playheadMs}
            onSelect={(tMs, itemId, findingId) => {
              if (itemId !== null) {
                setSelectedItemId(itemId)
              }
              setSelectedFindingId(findingId)
              seekToGame(tMs)
            }}
          />
          <ItemDetail
            item={selectedItem}
            finding={selectedFinding}
            onSeek={seekToGame}
            seekingMs={seekingMs}
            playingTargetMs={playingTargetMs}
            pendingReveal={preferNative && !nativeSessionReady(gameplayStatus)}
          />
        </div>
        <aside className="col-span-4 space-y-3">
          <FocusList
            title="Focus on these"
            testId="focus-items"
            items={review.focus_items}
            selectedId={selectedItem?.id ?? null}
            onSelect={(item) => {
              setSelectedItemId(item.id)
              setSelectedFindingId(item.exemplar_finding_id)
              const first = item.evidence_timestamps_ms[0]
              if (first !== undefined) {
                seekToGame(first)
              }
            }}
          />
          <FocusList
            title="Also noticed"
            testId="secondary-items"
            items={review.secondary_items}
            selectedId={selectedItem?.id ?? null}
            onSelect={(item) => {
              setSelectedItemId(item.id)
              setSelectedFindingId(item.exemplar_finding_id)
            }}
          />
          <FocusList
            title="What went well"
            testId="strength-items"
            items={review.strengths}
            selectedId={selectedItem?.id ?? null}
            onSelect={(item) => {
              setSelectedItemId(item.id)
              setSelectedFindingId(item.exemplar_finding_id)
            }}
          />
          <StatsPanel metrics={review.metrics} />
        </aside>
      </div>
    </main>
  )
}

function BackLink(): ReactElement {
  return (
    <button
      type="button"
      className="text-sm text-sky-400 hover:underline"
      onClick={() => {
        window.location.hash = '#/'
      }}
    >
      ← Reviews
    </button>
  )
}

function FocusList(props: {
  title: string
  testId: string
  items: CoachingItem[]
  selectedId: string | null
  onSelect: (item: CoachingItem) => void
}): ReactElement {
  return (
    <section className="rounded-lg border border-slate-800 p-3" data-testid={props.testId}>
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">{props.title}</h2>
      {props.items.length === 0 ? (
        <p className="mt-2 text-xs text-slate-500">None</p>
      ) : (
        <ol className="mt-2 space-y-2">
          {props.items.map((item, index) => (
            <li key={item.id}>
              <button
                type="button"
                className={`w-full rounded px-2 py-1.5 text-left text-sm ${
                  props.selectedId === item.id ? 'bg-sky-900/70' : 'hover:bg-slate-900'
                }`}
                onClick={() => props.onSelect(item)}
              >
                <div className="font-medium">
                  {index + 1}. {item.title}
                </div>
                <div className="text-xs text-slate-400">
                  {item.issue_type} · {item.certainty} · {item.cost_summary} ·{' '}
                  {item.evidence_timestamps_ms.map(formatMmss).join(' ')}
                </div>
              </button>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

function ItemDetail(props: {
  item: CoachingItem | null
  finding: Finding | null
  onSeek: (tMs: number) => void
  seekingMs: number | null
  playingTargetMs: number | null
  pendingReveal: boolean
}): ReactElement {
  if (props.item === null) {
    return (
      <section className="rounded-lg border border-slate-800 p-3 text-sm text-slate-500">
        Select a coaching item.
      </section>
    )
  }
  return (
    <section className="rounded-lg border border-slate-800 p-3" data-testid="item-detail">
      <h2 className="text-lg font-semibold">{props.item.title}</h2>
      <p className="mt-1 text-xs uppercase text-slate-400">
        {props.item.issue_type} · confidence {(props.item.confidence * 100).toFixed(0)}% ·{' '}
        {props.item.certainty}
      </p>
      <p className="mt-3 whitespace-pre-wrap text-sm text-slate-200">{props.item.body}</p>
      {props.item.the_fix ? (
        <div className="mt-3">
          <h3 className="text-xs font-semibold uppercase text-slate-400">Instead</h3>
          <p className="text-sm">{props.item.the_fix}</p>
        </div>
      ) : null}
      {props.item.next_game_check ? (
        <div className="mt-3">
          <h3 className="text-xs font-semibold uppercase text-slate-400">Next game check</h3>
          <p className="text-sm">{props.item.next_game_check}</p>
        </div>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-2">
        {props.item.evidence_timestamps_ms.map((tMs) => (
          <button
            key={tMs}
            type="button"
            data-testid={`timestamp-${tMs}`}
            className="rounded bg-slate-800 px-2 py-1 text-xs hover:bg-slate-700"
            onClick={() => props.onSeek(tMs)}
          >
            {formatMmss(tMs)}
            {props.seekingMs === tMs
              ? ' · seeking…'
              : props.playingTargetMs === tMs
                ? ' · playing'
                : props.pendingReveal
                  ? ' · open replay'
                  : ''}
          </button>
        ))}
      </div>
      {props.finding ? <EvidencePanel finding={props.finding} /> : null}
    </section>
  )
}

function EvidencePanel({ finding }: { finding: Finding }): ReactElement {
  return (
    <div className="mt-4 border-t border-slate-800 pt-3" data-testid="evidence-panel">
      <h3 className="text-xs font-semibold uppercase text-slate-400">
        Evidence · {finding.rule_id} · {finding.t_mmss} · conf {(finding.confidence * 100).toFixed(0)}%
      </h3>
      <ul className="mt-2 space-y-1 text-sm">
        {finding.evidence.map((item, index) => (
          <li key={`${item.label}-${index}`} className="text-slate-200">
            <span className="text-slate-400">{item.label}</span>: {formatEvidenceValue(item.value)}
            {item.confidence !== null ? ` · c=${item.confidence.toFixed(2)}` : ''}
            {item.source ? ` · ${item.source}` : ''}
            {item.quarantined ? (
              <span className="ml-2 text-amber-300">unverified (not a proven fact)</span>
            ) : null}
            {item.provenance ? (
              <span className="ml-2 text-xs text-slate-500">
                via {item.provenance.producer} v{item.provenance.producer_version}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  )
}

function StatsPanel({ metrics }: { metrics: ReviewPresentation['metrics'] }): ReactElement {
  return (
    <section className="rounded-lg border border-slate-800 p-3" data-testid="metric-summary">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Match stats</h2>
      <ul className="mt-2 space-y-1 text-sm">
        {metrics.map((metric) => (
          <li key={`${metric.metric_id}-${metric.phase ?? 'all'}`}>
            <span className="text-slate-300">{metric.metric_id}</span>{' '}
            <span className="font-mono">
              {metric.value.toFixed(2)} {metric.unit}
            </span>
            {metric.baseline_percentile !== null ? (
              <span className="text-xs text-slate-500"> p{Math.round(metric.baseline_percentile)}</span>
            ) : null}
            <span className="text-xs text-slate-500"> · c={metric.confidence.toFixed(2)}</span>
            {metric.quarantined ? (
              <span className="ml-1 text-xs text-amber-300">unverified</span>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  )
}

function MarkerTrack(props: {
  review: ReviewPresentation
  sync: SyncMapData | null
  nativeReady: boolean
  playheadMs: number
  onSelect: (tMs: number, itemId: string | null, findingId: string | null) => void
}): ReactElement {
  const duration = Math.max(1, props.review.duration_ms)
  const markers = props.review.focus_items.flatMap((item) =>
    item.evidence_timestamps_ms.map((tMs) => ({ tMs, itemId: item.id, findingId: item.exemplar_finding_id }))
  )
  return (
    <section className="rounded-lg border border-slate-800 p-3" data-testid="marker-track">
      <h2 className="text-xs font-semibold uppercase text-slate-400">Timestamps</h2>
      <div className="relative mt-2 h-8 rounded bg-slate-900">
        {markers.map((marker, index) => {
          const left = `${(marker.tMs / duration) * 100}%`
          const target = seekTarget(props.sync, marker.tMs)
          const covered = props.nativeReady || target.covered
          return (
            <button
              key={`${marker.itemId}-${marker.tMs}-${index}`}
              type="button"
              title={`${formatMmss(marker.tMs)}${covered ? '' : ' (no VOD coverage)'}`}
              className={`absolute top-1 h-6 w-1.5 -translate-x-1/2 rounded ${
                covered ? 'bg-sky-400' : 'bg-slate-500'
              } ${!props.nativeReady && target.uncertain ? 'opacity-60' : ''}`}
              style={{ left }}
              onClick={() => props.onSelect(marker.tMs, marker.itemId, marker.findingId)}
            />
          )
        })}
      </div>
      <p className="mt-1 text-xs text-slate-500">
        Video playhead {formatMmss(props.playheadMs)} · grey markers have no sync coverage
      </p>
    </section>
  )
}

function ManualSyncBar(props: {
  clockInput: string
  onClockInput: (value: string) => void
  disabled: boolean
  message: string | null
  onConfirm: () => void
}): ReactElement {
  return (
    <section className="rounded-lg border border-slate-800 p-3 text-sm" data-testid="manual-vod-sync">
      <h2 className="text-xs font-semibold uppercase text-slate-400">Manual VOD sync</h2>
      <p className="mt-1 text-xs text-slate-500">
        Pause on a frame, type the in-game clock you see, then confirm. One anchor is approximate.
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input
          value={props.clockInput}
          className="w-24 rounded border border-slate-700 bg-slate-900 px-2 py-1 font-mono"
          placeholder="m:ss"
          onChange={(event) => props.onClockInput(event.target.value)}
        />
        <button
          type="button"
          disabled={props.disabled}
          className="rounded bg-sky-700 px-3 py-1 disabled:opacity-50"
          onClick={props.onConfirm}
        >
          Clock reads this
        </button>
      </div>
      {props.message ? <p className="mt-2 text-xs text-amber-200">{props.message}</p> : null}
    </section>
  )
}

function formatEvidenceValue(value: unknown): string {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function parseClockMs(text: string): number | null {
  const parts = text.trim().split(':')
  const nums = parts.map((part) => Number(part))
  if (nums.some((value) => Number.isNaN(value) || value < 0)) {
    return null
  }
  if (parts.length === 2 && nums[0] !== undefined && nums[1] !== undefined && nums[1] < 60) {
    return Math.round((nums[0] * 60 + nums[1]) * 1000)
  }
  if (
    parts.length === 3 &&
    nums[0] !== undefined &&
    nums[1] !== undefined &&
    nums[2] !== undefined &&
    nums[1] < 60 &&
    nums[2] < 60
  ) {
    return Math.round((nums[0] * 3600 + nums[1] * 60 + nums[2]) * 1000)
  }
  return null
}

async function attachVod(
  setError: (value: string | null) => void,
  setWarning: (value: string | null) => void,
  setUrl: (value: string | null) => void,
  setProbe: (value: MediaProbe | null) => void
): Promise<void> {
  setError(null)
  const picked = await window.rift.pickVod()
  if (!picked.ok) {
    setError(picked.message)
    return
  }
  if (picked.path === null) {
    return
  }
  const probed = await window.rift.probeVod(picked.path)
  if (!probed.ok) {
    setUrl(null)
    setProbe(null)
    setError(probed.message)
    return
  }
  setUrl(probed.mediaUrl)
  setProbe(probed.probe)
  setWarning(probed.message)
}

async function confirmSync(args: {
  review: ReviewPresentation
  probe: MediaProbe | null
  playheadMs: number
  clockInput: string
  setSync: (value: SyncMapData) => void
  setSyncMessage: (value: string | null) => void
}): Promise<void> {
  if (args.probe === null) {
    args.setSyncMessage('Attach a playable VOD before setting sync.')
    return
  }
  const tGame = parseClockMs(args.clockInput)
  if (tGame === null) {
    args.setSyncMessage('Enter the game clock as m:ss or h:mm:ss.')
    return
  }
  const result = await window.rift.buildManualSync({
    matchId: args.review.match_id,
    videoDurationMs: args.probe.duration_ms,
    matchDurationMs: args.review.duration_ms,
    anchors: [{ t_video_ms: args.playheadMs, t_game_ms: tGame }]
  })
  if (!result.ok) {
    args.setSyncMessage(result.message)
    return
  }
  args.setSync(result.sync_map)
  args.setSyncMessage(
    `Anchor set: video ${formatMmss(args.playheadMs)} ↔ game ${formatMmss(tGame)}. ${
      result.sync_map.quality.verdict === 'DEGRADED' ? 'Single-anchor sync is approximate.' : ''
    }`
  )
}
