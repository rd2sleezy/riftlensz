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
import { Badge, Card, Disclosure, EmptyState, SectionLabel } from '../../components/ui'
import {
  formatConfidencePct,
  formatResult,
  humanizeConceptId,
  humanizeIdentifier,
  humanizeMetricId,
  humanizePhase,
  humanizeRole
} from '../../lib/humanize'
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
  const platformQuery = useQuery({
    queryKey: ['desktop-platform'],
    queryFn: () => window.rift.getDesktopPlatform()
  })
  const e2eMode = platformQuery.data?.e2eMode === true

  useEffect(() => {
    if (review === undefined) {
      return
    }
    const fixtureId = review.fixture_id
    const matchId = review.match_id
    const isFixture =
      (typeof fixtureId === 'string' && fixtureId.startsWith('NA1_fixture_')) ||
      (typeof matchId === 'string' && matchId.startsWith('NA1_fixture_'))
    if (isFixture && !e2eMode) {
      window.location.hash = '#/'
    }
  }, [e2eMode, review])

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

  const overlayCompanionSupported = platformQuery.data?.overlayCompanionSupported === true


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
      if (action === 'sign_in_api_key') {
        setOverlayNotice(
          'Sign in with a Riot developer API key from the home Account menu, then import the replay again.'
        )
        setWizardOpen(false)
        window.location.hash = '#/'
        return
      }
      if (action === 'enable_replay_api') {
        void (async () => {
          const result = await window.rift.enableReplayApi()
          if (!result.ok) {
            setOverlayNotice(
              result.error?.message ?? 'Could not enable Replay API in game.cfg.'
            )
            return
          }
          setOverlayNotice(
            result.requires_restart
              ? 'Replay API enabled. Restart League, then Open Replay.'
              : 'Replay API already enabled. Open Replay when ready.'
          )
          if (review !== undefined) {
            void refreshGameplay(review.match_id, gameplayStatus?.active_source_id)
          }
        })()
        return
      }
      if (action === 'open_replay' || action === 'reopen_replay' || action === 'retry' || action === 'try_anyway') {
        void openReplay()
      }
    },
    [gameplayStatus?.active_source_id, openReplay, refreshGameplay, review]
  )

  useEffect(() => {
    if (review === undefined) {
      return
    }
    const ready = nativeSessionReady(gameplayStatus)
    const sourceId = gameplayStatus?.active_source_id
    if (
      !overlayCompanionSupported ||
      !ready ||
      sourceId === null ||
      sourceId === undefined ||
      !preferNative
    ) {
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
    overlayCompanionSupported,
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

  const selectItem = useCallback((item: CoachingItem) => {
    setSelectedItemId(item.id)
    setSelectedFindingId(item.exemplar_finding_id)
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
      <main className="min-h-screen p-8 text-slate-100">
        <BackLink />
        <p className="mt-6 text-rift-danger" data-testid="review-error">
          {reviewQuery.error instanceof Error ? reviewQuery.error.message : 'Review unavailable'}
        </p>
      </main>
    )
  }

  if (review === undefined) {
    return (
      <main className="min-h-screen p-8 text-slate-100">
        <BackLink />
        <div className="mt-6 space-y-3">
          <div className="h-24 animate-pulse rounded-xl border border-rift-border bg-rift-surface" />
          <p className="text-sm text-slate-500">Loading review…</p>
        </div>
      </main>
    )
  }

  const result = formatResult(review.result)
  const resultVariant = result === 'Victory' ? 'win' : result === 'Defeat' ? 'loss' : 'neutral'

  return (
    <main className="min-h-screen p-4 text-slate-100 sm:p-6">
      <div className="mx-auto max-w-[1400px]">
        <header className="mb-4 flex flex-wrap items-start justify-between gap-4">
          <div>
            <BackLink />
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold" data-testid="review-identity">
                {review.champion} {review.role} · {review.result ?? 'unknown result'} ·{' '}
                {formatMmss(review.duration_ms)} · Patch {review.patch} · pid {review.participant_id}
              </h1>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Badge variant={resultVariant}>{result}</Badge>
              <span className="text-sm text-slate-400">
                {review.champion} · {humanizeRole(review.role)} · {formatMmss(review.duration_ms)}
              </span>
              <span className="font-mono text-xs text-slate-600">
                {review.match_id} · rank {review.rank} · {review.engine_version}
              </span>
            </div>
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
              <Badge variant={sync.quality.verdict === 'DEGRADED' || !sync.verified ? 'gold' : 'win'}>
                <span data-testid="sync-status">
                  Sync {sync.quality.verdict}
                  {sync.quality.verdict === 'DEGRADED' || !sync.verified ? ' · uncertain' : ''}
                </span>
              </Badge>
            ) : (
              <span className="text-xs text-slate-500">No VOD sync</span>
            )}
          </div>
        </header>

        {review.fixture_warning ? (
          <p
            className="mb-4 rounded-lg border border-rift-gold/25 bg-rift-gold-soft px-3 py-2 text-sm text-amber-100"
            data-testid="fixture-warning"
          >
            {review.fixture_warning}
          </p>
        ) : null}

        <section className="mb-4" data-testid="focus-items">
          <SectionLabel className="mb-2">Your coaching plan from this match</SectionLabel>
          {review.focus_items.length === 0 ? (
            <EmptyState title="No primary coaching focuses for this match." />
          ) : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              {review.focus_items.map((item, index) => (
                <FocusCard
                  key={item.id}
                  item={item}
                  rank={index + 1}
                  selected={selectedItem?.id === item.id}
                  onSelect={() => {
                    selectItem(item)
                    const first = item.evidence_timestamps_ms[0]
                    if (first !== undefined) {
                      seekToGame(first)
                    }
                  }}
                />
              ))}
            </div>
          )}
        </section>

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
            className="mb-3 rounded-lg border border-rift-gold/25 bg-rift-gold-soft px-3 py-2 text-xs text-amber-100"
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
              className="mt-2 rounded-md bg-rift-accent px-2 py-1 text-xs font-medium text-rift-bg hover:bg-rift-accent-strong"
              data-testid="overlay-recheck-main"
              onClick={() => void window.rift.overlayRecheckDisplay()}
            >
              Recheck
            </button>
          </div>
        ) : null}
        {pendingRevealMs !== null || playingTargetMs !== null ? (
          <p className="mb-2 text-xs text-slate-400" data-testid="gameplay-seek-status">
            {seekingMs !== null
              ? `Seeking League replay to ${formatMmss(seekingMs)}…`
              : pendingRevealMs !== null
                ? `Queued seek to ${formatMmss(pendingRevealMs)}`
                : playingTargetMs !== null
                  ? `Replay at ${formatMmss(playingTargetMs)}`
                  : null}
          </p>
        ) : null}

        <div className="grid grid-cols-12 gap-3">
          <div className="col-span-12 space-y-3 xl:col-span-8">
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
                setActiveMode('video')
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
              playheadMs={playheadMs}
              onSelect={(tMs, itemId, findingId) => {
                if (itemId !== null) {
                  setSelectedItemId(itemId)
                }
                setSelectedFindingId(findingId)
                seekToGame(tMs)
              }}
            />
            <ItemDetail item={selectedItem} finding={selectedFinding} onSeek={seekToGame} />
          </div>
          <aside className="col-span-12 space-y-3 xl:col-span-4">
            <ObservationList
              title="Also noticed"
              testId="secondary-items"
              items={review.secondary_items}
              selectedId={selectedItem?.id ?? null}
              onSelect={selectItem}
            />
            <ObservationList
              title="What you did well"
              testId="strength-items"
              items={review.strengths}
              selectedId={selectedItem?.id ?? null}
              onSelect={selectItem}
              positive
            />
            <StatsPanel metrics={review.metrics} />
          </aside>
        </div>
      </div>
      <ImportReplayWizard
        open={wizardOpen}
        matchId={review.match_id}
        onClose={() => setWizardOpen(false)}
        onLinked={(sourceId, linkedMatchId) => {
          setActiveMode('replay')
          void refreshGameplay(linkedMatchId, sourceId)
        }}
        onOpenReview={(nextReviewId) => {
          setWizardOpen(false)
          window.location.hash = `#/review/${encodeURIComponent(nextReviewId)}`
        }}
        onAction={handleReplayAction}
      />
    </main>
  )
}

