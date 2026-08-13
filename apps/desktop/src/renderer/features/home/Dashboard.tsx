import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactElement } from 'react'
import { AccountMenu } from '../auth/AccountMenu'
import { SystemStatus } from '../diagnostics/SystemStatus'
import { formatMmss } from '../../../main/sync/syncMap'
import type { OpenFixtureInput, ReviewSummary } from '../../../main/ipc/channels'
import { Badge, Card, EmptyState, SectionLabel } from '../../components/ui'
import { formatResult, humanizeRole } from '../../lib/humanize'

const FIXTURES: { id: OpenFixtureInput['fixtureId']; label: string }[] = [
  { id: 'NA1_fixture_a', label: 'Fixture A' },
  { id: 'NA1_fixture_b', label: 'Fixture B' },
  { id: 'NA1_fixture_c', label: 'Fixture C' }
]

export function Dashboard(): ReactElement {
  const queryClient = useQueryClient()
  const [pid, setPid] = useState(5)
  const [error, setError] = useState<string | null>(null)
  const statusQuery = useQuery({
    queryKey: ['sidecar-status'],
    queryFn: () => window.rift.getSidecarStatus()
  })
  const reviewsQuery = useQuery({
    queryKey: ['reviews'],
    queryFn: () => window.rift.listReviews(),
    enabled: statusQuery.data?.state === 'ready'
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
            <p className="mt-1.5 text-sm text-slate-500">
              Post-game coaching · local fixtures only
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <SystemStatus compact />
            <AccountMenu />
          </div>
        </header>

        <section
          className="mt-8 flex items-start gap-3 rounded-xl border border-rift-gold/25 bg-rift-gold-soft px-4 py-3 text-sm text-amber-100"
          role="note"
        >
          <svg viewBox="0 0 20 20" className="mt-0.5 h-4 w-4 shrink-0 text-rift-gold" fill="currentColor" aria-hidden="true">
            <path d="M10 2 1 18h18L10 2Zm0 5.5c.5 0 .9.4.9.9v4.2a.9.9 0 1 1-1.8 0V8.4c0-.5.4-.9.9-.9ZM10 15a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z" />
          </svg>
          <p>
            Fixture A/B/C are copies of one unpaired match+timeline dump. Match and timeline data
            aren't from the same real game — reviews still run, but identity and some metrics are
            limited.
          </p>
        </section>

        <Card className="mt-6 p-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-base font-semibold">Open a fixture review</h2>
              <p className="mt-1 text-sm text-slate-500">
                Builds the existing H.8 review in the sidecar. No Riot account or live API.
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
              // Fixture B always works: the main process falls back to a placeholder
              // review for it when the sidecar is unreachable. A/C need a real sidecar.
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
                  <span className="font-mono text-[11px] text-slate-500">
                    {fixture.id}
                    {!ready && usableOffline ? ' · placeholder (sidecar offline)' : ''}
                  </span>
                </button>
              )
            })}
          </div>
          {!ready ? (
            <p className="mt-3 flex items-center gap-1.5 text-sm text-slate-500">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-slate-500" />
              Waiting for sidecar… Fixture B still works with placeholder data.
            </p>
          ) : null}
          {error ? (
            <p className="mt-3 text-sm text-rift-danger" data-testid="review-error">
              {error}
            </p>
          ) : null}
        </Card>

        <section className="mt-10">
          <SectionLabel>Saved reviews</SectionLabel>
          {listError ? <p className="mt-2 text-sm text-rift-danger">{listError}</p> : null}
          {reviews.length === 0 && listError === null ? (
            <div className="mt-3">
              <EmptyState
                title="No saved reviews yet"
                body="Open a fixture above to generate your first coaching review."
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
      {item.fixture_warning ? (
        <span className="mt-0.5 text-[11px] text-rift-gold">Fixture data · limited accuracy</span>
      ) : null}
    </button>
  )
}
