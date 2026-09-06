import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { BrowserRouter } from 'react-router-dom'

import { AuthProvider } from '@/app/auth/AuthProvider'
import { AppRoutes } from '@/app/routes'
import { startSystemTheme } from '@/app/theme'

export function App() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: false, refetchOnWindowFocus: false },
        },
      }),
  )

  // Pre-auth pages follow the system theme; the shell toggle comes later.
  useEffect(startSystemTheme, [])

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
