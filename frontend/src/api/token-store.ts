/**
 * The access token lives here and nowhere else — module memory only.
 *
 * Never localStorage, never sessionStorage, never a readable cookie. A page
 * reload is meant to lose it; the httpOnly refresh cookie is what restores
 * the session.
 */

let accessToken: string | null = null

type Listener = () => void
const sessionEndedListeners = new Set<Listener>()

export function getAccessToken(): string | null {
  return accessToken
}

export function setAccessToken(token: string | null): void {
  accessToken = token
}

/** Called when the session can no longer be renewed. */
export function onSessionEnded(listener: Listener): () => void {
  sessionEndedListeners.add(listener)
  return () => sessionEndedListeners.delete(listener)
}

export function notifySessionEnded(): void {
  accessToken = null
  sessionEndedListeners.forEach((listener) => listener())
}
