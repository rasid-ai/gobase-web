import { Navigate, Route, Routes } from 'react-router-dom'

import { useAuth } from '@/app/auth/useAuth'
import { SignInPage } from '@/features/auth/SignInPage'
import { LandingPage } from '@/features/landing/LandingPage'
import { AppShell, RunsPlaceholder } from '@/features/shell/AppShell'
import { WorkspacePage } from '@/features/workspace/WorkspacePage'

/**
 * The route tree depends on the session, which is how `/` can be the landing
 * page for a visitor and the Map workspace for a signed-in user — both of
 * which context/ui-rules.md requires.
 *
 * Unauthenticated:  /  Landing · /signin  Sign in · everything else -> /signin
 * Authenticated:    /  Map     · /runs    Runs    · /signin        -> /
 */
export function AppRoutes() {
  const { status, sessionExpired } = useAuth()

  // Until the boot refresh resolves we know nothing, and rendering either tree
  // would flash the wrong page.
  if (status === 'checking') return <BootScreen />

  if (status === 'anon') {
    return (
      <Routes>
        {/*
          A visitor gets the landing page at the root; someone whose session
          just expired gets the login screen instead.
        */}
        <Route
          path="/"
          element={sessionExpired ? <Navigate to="/signin" replace /> : <LandingPage />}
        />
        <Route path="/signin" element={<SignInPage />} />
        <Route path="*" element={<Navigate to="/signin" replace />} />
      </Routes>
    )
  }

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<WorkspacePage />} />
        <Route path="/runs" element={<RunsPlaceholder />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

function BootScreen() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background text-muted-foreground">
      <span className="font-mono text-[11px] uppercase tracking-[0.06em]">Loading</span>
    </div>
  )
}
