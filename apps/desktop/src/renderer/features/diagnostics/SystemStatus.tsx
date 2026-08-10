import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, type ReactElement } from 'react'

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

  return (
    <section className={compact ? '' : 'min-h-screen bg-slate-950 px-8 py-10 text-slate-100'}>
      {!compact ? <h1 className="text-2xl font-semibold tracking-tight">RiftLens</h1> : null}
      <p data-testid="sidecar-status" className={compact ? 'font-mono text-sm' : 'mt-6 font-mono text-lg'}>
        Sidecar: {state} · v{version} · port {port}
      </p>
      <p className={compact ? 'mt-1 text-xs text-slate-400' : 'mt-3 text-sm text-slate-400'}>
        DB path: {dbPath}
      </p>
      <button
        type="button"
        className={
          compact
            ? 'mt-2 rounded-md bg-sky-600 px-3 py-1 text-xs font-medium hover:bg-sky-500'
            : 'mt-8 rounded-md bg-sky-600 px-4 py-2 text-sm font-medium hover:bg-sky-500'
        }
        onClick={() => {
          void window.rift.restartSidecar()
        }}
      >
        Restart sidecar
      </button>
    </section>
  )
}