function BackLink(): ReactElement {
  return (
    <button
      type="button"
      className="text-sm text-rift-accent-strong hover:underline"
      onClick={() => {
        window.location.hash = '#/'
      }}
    >
      ← Reviews
    </button>
  )
}

function FocusCard(props: {
  item: CoachingItem
  rank: number
  selected: boolean
  onSelect: () => void
}): ReactElement {
  const { item } = props
  return (
    <button
      type="button"
      onClick={props.onSelect}
      className={`group flex flex-col gap-2.5 rounded-xl border p-4 text-left transition ${
        props.selected
          ? 'border-rift-accent/60 bg-rift-accent-soft shadow-glow'
          : 'border-rift-border bg-rift-surface hover:border-rift-accent/30 hover:bg-rift-raised'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span
          className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
            props.selected ? 'bg-rift-accent text-rift-bg' : 'bg-white/10 text-slate-300'
          }`}
        >
          {props.rank}
        </span>
        <Badge variant="neutral" className="capitalize">
          {humanizeIdentifier(item.issue_type)}
        </Badge>
      </div>
      <h3 className="text-sm font-semibold leading-snug text-slate-100">{item.title}</h3>
      <p className="line-clamp-3 text-xs leading-relaxed text-slate-400">{item.body}</p>
      <div className="mt-auto flex items-center justify-between pt-1 text-[11px] text-slate-500">
        <span>{item.cost_summary}</span>
        <span>{formatConfidencePct(item.confidence)} confidence</span>
      </div>
    </button>
  )
}

