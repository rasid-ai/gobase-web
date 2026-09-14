import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { BrowserRouter } from 'react-router-dom'

import { AuthProvider } from '@/app/auth/AuthProvider'
import { AppRoutes } from '@/app/routes'
import { startSystemTheme } from '@/app/theme'
import { ToastProvider } from '@/components/ui/toast'

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
          {/* Above the routes so any page can raise a transient failure. */}
          <ToastProvider>
            <AppRoutes />
          </ToastProvider>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
