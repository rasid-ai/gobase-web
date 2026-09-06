import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import { AuthProvider } from '@/app/auth/AuthProvider'
import { AppRoutes } from '@/app/routes'
import { setAccessToken } from '@/api/token-store'

export type Route = { status: number; body?: unknown }

/**
 * A tiny fetch double keyed by "METHOD /path". Every test states exactly the
 * network it expects, so an unlisted call is a visible failure rather than a
 * silent undefined.
 */
export function mockFetch(routes: Record<string, Route>) {
  const calls: string[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    const key = `${(init?.method ?? 'GET').toUpperCase()} ${url}`
    calls.push(key)
    const route = routes[key]
    if (!route) throw new Error(`Unexpected request: ${key}`)
    return {
      ok: route.status >= 200 && route.status < 300,
      status: route.status,
      headers: new Headers(),
      json: async () => route.body,
    } as unknown as Response
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock }
}

export function resetSession() {
  setAccessToken(null)
}

export function renderApp(initialPath = '/') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <Wrapper queryClient={queryClient} initialPath={initialPath}>
      <AppRoutes />
    </Wrapper>,
  )
}

function Wrapper({
  queryClient,
  initialPath,
  children,
}: {
  queryClient: QueryClient
  initialPath: string
  children: ReactNode
}) {
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <AuthProvider>{children}</AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  )
}
