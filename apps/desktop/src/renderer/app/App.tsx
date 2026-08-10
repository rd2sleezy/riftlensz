import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement } from 'react'
import { AppRoutes } from './routes'

const queryClient = new QueryClient()

export function App(): ReactElement {
  return (
    <QueryClientProvider client={queryClient}>
      <AppRoutes />
    </QueryClientProvider>
  )
}
