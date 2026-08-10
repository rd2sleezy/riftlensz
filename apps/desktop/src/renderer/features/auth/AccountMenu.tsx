import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type ReactElement } from 'react'
import { Badge } from '../../components/ui'

export function AccountMenu(): ReactElement {
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)

  const sessionQuery = useQuery({
    queryKey: ['auth-session'],
    queryFn: () => window.rift.getAuthSession()
  })

  useEffect(() => {
    return window.rift.onAuthSession((session) => {
      queryClient.setQueryData(['auth-session'], session)
    })
  }, [queryClient])

  const signIn = useMutation({
    mutationFn: () => window.rift.signIn(),
    onSuccess: (result) => {
      if (!result.ok) {
        setError(result.message)
        return
      }
      setError(null)
      queryClient.setQueryData(['auth-session'], result.session)
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : 'Sign-in failed')
    }
  })

  const signOut = useMutation({
    mutationFn: () => window.rift.signOut(),
    onSuccess: (session) => {
      setError(null)
      queryClient.setQueryData(['auth-session'], session)
    }
  })

  const session = sessionQuery.data

  if (session?.signedIn) {
    return (
      <div className="flex items-center gap-2">
        <Badge variant="accent">
          {session.gameName ?? 'Signed in'}
          {session.tagLine ? <span className="text-slate-400">#{session.tagLine}</span> : null}
        </Badge>
        <button
          type="button"
          className="rounded-md border border-rift-edge px-2.5 py-1 text-xs text-slate-400 transition hover:border-rift-danger/40 hover:text-slate-200"
          onClick={() => signOut.mutate()}
        >
          Sign out
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        disabled={signIn.isPending}
        className="flex items-center gap-1.5 rounded-md bg-rift-accent px-3 py-1.5 text-xs font-medium text-rift-bg transition hover:bg-rift-accent-strong disabled:cursor-wait disabled:opacity-60"
        onClick={() => {
          setError(null)
          signIn.mutate()
        }}
      >
        {signIn.isPending ? 'Waiting for Riot…' : 'Sign in with Riot Games'}
      </button>
      {error ? <p className="max-w-xs text-right text-[11px] text-rift-danger">{error}</p> : null}
    </div>
  )
}
