import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useEffect, useState, type ReactElement } from 'react'
import { AppRoutes } from './routes'
import { SplashScreen } from './SplashScreen'

const queryClient = new QueryClient()

const SPLASH_HOLD_MS = 1000
const SPLASH_FADE_MS = 420

export function App(): ReactElement {
  const [splashVisible, setSplashVisible] = useState(true)
  const [splashFading, setSplashFading] = useState(false)

  useEffect(() => {
    const fadeTimer = setTimeout(() => setSplashFading(true), SPLASH_HOLD_MS)
    const hideTimer = setTimeout(() => setSplashVisible(false), SPLASH_HOLD_MS + SPLASH_FADE_MS)
    return () => {
      clearTimeout(fadeTimer)
      clearTimeout(hideTimer)
    }
  }, [])

  return (
    <QueryClientProvider client={queryClient}>
      <AppRoutes />
      {splashVisible ? <SplashScreen fading={splashFading} /> : null}
    </QueryClientProvider>
  )
}
