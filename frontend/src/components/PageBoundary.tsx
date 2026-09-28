import { Component, type ErrorInfo, type ReactNode } from 'react'

import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'

/**
 * Catches an error thrown while a page renders, and says so.
 *
 * Without it React unmounts the whole app on a render error — header and
 * navigation included — and the screen goes blank until a reload. The shell
 * keys one by path, so going to another page starts a fresh one and the rest
 * of the app keeps working.
 */
export class PageBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // The console is where a developer looks; the page only says what broke.
    console.error(error, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="px-8 py-7">
        <Alert className="flex flex-wrap items-center justify-between gap-3">
          <span className="flex min-w-0 flex-col gap-1">
            <span>This page could not be shown.</span>
            <span className="break-words font-mono text-[11px] text-muted-foreground">
              {error.message}
            </span>
          </span>
          <Button variant="outline" size="sm" onClick={() => window.location.reload()}>
            Reload
          </Button>
        </Alert>
      </div>
    )
  }
}
