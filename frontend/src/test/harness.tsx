import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import { AuthProvider } from '@/app/auth/AuthProvider'
import { AppRoutes } from '@/app/routes'
import { setAccessToken } from '@/api/token-store'
import { ToastProvider } from '@/components/ui/toast'

/**
 * `body` answers `response.json()`; `blob` answers `response.blob()`, for a
 * file; `stream` is `response.body`, for server-sent events — a list of
 * chunks sent at once, or a function that builds the stream so a test can
 * send more later (`openStream`).
 */
export type Route = {
  status: number
  body?: unknown
  blob?: Blob
  stream?: string[] | (() => ReadableStream<Uint8Array>)
}

/**
 * A stream the test writes to: `send` a chunk, `end` it.
 *
 * Like a real response body, it fails with an AbortError when the request's
 * signal aborts — which is how a stopped answer ends.
 */
export function openStream() {
  const encoder = new TextEncoder()
  let controller!: ReadableStreamDefaultController<Uint8Array>
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c
    },
  })
  return {
    stream: () => stream,
    send: (chunk: string) => controller.enqueue(encoder.encode(chunk)),
    end: () => controller.close(),
    fail: (error: unknown) => controller.error(error),
  }
}

function bodyOf(route: Route, signal: AbortSignal | null | undefined) {
  if (!route.stream) return null
  let stream: ReadableStream<Uint8Array>
  if (typeof route.stream === 'function') {
    stream = route.stream()
  } else {
    const chunks = route.stream.map((chunk) => new TextEncoder().encode(chunk))
    stream = new ReadableStream({
      start(controller) {
        chunks.forEach((chunk) => controller.enqueue(chunk))
        controller.close()
      },
    })
  }
  // Pass reads through, and fail them on abort as a browser does.
  const reader = stream.getReader()
  return new ReadableStream<Uint8Array>({
    start(controller) {
      signal?.addEventListener('abort', () => {
        controller.error(new DOMException('The request was aborted', 'AbortError'))
        void reader.cancel().catch(() => {})
      })
    },
    async pull(controller) {
      try {
        const { value, done } = await reader.read()
        if (done) controller.close()
        else controller.enqueue(value)
      } catch {
        // Already failed by the abort above.
      }
    },
    cancel() {
      void reader.cancel().catch(() => {})
    },
  })
}

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
      body: bodyOf(route, init?.signal),
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
