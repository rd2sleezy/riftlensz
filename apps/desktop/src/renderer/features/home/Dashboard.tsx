import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactElement } from 'react'
import { AccountMenu } from '../auth/AccountMenu'
import { SystemStatus } from '../diagnostics/SystemStatus'
import { formatMmss } from '../../../main/sync/syncMap'
import type { OpenFixtureInput, ReviewSummary } from '../../../main/ipc/channels'
import { Badge, Card, EmptyState, SectionLabel } from '../../components/ui'
import { formatResult, humanizeRole } from '../../lib/humanize'
import { ImportReplayWizard } from '../review/ImportReplayWizard'
import type { ReplayActionId } from '../review/replayErrors'

const FIXTURES: { id: OpenFixtureInput['fixtureId']; label: string }[] = [
  { id: 'NA1_fixture_a', label: 'Fixture A' },
  { id: 'NA1_fixture_b', label: 'Fixture B' },
  { id: 'NA1_fixture_c', label: 'Fixture C' }
]

export function Dashboard(): ReactElement {
  const queryClient = useQueryClient()
  const [pid, setPid] = useState(5)
  const [error, setError] = useState<string | null>(null)
  const [wizardOpen, setWizardOpen] = useState(false)
  const statusQuery = useQuery({
    queryKey: ['sidecar-status'],
    queryFn: () => window.rift.getSidecarStatus()
  })
  const platformQuery = useQuery({
    queryKey: ['desktop-platform'],
    queryFn: () => window.rift.getDesktopPlatform()
  })
  const reviewsQuery = useQuery({
    queryKey: ['reviews'],
    queryFn: () => window.rift.listReviews(),
    enabled: statusQuery.data?.state === 'ready',
    refetchInterval: 5_000
  })

  const openFixture = useMutation({
    mutationFn: (fixtureId: OpenFixtureInput['fixtureId']) =>
      window.rift.openFixtureReview({ fixtureId, participantId: pid, rank: 'UNRANKED' }),
    onSuccess: (result) => {
      if (!result.ok) {
        setError(result.message)
        return
      }
      setError(null)
      queryClient.setQueryData(['review', result.review.id], result.review)
      void queryClient.invalidateQueries({ queryKey: ['reviews'] })
      window.location.hash = `#/review/${result.review.id}`
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : 'Failed to build review')
    }
  })

  const reviews = reviewsQuery.data?.ok === true ? reviewsQuery.data.reviews : []
  const listError = reviewsQuery.data?.ok === false ? reviewsQuery.data.message : null
  const ready = statusQuery.data?.state === 'ready'
  const e2eMode = platformQuery.data?.e2eMode === true
  const nativeReplaySupported = platformQuery.data?.nativeReplaySupported === true

  const handleReplayAction = (action: ReplayActionId): void => {
    if (action === 'sign_in_api_key') {
      setError('Sign in with a Riot developer API key above, then import the replay again.')
      setWizardOpen(false)
    }
  }

  return (
    <main className="min-h-screen px-6 py-8 text-slate-100 sm:px-10 lg:px-16">
      <div className="mx-auto max-w-5xl">
        <header className="flex items-start justify-between gap-8">
          <div>
            <div className="flex items-center gap-2.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-rift-accent-soft text-rift-accent-strong">
                <svg viewBox="0 0 24 24" className="h-4.5 w-4.5" fill="none" aria-hidden="true">
                  <path
                    d="M12 2 3 7v6c0 5 4 8.5 9 9 5-.5 9-4 9-9V7l-9-5Z"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinejoin="round"
                  />
                  <path d="M12 7v10M8 9.5l8 5M16 9.5l-8 5" stroke="currentColor" strokeWidth="1.3" />
                </svg>
              </span>
              <h1 className="font-display text-xl font-semibold tracking-tight">RiftLens</h1>
            </div>
            <p className="mt-1.5 text-sm text-slate-500">Post-game coaching from real League replays</p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <SystemStatus compact />
            <AccountMenu />
          </div>
        </header>

        <Card className="mt-8 p-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-base font-semibold">Import a League replay</h2>
              <p className="mt-1 text-sm text-slate-500">
                Choose a <span className="font-mono text-slate-300">.rofl</span> file. RiftLens identifies
                the match, builds coaching for your champion, and links the replay.
              </p>
            </div>
            <button
              type="button"
              data-testid="home-import-replay"
              disabled={!ready || !nativeReplaySupported}
              className="rounded-lg bg-sky-700 px-4 py-2.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-40"
              onClick={() => {
                setError(null)
                setWizardOpen(true)
              }}
            >
              Import .rofl
            </button>
          </div>
          {!nativeReplaySupported ? (
            <p className="mt-3 text-sm text-slate-500">
              Native League replay import is available on Windows and macOS.
            </p>
          ) : null}
          {!ready ? (
            <p className="mt-3 flex items-center gap-1.5 text-sm text-slate-500">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-500" />
              Waiting for sidecar…
            </p>
          ) : null}
          {error ? (
            <p className="mt-3 text-sm text-rift-danger" data-testid="review-error">
              {error}
            </p>
          ) : null}
        </Card>

        {e2eMode ? (
          <Card className="mt-6 p-5" data-testid="dev-fixtures">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <h2 className="text-base font-semibold">Dev fixtures (E2E only)</h2>
                <p className="mt-1 text-sm text-slate-500">
                  Hidden in normal use. Pyke fixture trials are not saved to the home list.
                </p>
              </div>
              <label className="flex items-center gap-2 text-sm text-slate-400">
                Participant id
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={pid}
                  className="w-16 rounded-md border border-rift-edge bg-rift-raised px-2 py-1 text-slate-100 focus:border-rift-accent/50"
                  onChange={(event) => setPid(Number(event.target.value) || 5)}
                />
              </label>
            </div>
            <div className="mt-4 flex flex-wrap gap-3">
              {FIXTURES.map((fixture) => {
                const usableOffline = fixture.id === 'NA1_fixture_b'
                const disabled = (!ready && !usableOffline) || openFixture.isPending
                return (
                  <button
                    key={fixture.id}
                    type="button"
                    data-testid={fixture.id === 'NA1_fixture_b' ? 'open-fixture-b' : undefined}
                    disabled={disabled}
                    className="group flex flex-col items-start rounded-lg border border-rift-edge bg-rift-raised px-4 py-2.5 text-left transition hover:border-rift-accent/50 hover:bg-rift-accent-soft disabled:cursor-not-allowed disabled:opacity-40"
                    onClick={() => {
                      setError(null)
                      openFixture.mutate(fixture.id)
                    }}
                  >
                    <span className="text-sm font-medium text-slate-100">
                      {openFixture.isPending && openFixture.variables === fixture.id
                        ? 'Analyzing…'
                        : fixture.label}
                    </span>
                    <span className="font-mono text-[11px] text-slate-500">{fixture.id}</span>
                  </button>
                )
              })}
            </div>
          </Card>
        ) : null}

        <section className="mt-10">
          <SectionLabel>Saved reviews</SectionLabel>
          {listError ? <p className="mt-2 text-sm text-rift-danger">{listError}</p> : null}
          {reviews.length === 0 && listError === null ? (
            <div className="mt-3">
              <EmptyState
                title="No saved reviews yet"
                body="Import a .rofl replay to generate your first coaching review."
              />
            </div>
          ) : (
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
              {reviews.map((item) => (
                <ReviewCard key={item.id} item={item} />
              ))}
            </div>
          )}
        </section>
      </div>

      <ImportReplayWizard
        open={wizardOpen}
        matchId=""
        onClose={() => setWizardOpen(false)}
        onLinked={() => {
          void queryClient.invalidateQueries({ queryKey: ['reviews'] })
        }}
        onOpenReview={(reviewId) => {
          setWizardOpen(false)
          void queryClient.invalidateQueries({ queryKey: ['reviews'] })
          window.location.hash = `#/review/${encodeURIComponent(reviewId)}`
        }}
        onAction={handleReplayAction}
      />
    </main>
  )
}

