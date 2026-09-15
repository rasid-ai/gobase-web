import { Moon, Sun } from 'lucide-react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from '@/app/auth/useAuth'
import { PortalWordmark } from '@/components/PortalWordmark'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { useThemeToggle } from './useThemeToggle'

/**
 * Frame for the authenticated routes: wordmark, the three pages, identity, and
 * the theme toggle that context/ui-rules.md puts inside the shell.
 */
export function AppShell() {
  const { user, signOut } = useAuth()
  const { theme, toggle } = useThemeToggle()

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <header className="flex items-center gap-6 border-b border-border px-10 py-[18px]">
        <PortalWordmark />
        <nav className="flex items-center gap-1">
          <ShellLink to="/map">Atlas</ShellLink>
          <ShellLink to="/assets">Assets</ShellLink>
          <ShellLink to="/runs">Data Governance</ShellLink>
        </nav>
        <span className="flex-1" />
        <span className="font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
          {user?.username} · {user?.role}
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={toggle}
          aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {theme === 'dark' ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
          {theme === 'dark' ? 'Light mode' : 'Dark mode'}
        </Button>
        <Button variant="outline" size="sm" onClick={signOut}>
          Sign out
        </Button>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}

function ShellLink({ to, children }: { to: string; children: string }) {
  const { pathname } = useLocation()
  // Every page owns its whole subtree, so a nested route keeps its section
  // highlighted. No path is a prefix of another (docs/adr/009), which is what
  // lets this be one rule rather than a special case for the root.
  const isActive = pathname.startsWith(to)

  return (
    <NavLink
      to={to}
      className={cn(
        'rounded-md px-3 py-1.5 text-sm',
        isActive ? 'text-primary' : 'text-muted-foreground hover:text-foreground',
      )}
    >
      {children}
    </NavLink>
  )
}
