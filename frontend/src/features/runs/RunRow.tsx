import { ChevronRight } from 'lucide-react'

import { useRunsDetail } from '@/api/generated/runs/runs'
import type { Run } from '@/api/generated/model'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

import {
  formatDuration,
  formatExact,
  formatStarted,
  formatStepKey,
  formatTrigger,
  NONE,
} from './formatRun'
import { RunLogs } from './RunLogs'
import { runStatusLook, stepStatusLook } from './runStatus'

/**
 * One column template for runs and their steps, so a step's status badge sits
 * directly under its run's. Steps are indented inside the first cell rather
 * than by padding the row, which would shift every column after it.
 */
const COLUMNS =
  'grid grid-cols-[minmax(8rem,16rem)_7.5rem_8.5rem_minmax(0,1fr)_1rem] items-center gap-4'

export function RunRow({
  run,
  expanded,
  onToggle,
}: {
  run: Run
  expanded: boolean
  onToggle: () => void
}) {
  const look = runStatusLook(run.status)
  const panelId = `run-panel-${run.id}`

  return (
    <div className="border-b border-border last:border-b-0">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-controls={panelId}
        className={cn(
          COLUMNS,
          'w-full px-5 py-4 text-left transition-colors hover:bg-muted-foreground/5',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
        )}
      >
        {/* Run ids are data chrome, so they are mono (context/design-system.md). */}
        <span className="truncate font-mono text-sm" title={run.id}>
          {run.short_id}
        </span>
        <Badge tone={look.tone} hollow={look.hollow} className="justify-self-start">
          {look.label}
        </Badge>
        <span className="text-sm text-muted-foreground" title={formatExact(run.created_at)}>
          {formatStarted(run.started_at ?? run.created_at)}
        </span>
        <span className="text-sm text-muted-foreground">
          {formatDuration(run.duration_seconds)}
        </span>
        <ChevronRight
          aria-hidden="true"
          className={cn(
            'size-4 text-muted-foreground transition-transform',
            expanded && 'rotate-90',
          )}
        />
      </button>

      {expanded && (
        <div id={panelId} className="border-t border-border bg-muted-foreground/[0.03] px-5 py-4">
          <RunSteps runId={run.id} />
        </div>
      )}
    </div>
  )
}

/**
 * The per-step breakdown, fetched only when a row is opened. A run's steps are
 * the reason to open it at all, so nothing else is loaded up front.
 */
function RunSteps({ runId }: { runId: string }) {
  const detail = useRunsDetail(runId)

  if (detail.isPending) {
    return (
      <div className="space-y-2" aria-busy="true" aria-label="Loading run detail">
        <Skeleton className="h-5 w-64" />
        <Skeleton className="h-5 w-52" />
      </div>
    )
  }

  if (detail.data?.status !== 200) {
    return (
      <Alert>
        {detail.data?.status === 404
          ? 'This run is no longer in Dagster.'
          : 'The run detail could not be loaded.'}
      </Alert>
    )
  }

  const run = detail.data.data

  return (
    <div className="space-y-3">
      {run.failure_summary && (
        <Alert>
          <span className="font-mono text-[11px] uppercase tracking-[0.06em]">Failure</span>
          <p className="mt-1 whitespace-pre-wrap">{run.failure_summary}</p>
        </Alert>
      )}

      <dl className="flex flex-wrap gap-x-8 gap-y-1 text-xs text-muted-foreground">
        <div className="flex gap-2">
          <dt>Trigger</dt>
          <dd className="text-foreground">{formatTrigger(run.trigger.kind, run.trigger.name)}</dd>
        </div>
        <div className="flex gap-2">
          <dt>Job</dt>
          <dd className="font-mono text-foreground">{run.job_name}</dd>
        </div>
        <div className="flex gap-2">
          <dt>Materializations</dt>
          <dd className="text-foreground">{run.materializations ?? NONE}</dd>
        </div>
      </dl>

      {run.steps.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No step detail. Dagster reports steps once a run starts executing.
        </p>
      ) : (
        <ul className="space-y-1">
          {run.steps.map((step) => {
            const stepLook = stepStatusLook(step.status)
            return (
              <li key={step.step_key} className={cn(COLUMNS, 'py-1')}>
                <span className="truncate pl-4 text-sm" title={step.step_key}>
                  {formatStepKey(step.step_key)}
                </span>
                <Badge tone={stepLook.tone} hollow={stepLook.hollow} className="justify-self-start">
                  {stepLook.label}
                </Badge>
                <span className="text-sm text-muted-foreground">
                  {formatDuration(step.duration_seconds)}
                </span>
              </li>
            )
          })}
        </ul>
      )}

      <RunLogs runId={run.id} />
    </div>
  )
}
