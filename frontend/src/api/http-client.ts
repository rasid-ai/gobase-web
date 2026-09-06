/**
 * The Orval mutator: every generated hook and function goes through here.
 *
 * It attaches the in-memory access token, and on a 401 renews the session
 * once from the refresh cookie and retries the original request — which is
 * what makes HLR-003 invisible to the user. If renewal fails, the session is
 * over and listeners are told (HLR-004).
 *
 * Orval's fetch client expects `(url, init)` and a `{ data, status, headers }`
 * result, discriminated on status. Non-2xx is returned, not thrown; callers
 * branch on `status`.
 */

import { getAccessToken, notifySessionEnded, setAccessToken } from './token-store'

export const REFRESH_PATH = '/api/auth/refresh'
export const LOGIN_PATH = '/api/auth/login'

/**
 * A single in-flight refresh shared by every concurrent 401. Without this, a
 * page firing several queries at once would spend its one-use rotating
 * refresh cookie several times over and sign itself out.
 */
let inFlightRefresh: Promise<string | null> | null = null

export async function refreshSession(): Promise<string | null> {
  inFlightRefresh ??= (async () => {
    try {
      const response = await fetch(REFRESH_PATH, { method: 'POST', credentials: 'same-origin' })
      if (!response.ok) return null
      const body = (await response.json()) as { access?: string }
      if (!body?.access) return null
      setAccessToken(body.access)
      return body.access
    } catch {
      return null
    } finally {
      // Cleared a microtask after resolution so every concurrent caller
      // observes the same promise.
      queueMicrotask(() => {
        inFlightRefresh = null
      })
    }
  })()
  return inFlightRefresh
}

function withAuth(init: RequestInit, token: string | null): RequestInit {
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  return { ...init, credentials: 'same-origin', headers }
}

export async function httpClient<T>(url: string, init: RequestInit): Promise<T> {
  let response = await fetch(url, withAuth(init, getAccessToken()))

  // Renew once, then retry. Login and refresh are excluded: a 401 there is
  // the real answer, not a stale-token symptom.
  const renewable = url !== REFRESH_PATH && url !== LOGIN_PATH
  if (response.status === 401 && renewable) {
    const renewed = await refreshSession()
    if (renewed) {
      response = await fetch(url, withAuth(init, renewed))
    } else {
      notifySessionEnded()
    }
  }

  const data = response.status === 204 ? undefined : await response.json().catch(() => undefined)

  return { data, status: response.status, headers: response.headers } as T
}

export default httpClient