function ObservationList(props: {
  title: string
  testId: string
  items: CoachingItem[]
  selectedId: string | null
  onSelect: (item: CoachingItem) => void
  positive?: boolean
}): ReactElement {
  return (
    <Card className="p-3" testId={props.testId}>
      <SectionLabel>{props.title}</SectionLabel>
      {props.items.length === 0 ? (
        <p className="mt-2 text-xs text-slate-600">None</p>
      ) : (
        <ol className="mt-2 space-y-1">
          {props.items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className={`w-full rounded-lg px-2.5 py-2 text-left text-sm transition ${
                  props.selectedId === item.id
                    ? 'bg-rift-accent-soft text-slate-100'
                    : 'text-slate-300 hover:bg-white/5'
                }`}
                onClick={() => props.onSelect(item)}
              >
                <div className="flex items-center gap-1.5 font-medium">
                  {props.positive ? (
                    <span className="text-rift-win">✓</span>
                  ) : (
                    <span className="text-slate-600">·</span>
                  )}
                  {item.title}
                </div>
                <div className="mt-0.5 text-xs text-slate-500">
                  {humanizeIdentifier(item.issue_type)} · {item.cost_summary}
                </div>
              </button>
            </li>
          ))}
        </ol>
      )}
    </Card>
  )
}

function ItemDetail(props: {
  item: CoachingItem | null
  finding: Finding | null
  onSeek: (tMs: number) => void
}): ReactElement {
  if (props.item === null) {
    return (
      <Card className="p-4">
        <EmptyState title="Select a coaching item to see the full breakdown." />
      </Card>
    )
  }
  const item = props.item
  return (
    <Card className="animate-fade-in p-4" testId="item-detail">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="neutral">{humanizeIdentifier(item.issue_type)}</Badge>
        <Badge variant="accent">{formatConfidencePct(item.confidence)} confidence</Badge>
        <span className="text-xs text-slate-500">{humanizeIdentifier(item.certainty)}</span>
      </div>
      <h2 className="mt-2 text-lg font-semibold">{item.title}</h2>

      <div className="mt-3">
        <SectionLabel>{item.is_strength ? 'What you did well' : 'What happened'}</SectionLabel>
        <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-slate-200">{item.body}</p>
      </div>

      {!item.is_strength && item.the_fix ? (
        <div className="mt-3">
          <SectionLabel>What to do instead</SectionLabel>
          <p className="mt-1 text-sm leading-relaxed text-slate-200">{item.the_fix}</p>
        </div>
      ) : null}

      {item.next_game_check ? (
        <div className="mt-3 rounded-lg border border-rift-accent/25 bg-rift-accent-soft px-3 py-2.5">
          <SectionLabel className="text-rift-accent-strong">Next-game goal</SectionLabel>
          <p className="mt-1 text-sm leading-relaxed text-slate-100">{item.next_game_check}</p>
        </div>
      ) : null}

      {item.evidence_timestamps_ms.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {item.evidence_timestamps_ms.map((tMs) => (
            <button
              key={tMs}
              type="button"
              className="rounded-md bg-white/5 px-2 py-1 text-xs text-slate-300 transition hover:bg-white/10"
              onClick={() => props.onSeek(tMs)}
            >
              ▶ {formatMmss(tMs)}
            </button>
          ))}
        </div>
      ) : null}

      <div className="mt-4 border-t border-rift-border pt-3">
        <Disclosure summary="Why RiftLens flagged this" testId="why-flagged">
          <div className="space-y-2 text-xs text-slate-400">
            <p>
              Concept: <span className="text-slate-300">{humanizeConceptId(item.root_concept_id)}</span>{' '}
              · occurred {item.occurrences} {item.occurrences === 1 ? 'time' : 'times'}
            </p>
            <p>{item.grouping_reason}</p>
            {props.finding ? <EvidencePanel finding={props.finding} /> : null}
          </div>
        </Disclosure>
      </div>
    </Card>
  )
}

