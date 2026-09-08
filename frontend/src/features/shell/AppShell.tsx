import { Link, NavLink, Outlet } from 'react-router-dom'

import { useAuth } from '@/app/auth/useAuth'
import { PortalWordmark } from '@/components/PortalWordmark'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/**
 * Placeholder shell for the authenticated routes.
 *
 * The real persistent sidebar, theme toggle, and the Map/Runs screens belong
 * to their own slices (context/ui-rules.md); this exists so sign-in has
 * somewhere to land and so the route guard is exercised end to end.
 */
export function AppShell() {
  const { user, signOut } = useAuth()

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <header className="flex items-center gap-6 border-b border-border px-10 py-[18px]">
        <PortalWordmark />
        <nav className="flex items-center gap-1">
          <ShellLink to="/">Map</ShellLink>
          <ShellLink to="/runs">Runs</ShellLink>
        </nav>
        <span className="flex-1" />
        <span className="font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
          {user?.username} · {user?.role}
        </span>
        <Button variant="outline" size="sm" onClick={signOut}>
          Sign out
        </Button>
      </header>
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
    </div>
  )
}

function ShellLink({ to, children }: { to: string; children: string }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        cn(
          'rounded-md px-3 py-1.5 text-sm',
          isActive ? 'text-primary' : 'text-muted-foreground hover:text-foreground',
        )
      }
    >
      {children}
    </NavLink>
  )
}

/** Stand-in until the Runs slice lands. */
export function RunsPlaceholder() {
  return <PlaceholderScreen name="Runs" />
}

function PlaceholderScreen({ name }: { name: string }) {
  return (
    <div className="m-10 rounded-lg border border-border p-10">
      <p className="mb-2 font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
        Placeholder
      </p>
      <h1 className="text-2xl font-semibold">{name}</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        This screen arrives with its own slice. You are signed in.
      </p>
      <Link to="/" className="mt-4 inline-block text-sm text-primary hover:underline">
        Back to the workspace
      </Link>
    </div>
  )
}
