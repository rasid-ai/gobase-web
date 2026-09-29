import { Navigate, Route, Routes } from 'react-router-dom'

import { useAuth } from '@/app/auth/useAuth'
import { SignInPage } from '@/features/auth/SignInPage'
import { AssetsPage } from '@/features/catalog/AssetsPage'
import { LandingPage } from '@/features/landing/LandingPage'
import { RunsPage } from '@/features/runs/RunsPage'
import { AppShell } from '@/features/shell/AppShell'
import { WorkspacePage } from '@/features/workspace/WorkspacePage'

/**
 * One path, one page — for everyone (docs/adr/009).
 *
 * The tree still depends on the session, because `/` is the landing page for a
 * visitor and has nothing to show a signed-in user. But no path below it means
 * two different things any more, so a workspace link can be shared and the
 * destination of an exit never depends on where you happened to be.
 *
 * Unauthenticated:  /  Landing · /signin  Sign in · everything else -> /signin
 * Authenticated:    /  -> /map · /map  Atlas · /assets  Assets
 *                   /runs  Data Governance · everything else -> /map
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
        <Route path="/map" element={<WorkspacePage />} />
        <Route path="/assets" element={<AssetsPage />} />
        <Route path="/runs" element={<RunsPage />} />
      </Route>
      {/* The root has no meaning once you are signed in; the map is home. */}
      <Route path="*" element={<Navigate to="/map" replace />} />
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
