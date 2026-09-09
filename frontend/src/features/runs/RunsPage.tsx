import { useEffect, useState } from 'react'

import { RoleEnum } from '@/api/generated/model'
import { useRunsList } from '@/api/generated/runs/runs'
import { useAuth } from '@/app/auth/useAuth'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

import { RunRow } from './RunRow'
import { TriggerRunButton, type TriggerOutcome } from './TriggerRunButton'
import { formatSince } from './formatRun'
import { isRunActive } from './runStatus'

const PAGE_SIZE = 25

/**
 * Pipeline runs, newest first.
 *
 * Refresh is manual. The pipeline runs weekly and its schedule ships stopped,
 * so the list is usually one or two rows that do not change while anyone is
 * looking at them; polling would spend requests to tell the user nothing.
 */
export function RunsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === RoleEnum.admin
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<TriggerOutcome | null>(null)

  const runs = useRunsList({ limit: PAGE_SIZE })
  const page = runs.data?.status === 200 ? runs.data.data : null
  const results = page?.results ?? []
  const anyActive = results.some((run) => isRunActive(run.status))

  // Offering to launch is only honest once the list has answered: before that
  // an in-flight run is unknown, and if Dagster did not answer at all then the
  // launch cannot work either.
  const canTrigger = runs.data?.status === 200 && !anyActive

  return (
    <div className="mx-auto max-w-6xl px-10 py-10">
      <header className="flex flex-wrap items-start gap-4">
        <div className="flex-1">
          <h1 className="text-2xl font-semibold tracking-tight">Runs</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Ingestion pipeline health. Manual refresh only.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {runs.dataUpdatedAt > 0 && <LastUpdated at={runs.dataUpdatedAt} />}
          <Button
            variant="outline"
            size="sm"
            onClick={() => void runs.refetch()}
            disabled={runs.isFetching}
          >
            {runs.isFetching ? 'Refreshing…' : 'Refresh'}
          </Button>
          {isAdmin && <TriggerRunButton disabled={!canTrigger} onOutcome={setOutcome} />}
        </div>
      </header>

      {outcome && (
        <div
          role="status"
          className={cn(
            'mt-6 rounded-md border px-3 py-2 text-sm',
            outcome.tone === 'ok' &&
              'border-status-success/40 bg-status-success/10 text-status-success',
            outcome.tone === 'warn' &&
              'border-status-queued/40 bg-status-queued/10 text-foreground',
            outcome.tone === 'error' && 'border-destructive/40 bg-destructive/10 text-destructive',
          )}
        >
          {outcome.message}
        </div>
      )}

      <div className="mt-6">
        <RunsBody
          pending={runs.isPending}
          status={runs.data?.status}
          results={results}
          expandedId={expandedId}
          onToggle={(id) => setExpandedId((current) => (current === id ? null : id))}
          onRetry={() => void runs.refetch()}
        />
      </div>

      {page?.next_cursor && (
        <p className="mt-4 text-center text-xs text-muted-foreground">
          Showing the most recent {results.length} runs.
        </p>
      )}
    </div>
  )
}

function RunsBody({
  pending,
  status,
  results,
  expandedId,
  onToggle,
  onRetry,
}: {
  pending: boolean
  status: number | undefined
  results: readonly import('@/api/generated/model').Run[]
  expandedId: string | null
  onToggle: (id: string) => void
  onRetry: () => void
}) {
  if (pending) {
    return (
      <Panel>
        <div className="space-y-4 p-5" aria-busy="true" aria-label="Loading runs">
          {[0, 1, 2].map((row) => (
            <Skeleton key={row} className="h-6 w-full" />
          ))}
        </div>
      </Panel>
    )
  }

  // Dagster being down is its own state, not a generic failure: the portal is
  // fine and the right move is to try again, not to report a broken page.
  if (status === 503 || status === 502) {
    return (
      <Alert className="flex flex-wrap items-center justify-between gap-3">
        <span>
          {status === 503
            ? 'The pipeline service is unreachable.'
            : 'The pipeline service returned an error.'}
        </span>
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      </Alert>
    )
  }

  if (status !== 200) {
    return <Alert>The runs could not be loaded.</Alert>
  }

  if (results.length === 0) {
    return (
      <Panel>
        <div className="px-5 py-12 text-center">
          <p className="text-sm font-medium">No runs yet</p>
          <p className="mt-1 text-sm text-muted-foreground">
            The pipeline has not run. Its weekly schedule ships stopped, so the first run is started
            by hand.
          </p>
        </div>
      </Panel>
    )
  }

  return (
    <Panel>
      {results.map((run) => (
        <RunRow
          key={run.id}
          run={run}
          expanded={expandedId === run.id}
          onToggle={() => onToggle(run.id)}
        />
      ))}
    </Panel>
  )
}

function Panel({ children }: { children: React.ReactNode }) {
  return <div className="overflow-hidden rounded-lg border border-border">{children}</div>
}

/** Re-renders on its own so the label does not sit at "Just now" forever. */
function LastUpdated({ at }: { at: number }) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(timer)
  }, [])

  return <span className="text-sm text-muted-foreground">{formatSince(at, now)}</span>
}
