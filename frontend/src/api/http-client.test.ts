/**
 * The 401 interceptor: the mechanism behind HLR-003 and HLR-004.
 */

import { afterEach, describe, expect, it, vi } from 'vitest'

import { httpClient, refreshSession } from './http-client'
import { getAccessToken, onSessionEnded, setAccessToken } from './token-store'

type Reply = { status: number; body?: unknown }

function stubFetch(replies: Record<string, Reply[]>) {
  const calls: string[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    calls.push(url)
    const queue = replies[url]
    if (!queue?.length) throw new Error(`Unexpected request: ${url}`)
    const reply = queue.length === 1 ? queue[0] : queue.shift()!
    return {
      ok: reply.status >= 200 && reply.status < 300,
      status: reply.status,
      headers: new Headers(),
      json: async () => reply.body,
    } as unknown as Response
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
  setAccessToken(null)
})

describe('HLR-003 — the session renews transparently', () => {
  it('renews on a 401 and retries the original request', async () => {
    setAccessToken('stale')
    const { calls } = stubFetch({
      '/api/auth/me': [
        { status: 401, body: { detail: 'expired' } },
        { status: 200, body: { username: 'viewer1', role: 'viewer' } },
      ],
      '/api/auth/refresh': [{ status: 200, body: { access: 'fresh' } }],
    })

    const result = await httpClient<{ data: unknown; status: number }>('/api/auth/me', {
      method: 'GET',
    })

    expect(result.status).toBe(200)
    expect(result.data).toEqual({ username: 'viewer1', role: 'viewer' })
    expect(calls).toEqual(['/api/auth/me', '/api/auth/refresh', '/api/auth/me'])
    expect(getAccessToken()).toBe('fresh')
  })

  it('sends the renewed token on the retry', async () => {
    setAccessToken('stale')
    const { fetchMock } = stubFetch({
      '/api/auth/me': [{ status: 401 }, { status: 200, body: {} }],
      '/api/auth/refresh': [{ status: 200, body: { access: 'fresh' } }],
    })

    await httpClient('/api/auth/me', { method: 'GET' })

    const retry = fetchMock.mock.calls.at(-1)![1] as RequestInit
    expect(new Headers(retry.headers).get('Authorization')).toBe('Bearer fresh')
  })

  it('spends the one-use refresh cookie once for concurrent 401s', async () => {
    // Without single-flight, parallel queries would each rotate the cookie and
    // invalidate one another — the session would end mid-page.
    setAccessToken('stale')
    const { calls } = stubFetch({
      '/api/auth/me': [{ status: 401 }, { status: 200, body: {} }],
      '/api/auth/runs': [{ status: 401 }, { status: 200, body: {} }],
      '/api/auth/refresh': [{ status: 200, body: { access: 'fresh' } }],
    })

    await Promise.all([
      httpClient('/api/auth/me', { method: 'GET' }),
      httpClient('/api/auth/runs', { method: 'GET' }),
    ])

    expect(calls.filter((c) => c === '/api/auth/refresh')).toHaveLength(1)
  })
})

describe('HLR-004 — an unrenewable session ends', () => {
  it('signals session end when renewal fails, and does not retry', async () => {
    setAccessToken('stale')
    const ended = vi.fn()
    const unsubscribe = onSessionEnded(ended)
    const { calls } = stubFetch({
      '/api/auth/me': [{ status: 401 }],
      '/api/auth/refresh': [{ status: 401, body: { detail: 'Session expired.' } }],
    })

    const result = await httpClient<{ status: number }>('/api/auth/me', { method: 'GET' })

    expect(result.status).toBe(401)
    expect(ended).toHaveBeenCalledOnce()
    expect(getAccessToken()).toBeNull()
    expect(calls).toEqual(['/api/auth/me', '/api/auth/refresh'])
    unsubscribe()
  })

  it('does not try to renew a failed login', async () => {
    const { calls } = stubFetch({ '/api/auth/login': [{ status: 400 }] })

    const result = await httpClient<{ status: number }>('/api/auth/login', { method: 'POST' })

    expect(result.status).toBe(400)
    expect(calls).toEqual(['/api/auth/login'])
  })
})

describe('refreshSession', () => {
  it('returns null and keeps no token when the cookie is gone', async () => {
    stubFetch({ '/api/auth/refresh': [{ status: 401 }] })
    await expect(refreshSession()).resolves.toBeNull()
    expect(getAccessToken()).toBeNull()
  })
})
