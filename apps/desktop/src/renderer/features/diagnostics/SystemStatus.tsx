import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, type ReactElement } from 'react'
import { Badge } from '../../components/ui'

const STATE_VARIANT = {
  ready: 'accent',
  starting: 'neutral',
  restarting: 'gold',
  unhealthy: 'danger',
  failed: 'danger'
} as const satisfies Record<string, 'accent' | 'neutral' | 'gold' | 'danger'>

export function SystemStatus({ compact = false }: { compact?: boolean }): ReactElement {
  const queryClient = useQueryClient()
  const statusQuery = useQuery({
    queryKey: ['sidecar-status'],
    queryFn: () => window.rift.getSidecarStatus()
  })

  useEffect(() => {
    return window.rift.onSidecarStatus((next) => {
      queryClient.setQueryData(['sidecar-status'], next)
    })
  }, [queryClient])

  const healthQuery = useQuery({
    queryKey: ['sidecar-health', statusQuery.data?.state, statusQuery.data?.port],
    queryFn: () => window.rift.health(),
    enabled: statusQuery.data?.state === 'ready',
    refetchInterval: 5_000
  })

  const state = statusQuery.data?.state ?? 'starting'
  const version = healthQuery.data?.version ?? statusQuery.data?.version ?? '—'
  const port = statusQuery.data?.port ?? '—'
  const dbPath = healthQuery.data?.db_path ?? statusQuery.data?.dbPath ?? '—'
  const variant = STATE_VARIANT[state] ?? 'neutral'

  if (compact) {
    return (
      <div className="flex items-center gap-2">
        <Badge variant={variant} className="font-mono">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              state === 'ready'
                ? 'bg-rift-accent'
                : state === 'restarting'
                  ? 'animate-pulse bg-rift-gold'
                  : state === 'unhealthy' || state === 'failed'
                    ? 'bg-rift-danger'
                    : 'animate-pulse bg-slate-400'
            }`}
          />
          <span data-testid="sidecar-status">
            Sidecar: {state} · v{version} · port {port}
          </span>
        </Badge>
        <button
          type="button"
          className="rounded-md border border-rift-edge px-2.5 py-1 text-xs text-slate-400 transition hover:border-rift-accent/40 hover:text-slate-200"
          onClick={() => {
            void window.rift.restartSidecar()
          }}
        >
          Restart
        </button>
      </div>
    )
  }

  return (
    <section className="min-h-screen bg-rift-bg px-8 py-10 text-slate-100">
      <h1 className="text-2xl font-semibold tracking-tight">RiftLens</h1>
      <p data-testid="sidecar-status" className="mt-6 font-mono text-lg">
        Sidecar: {state} · v{version} · port {port}
      </p>
      <p className="mt-3 text-sm text-slate-400">DB path: {dbPath}</p>
      <button
        type="button"
        className="mt-8 rounded-md bg-rift-accent px-4 py-2 text-sm font-medium text-rift-bg hover:bg-rift-accent-strong"
        onClick={() => {
          void window.rift.restartSidecar()
        }}
      >
        Restart sidecar
      </button>
    </section>
  )
}
