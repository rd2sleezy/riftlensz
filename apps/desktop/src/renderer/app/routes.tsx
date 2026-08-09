import { useEffect, useState, type ReactElement } from 'react'
import { Dashboard } from '../features/home/Dashboard'
import { ReviewScreen } from '../features/review/ReviewScreen'

export function AppRoutes(): ReactElement {
  const hash = useHash()
  const reviewMatch = /^#\/review\/([^/]+)$/.exec(hash)
  if (reviewMatch?.[1]) {
    return <ReviewScreen reviewId={decodeURIComponent(reviewMatch[1])} />
  }
  return <Dashboard />
}

function useHash(): string {
  const [hash, setHash] = useState(() => window.location.hash || '#/')
  useEffect(() => {
    const onChange = (): void => setHash(window.location.hash || '#/')
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return hash
}
