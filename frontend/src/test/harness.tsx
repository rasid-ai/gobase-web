import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import { AuthProvider } from '@/app/auth/AuthProvider'
import { AppRoutes } from '@/app/routes'
import { setAccessToken } from '@/api/token-store'
import { ToastProvider } from '@/components/ui/toast'

/** `body` answers `response.json()`; `blob` answers `response.blob()`, for a file. */
export type Route = { status: number; body?: unknown; blob?: Blob }

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
      blob: async () => route.blob ?? new Blob([]),
    } as unknown as Response
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock }
}

export function resetSession() {
  setAccessToken(null)
}

/**
 * A new tab the page can point somewhere, and an object URL to point it at —
 * what opening a PDF needs (features/catalog/openDocument.ts). Undo with
 * `forgetTab()` and `vi.restoreAllMocks()`.
 */
export function fakeTab() {
  const tab = { location: { href: '' }, close: vi.fn() }
  vi.spyOn(window, 'open').mockReturnValue(tab as unknown as Window)
  // jsdom has no object URLs at all.
  Object.defineProperty(URL, 'createObjectURL', {
    value: vi.fn(() => 'blob:pdf'),
    configurable: true,
    writable: true,
  })
  return tab
}

export function forgetTab() {
  delete (URL as { createObjectURL?: unknown }).createObjectURL
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
        {/* Matches App.tsx, so a test can assert what a failure shows. */}
        <AuthProvider>
          <ToastProvider>{children}</ToastProvider>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  )
}