function ReviewCard({ item }: { item: ReviewSummary }): ReactElement {
  const result = formatResult(item.result)
  const resultVariant = result === 'Victory' ? 'win' : result === 'Defeat' ? 'loss' : 'neutral'
  return (
    <button
      type="button"
      className="flex flex-col gap-2 rounded-xl border border-rift-border bg-rift-surface p-4 text-left shadow-card transition hover:border-rift-accent/40 hover:bg-rift-raised"
      onClick={() => {
        window.location.hash = `#/review/${item.id}`
      }}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-semibold text-slate-100">
          {item.champion} <span className="font-normal text-slate-400">· {humanizeRole(item.role)}</span>
        </span>
        <Badge variant={resultVariant}>{result}</Badge>
      </div>
      <div className="flex items-center gap-3 text-xs text-slate-500">
        <span>{formatMmss(item.duration_ms)}</span>
        <span className="h-1 w-1 rounded-full bg-slate-700" />
        <span>
          {item.focus_count} focus {item.focus_count === 1 ? 'area' : 'areas'}
        </span>
        {item.has_sync ? (
          <>
            <span className="h-1 w-1 rounded-full bg-slate-700" />
            <span className="text-rift-accent-strong">VOD synced</span>
          </>
        ) : null}
      </div>
      <span className="font-mono text-[11px] text-slate-600">{item.match_id}</span>
    </button>
  )
}
