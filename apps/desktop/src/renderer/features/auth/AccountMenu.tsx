import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type ReactElement } from 'react'
import { Badge } from '../../components/ui'
import type { SignInResult, SignInWithApiKeyInput } from '../../../main/ipc/channels'

const REGIONS: SignInWithApiKeyInput['region'][] = ['americas', 'europe', 'asia']

export function AccountMenu(): ReactElement {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [riotId, setRiotId] = useState('')
  const [region, setRegion] = useState<SignInWithApiKeyInput['region']>('americas')
  const [apiKey, setApiKey] = useState('')
  const panelRef = useRef<HTMLDivElement>(null)

  const sessionQuery = useQuery({
    queryKey: ['auth-session'],
    queryFn: () => window.rift.getAuthSession()
  })

  useEffect(() => {
    return window.rift.onAuthSession((session) => {
      queryClient.setQueryData(['auth-session'], session)
    })
  }, [queryClient])

  useEffect(() => {
    if (!open) return
    const onClick = (event: MouseEvent): void => {
      if (panelRef.current && !panelRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open])

  const applySession = (result: SignInResult): void => {
    if (!result.ok) {
      setError(result.message)
      return
    }
    setError(null)
    setOpen(false)
    queryClient.setQueryData(['auth-session'], result.session)
  }

  const signInApiKey = useMutation({
    mutationFn: (input: SignInWithApiKeyInput) => window.rift.signInWithApiKey(input),
    onSuccess: applySession,
    onError: (err: unknown) => setError(err instanceof Error ? err.message : 'Sign-in failed')
  })

  const signInRso = useMutation({
    mutationFn: () => window.rift.signIn(),
    onSuccess: applySession,
    onError: (err: unknown) => setError(err instanceof Error ? err.message : 'Sign-in failed')
  })

  const signOut = useMutation({
    mutationFn: () => window.rift.signOut(),
    onSuccess: (session) => {
      setError(null)
      queryClient.setQueryData(['auth-session'], session)
    }
  })

  const session = sessionQuery.data
  const isPending = signInApiKey.isPending || signInRso.isPending

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
    <div className="relative" ref={panelRef}>
      <button
        type="button"
        className="flex items-center gap-1.5 rounded-md bg-rift-accent px-3 py-1.5 text-xs font-medium text-rift-bg transition hover:bg-rift-accent-strong"
        onClick={() => setOpen((value) => !value)}
      >
        Sign in with Riot
      </button>

      {open ? (
        <div className="absolute right-0 top-full z-10 mt-2 w-80 rounded-xl border border-rift-border bg-rift-surface p-4 shadow-card">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Sign in with your Riot ID
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
            Verifies your account against Riot&apos;s real API using a personal developer key —{' '}
            <a
              href="https://developer.riotgames.com/"
              target="_blank"
              rel="noreferrer"
              className="text-rift-accent-strong hover:underline"
            >
              get an instant one here
            </a>
            . Personal keys expire roughly every 24h.
          </p>

          <form
            className="mt-3 space-y-2"
            onSubmit={(event) => {
              event.preventDefault()
              const [gameName, tagLine] = riotId.split('#').map((part) => part.trim())
              if (!gameName || !tagLine) {
                setError('Enter your Riot ID as Name#Tag.')
                return
              }
              setError(null)
              signInApiKey.mutate({ apiKey, gameName, tagLine, region })
            }}
          >
            <input
              value={riotId}
              onChange={(event) => setRiotId(event.target.value)}
              placeholder="Riot ID (Name#Tag)"
              className="w-full rounded-md border border-rift-edge bg-rift-raised px-2.5 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-rift-accent/50"
            />
            <div className="flex gap-2">
              <select
                value={region}
                onChange={(event) => setRegion(event.target.value as SignInWithApiKeyInput['region'])}
                className="rounded-md border border-rift-edge bg-rift-raised px-2 py-1.5 text-sm text-slate-100 focus:border-rift-accent/50"
              >
                {REGIONS.map((value) => (
                  <option key={value} value={value}>
                    {value[0]?.toUpperCase()}
                    {value.slice(1)}
                  </option>
                ))}
              </select>
              <input
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                type="password"
                placeholder="Personal API key"
                className="flex-1 rounded-md border border-rift-edge bg-rift-raised px-2.5 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-rift-accent/50"
              />
            </div>
            <button
              type="submit"
              disabled={isPending || !riotId || !apiKey}
              className="w-full rounded-md bg-rift-accent px-3 py-1.5 text-xs font-medium text-rift-bg transition hover:bg-rift-accent-strong disabled:cursor-not-allowed disabled:opacity-40"
            >
              {signInApiKey.isPending ? 'Verifying…' : 'Verify & sign in'}
            </button>
          </form>

          <button
            type="button"
            disabled={isPending}
            className="mt-3 w-full text-center text-[11px] text-slate-500 hover:text-slate-300 disabled:cursor-not-allowed"
            onClick={() => {
              setError(null)
              signInRso.mutate()
            }}
          >
            {signInRso.isPending ? 'Waiting for Riot…' : 'Or use full Riot sign-on (needs an approved app)'}
          </button>

          {error ? <p className="mt-2 text-[11px] text-rift-danger">{error}</p> : null}
        </div>
      ) : null}
    </div>
  )
}
