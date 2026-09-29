import { createContext, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { authMeRetrieve } from '@/api/generated/auth/auth'
import type { Me } from '@/api/generated/model'
import { refreshSession } from '@/api/http-client'
import { notifySessionEnded, onSessionEnded, setAccessToken } from '@/api/token-store'

export type AuthStatus = 'checking' | 'authed' | 'anon'

export type AuthContextValue = {
  status: AuthStatus
  user: Me | null
  /**
   * True when the session ended on its own rather than by the user asking.
   * That case has to land on the login screen, which is a
   * different destination from a deliberate sign-out.
   */
  sessionExpired: boolean
  /** Adopt the access token returned by a successful sign-in. */
  signIn: (accessToken: string) => Promise<void>
  signOut: () => void
}

// eslint-disable-next-line react-refresh/only-export-components
export const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('checking')
  const [user, setUser] = useState<Me | null>(null)
  const [sessionExpired, setSessionExpired] = useState(false)
  const queryClient = useQueryClient()

  const loadUser = useCallback(async () => {
    const response = await authMeRetrieve()
    if (response.status !== 200) throw new Error('Not signed in')
    setUser(response.data)
    setStatus('authed')
  }, [])

  const signIn = useCallback(
    async (accessToken: string) => {
      setAccessToken(accessToken)
      setSessionExpired(false)
      await loadUser()
    },
    [loadUser],
  )

  const endSession = useCallback(
    (expired: boolean) => {
      setAccessToken(null)
      setUser(null)
      setStatus('anon')
      setSessionExpired(expired)
      // Nothing cached may outlive the session — "no partial data renders".
      queryClient.clear()
    },
    [queryClient],
  )

  const signOut = useCallback(() => endSession(false), [endSession])

  // The session can end at any moment the refresh cookie stops working
  // The http client raises it; the tree hears about it here.
  useEffect(() => onSessionEnded(() => endSession(true)), [endSession])

  // On boot the in-memory access token is always empty — a reload is meant to
  // lose it. The refresh cookie is what proves the session.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      const token = await refreshSession()
      if (cancelled) return
      if (!token) {
        setStatus('anon')
        return
      }
      try {
        await loadUser()
      } catch {
        if (!cancelled) notifySessionEnded()
      }
    })()
    return () => {
      cancelled = true
    }
  }, [loadUser])

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, sessionExpired, signIn, signOut }),
    [status, user, sessionExpired, signIn, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