function EvidencePanel({ finding }: { finding: Finding }): ReactElement {
  return (
    <div className="mt-2 border-t border-rift-border pt-2" data-testid="evidence-panel">
      <p className="font-mono text-[11px] text-slate-500">
        {finding.rule_id} rev{finding.rule_version} · {finding.t_mmss} · conf{' '}
        {formatConfidencePct(finding.confidence)}
      </p>
      <ul className="mt-2 space-y-1.5">
        {finding.evidence.map((item, index) => (
          <li key={`${item.label}-${index}`} className="text-slate-300">
            <span className="text-slate-500">{humanizeIdentifier(item.label)}</span>:{' '}
            {formatEvidenceValue(item.value)}
            {item.confidence !== null ? ` · c=${item.confidence.toFixed(2)}` : ''}
            {item.source ? ` · ${item.source}` : ''}
            {item.quarantined ? (
              <span className="ml-2 text-rift-gold">unverified (not a proven fact)</span>
            ) : null}
            {item.provenance ? (
              <span className="ml-2 text-slate-600">
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
    <Card className="p-3" testId="metric-summary">
      <SectionLabel>Match stats</SectionLabel>
      <ul className="mt-2 space-y-2">
        {metrics.map((metric) => (
          <li key={`${metric.metric_id}-${metric.phase ?? 'all'}`} className="text-sm">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-slate-300" title={metric.metric_id}>
                {humanizeMetricId(metric.metric_id)}
                {metric.phase !== null ? (
                  <span className="ml-1 text-xs text-slate-600">· {humanizePhase(metric.phase)}</span>
                ) : null}
              </span>
              <span className="font-mono text-slate-100">
                {metric.value.toFixed(2)} {metric.unit}
              </span>
            </div>
            {metric.baseline_percentile !== null ? (
              <div className="mt-1 h-1 overflow-hidden rounded-full bg-white/5">
                <div
                  className="h-full rounded-full bg-rift-accent/70"
                  style={{ width: `${Math.min(100, Math.max(0, metric.baseline_percentile))}%` }}
                />
              </div>
            ) : null}
            {metric.quarantined ? (
              <span className="text-[11px] text-rift-gold">unverified</span>
            ) : null}
          </li>
        ))}
      </ul>
    </Card>
  )
}

function MarkerTrack(props: {
  review: ReviewPresentation
  sync: SyncMapData | null
  playheadMs: number
  onSelect: (tMs: number, itemId: string | null, findingId: string | null) => void
}): ReactElement {
  const duration = Math.max(1, props.review.duration_ms)
  const markers = props.review.focus_items.flatMap((item) =>
    item.evidence_timestamps_ms.map((tMs) => ({ tMs, itemId: item.id, findingId: item.exemplar_finding_id }))
  )
  return (
    <Card className="p-3" testId="marker-track">
      <SectionLabel>Timestamps</SectionLabel>
      <div className="relative mt-2 h-8 rounded-lg bg-rift-raised">
        {markers.map((marker, index) => {
          const left = `${(marker.tMs / duration) * 100}%`
          const target = seekTarget(props.sync, marker.tMs)
          return (
            <button
              key={`${marker.itemId}-${marker.tMs}-${index}`}
              type="button"
              title={`${formatMmss(marker.tMs)}${target.covered ? '' : ' (no VOD coverage)'}`}
              className={`absolute top-1 h-6 w-1.5 -translate-x-1/2 rounded-full transition ${
                target.covered ? 'bg-rift-accent' : 'bg-slate-600'
              } ${target.uncertain ? 'opacity-60' : ''}`}
              style={{ left }}
              onClick={() => props.onSelect(marker.tMs, marker.itemId, marker.findingId)}
            />
          )
        })}
      </div>
      <p className="mt-1.5 text-xs text-slate-600">
        Video playhead {formatMmss(props.playheadMs)} · grey markers have no sync coverage
      </p>
    </Card>
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
    <Card className="p-3 text-sm" testId="manual-vod-sync">
      <SectionLabel>Manual VOD sync</SectionLabel>
      <p className="mt-1 text-xs text-slate-500">
        Pause on a frame, type the in-game clock you see, then confirm. One anchor is approximate.
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input
          value={props.clockInput}
          className="w-24 rounded-md border border-rift-edge bg-rift-raised px-2 py-1 font-mono text-slate-100 focus:border-rift-accent/50"
          placeholder="m:ss"
          onChange={(event) => props.onClockInput(event.target.value)}
        />
        <button
          type="button"
          disabled={props.disabled}
          className="rounded-md bg-rift-accent px-3 py-1 font-medium text-rift-bg transition hover:bg-rift-accent-strong disabled:cursor-not-allowed disabled:opacity-40"
          onClick={props.onConfirm}
        >
          Clock reads this
        </button>
      </div>
      {props.message ? <p className="mt-2 text-xs text-rift-gold">{props.message}</p> : null}
    </Card>
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
