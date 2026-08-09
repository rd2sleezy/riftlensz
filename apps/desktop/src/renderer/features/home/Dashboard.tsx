import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactElement } from 'react'
import { SystemStatus } from '../diagnostics/SystemStatus'
import { formatMmss } from '../../../main/sync/syncMap'
import type { OpenFixtureInput } from '../../../main/ipc/channels'

const FIXTURES: OpenFixtureInput['fixtureId'][] = [
  'NA1_fixture_a',
  'NA1_fixture_b',
  'NA1_fixture_c'
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
    <main className="min-h-screen bg-slate-950 px-8 py-8 text-slate-100">
      <div className="flex items-start justify-between gap-8">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">RiftLens</h1>
          <p className="mt-1 text-sm text-slate-400">H.8 coaching reviews · local fixtures only</p>
        </div>
        <SystemStatus compact />
      </div>

      <section className="mt-8 rounded-lg border border-amber-700/60 bg-amber-950/40 p-4 text-sm text-amber-100">
        Fixture A/B/C are copies of one unpaired match+timeline dump. match.json and timeline.json
        are not the same real game. Reviews still run, but identity and some metrics are limited.
      </section>

      <section className="mt-8">
        <h2 className="text-lg font-medium">Open a fixture review</h2>
        <p className="mt-1 text-sm text-slate-400">
          Builds the existing H.8 review in the sidecar. No Riot account or live API.
        </p>
        <label className="mt-4 flex items-center gap-2 text-sm">
          Participant id
          <input
            type="number"
            min={1}
            max={10}
            value={pid}
            className="w-16 rounded border border-slate-700 bg-slate-900 px-2 py-1"
            onChange={(event) => setPid(Number(event.target.value) || 5)}
          />
        </label>
        <div className="mt-4 flex flex-wrap gap-3">
          {FIXTURES.map((fixtureId) => (
            <button
              key={fixtureId}
              type="button"
              data-testid={fixtureId === 'NA1_fixture_b' ? 'open-fixture-b' : undefined}
              disabled={!ready || openFixture.isPending}
              className="rounded-md bg-sky-600 px-4 py-2 text-sm font-medium hover:bg-sky-500 disabled:opacity-50"
              onClick={() => {
                setError(null)
                openFixture.mutate(fixtureId)
              }}
            >
              {openFixture.isPending ? 'Analyzing…' : fixtureId}
            </button>
          ))}
        </div>
        {openFixture.isPending ? (
          <p className="mt-3 text-sm text-slate-300">Running H.8 review in the sidecar…</p>
        ) : null}
        {error ? (
          <p className="mt-3 text-sm text-rose-400" data-testid="review-error">
            {error}
          </p>
        ) : null}
        {!ready ? <p className="mt-3 text-sm text-slate-400">Waiting for sidecar…</p> : null}
      </section>

      <section className="mt-10">
        <h2 className="text-lg font-medium">Saved reviews</h2>
        {listError ? <p className="mt-2 text-sm text-rose-400">{listError}</p> : null}
        {reviews.length === 0 ? (
          <p className="mt-2 text-sm text-slate-400">No saved reviews yet.</p>
        ) : (
          <ul className="mt-3 divide-y divide-slate-800 rounded-lg border border-slate-800">
            {reviews.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-slate-900"
                  onClick={() => {
                    window.location.hash = `#/review/${item.id}`
                  }}
                >
                  <span>
                    {item.champion} {item.role} · {item.result ?? '—'} · pid {item.participant_id}
                    <span className="ml-2 text-xs text-slate-500">{item.match_id}</span>
                  </span>
                  <span className="text-xs text-slate-400">
                    {formatMmss(item.duration_ms)} · {item.focus_count} focus
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  )
}
