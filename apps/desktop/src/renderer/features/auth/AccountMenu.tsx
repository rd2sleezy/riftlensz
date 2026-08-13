import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type ReactElement } from 'react'
import { Badge, Disclosure, RiotIcon, RiotMark } from '../../components/ui'
import type { SignInResult, SignInWithApiKeyInput } from '../../../main/ipc/channels'

const REGIONS: SignInWithApiKeyInput['region'][] = ['americas', 'europe', 'asia']

const REGION_LABELS: Record<SignInWithApiKeyInput['region'], string> = {
  americas: 'Americas (NA, BR, LAN, LAS, OCE)',
  europe: 'Europe (EUW, EUNE, TR, RU)',
  asia: 'Asia (KR, JP)'
}

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
        className="flex items-center gap-2 rounded-md bg-rift-accent px-3 py-1.5 text-xs font-medium text-rift-bg transition hover:bg-rift-accent-strong"
        onClick={() => setOpen((value) => !value)}
      >
        <RiotIcon />
        Sign in with Riot
      </button>

      {open ? (
        <div className="absolute right-0 top-full z-10 mt-2 w-96 rounded-xl border border-rift-border bg-rift-surface p-4 shadow-card">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Sign in with your Riot ID
            </p>
            <RiotMark />
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
            Connect your real Riot account to pull match history automatically. Takes about a minute.
          </p>

          <form
            className="mt-3 space-y-2"
            onSubmit={(event) => {
              event.preventDefault()
              if (isPending) {
                return
              }
              const [gameName, tagLine] = riotId.split('#').map((part) => part.trim())
              if (!gameName || !tagLine) {
                setError('Enter your Riot ID as Name#Tag.')
                return
              }
              setError(null)
              signInApiKey.mutate({ apiKey, gameName, tagLine, region })
            }}
          >
            <div>
              <input
                value={riotId}
                onChange={(event) => setRiotId(event.target.value)}
                placeholder="Riot ID (Name#Tag)"
                disabled={isPending}
                className="w-full rounded-md border border-rift-edge bg-rift-raised px-2.5 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-rift-accent/50 disabled:opacity-50"
              />
              <p className="mt-1 text-[10px] text-slate-600">Found in-client under your profile, top right</p>
            </div>

            <div>
              <div className="flex items-center justify-between">
                <label className="text-[11px] font-medium text-slate-400">Riot API key</label>
                <a
                  href="https://developer.riotgames.com/"
                  target="_blank"
                  rel="noreferrer"
                  className="text-[11px] font-medium text-rift-accent-strong hover:underline"
                >
                  Get a key →
                </a>
              </div>
              <input
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                type="password"
                placeholder="Personal API key"
                disabled={isPending}
                autoComplete="off"
                className="mt-1 w-full rounded-md border border-rift-edge bg-rift-raised px-2.5 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-rift-accent/50 disabled:opacity-50"
              />
              <p className="mt-1 text-[10px] text-slate-600">Starts with RGAPI- · expires roughly every 24h</p>
              {apiKey.length > 0 && !apiKey.trim().startsWith('RGAPI-') ? (
                <p className="mt-1 text-[10px] text-rift-gold">
                  Personal keys normally start with &quot;RGAPI-&quot; — double check you copied the whole key.
                </p>
              ) : null}
            </div>

            <select
              value={region}
              onChange={(event) => setRegion(event.target.value as SignInWithApiKeyInput['region'])}
              disabled={isPending}
              className="w-full rounded-md border border-rift-edge bg-rift-raised px-2 py-1.5 text-sm text-slate-100 focus:border-rift-accent/50 disabled:opacity-50"
            >
              {REGIONS.map((value) => (
                <option key={value} value={value}>
                  {REGION_LABELS[value]}
                </option>
              ))}
            </select>

            <button
              type="submit"
              disabled={isPending || !riotId || !apiKey}
              className="w-full rounded-md bg-rift-accent px-3 py-1.5 text-xs font-medium text-rift-bg transition hover:bg-rift-accent-strong disabled:cursor-not-allowed disabled:opacity-40"
            >
              {signInApiKey.isPending ? 'Verifying…' : 'Verify & sign in'}
            </button>
          </form>

          <div className="mt-3 border-t border-rift-border pt-3">
            <Disclosure summary="Advanced: full Riot sign-on">
              <p className="mb-2 text-[11px] leading-relaxed text-slate-500">
                Uses Riot&apos;s official account login flow instead of a personal API key. Requires an
                approved Riot developer app, which this build doesn&apos;t have yet.
              </p>
              <button
                type="button"
                disabled={isPending}
                className="w-full rounded-md border border-rift-edge px-3 py-1.5 text-xs text-slate-300 transition hover:border-rift-accent/40 disabled:cursor-not-allowed disabled:opacity-50"
                onClick={() => {
                  setError(null)
                  signInRso.mutate()
                }}
              >
                {signInRso.isPending ? 'Waiting for Riot…' : 'Sign in with Riot account'}
              </button>
            </Disclosure>
          </div>

          {error ? <p className="mt-2 text-[11px] text-rift-danger">{error}</p> : null}
        </div>
      ) : null}
    </div>
  )
}
