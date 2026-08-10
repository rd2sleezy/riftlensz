import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState, type ReactElement } from 'react'
import type {
  CoachingItem,
  Finding,
  MediaProbe,
  ReviewPresentation
} from '../../../main/ipc/channels'
import { type SyncMapData, formatMmss, seekTarget } from '../../../main/sync/syncMap'
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

  const seekToGame = useCallback(
    (tGameMs: number) => {
      const target = seekTarget(sync, tGameMs)
      if (!target.covered || target.seek_video_ms === null) {
        setSyncMessage(target.reason ?? 'Cannot seek — sync does not cover this timestamp.')
        return
      }
      setSeekRequestMs(target.seek_video_ms)
      setSyncMessage(target.uncertain ? target.reason : null)
    },
    [sync]
  )

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
        {sync ? (
          <p className="text-xs text-slate-300" data-testid="sync-status">
            Sync {sync.quality.verdict}
            {sync.quality.verdict === 'DEGRADED' || !sync.verified ? ' · uncertain' : ''}
          </p>
        ) : (
          <p className="text-xs text-slate-500">No VOD sync</p>
        )}
      </header>

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
            className="rounded bg-slate-800 px-2 py-1 text-xs hover:bg-slate-700"
            onClick={() => props.onSeek(tMs)}
          >
            {formatMmss(tMs)}
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
          return (
            <button
              key={`${marker.itemId}-${marker.tMs}-${index}`}
              type="button"
              title={`${formatMmss(marker.tMs)}${target.covered ? '' : ' (no VOD coverage)'}`}
              className={`absolute top-1 h-6 w-1.5 -translate-x-1/2 rounded ${
                target.covered ? 'bg-sky-400' : 'bg-slate-500'
              } ${target.uncertain ? 'opacity-60' : ''}`}
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
    <section className="rounded-lg border border-slate-800 p-3 text-sm">
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
