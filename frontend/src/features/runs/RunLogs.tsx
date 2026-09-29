import { useState } from 'react'

import { useRunsLogs } from '@/api/generated/runs/runs'
import type { LogEvent } from '@/api/generated/model'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

import { atLeast, DEFAULT_MIN_LEVEL, LEVEL_CHOICES, levelTone, type LogLevel } from './logLevels'

const PAGE_SIZE = 200
const TIME = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

/**
 * A run's event log, behind a disclosure inside the opened row.
 *
 * It is not shown by default on purpose: steps are the reason to open a run,
 * and a log is hundreds of lines that only matter when something went wrong.
 * Nothing is fetched until it is asked for.
 */
export function RunLogs({ runId }: { runId: string }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="border-t border-border pt-3">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground hover:text-foreground"
      >
        {open ? 'Hide event log' : 'Show event log'}
      </button>
      {open && <LogStream runId={runId} />}
    </div>
  )
}

function LogStream({ runId }: { runId: string }) {
  const [minLevel, setMinLevel] = useState<LogLevel>(DEFAULT_MIN_LEVEL)
  const [pages, setPages] = useState<LogEvent[][]>([])
  const [cursor, setCursor] = useState<string | null>(null)

  const logs = useRunsLogs(runId, { limit: PAGE_SIZE, ...(cursor ? { cursor } : {}) })
  const current = logs.data?.status === 200 ? logs.data.data : null

  // Pages accumulate: the log reads forward from a cursor, so each answer is
  // appended rather than replacing what is already on screen.
  const seen = current ? [...pages, [...current.events]] : pages
  const events = seen.flat().filter((event) => atLeast(event.level, minLevel))
  const hidden = seen.flat().length - events.length

  if (logs.isPending && pages.length === 0) {
    return (
      <div className="mt-3 space-y-2" aria-busy="true" aria-label="Loading the event log">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-4/5" />
        <Skeleton className="h-4 w-3/5" />
      </div>
    )
  }

  if (logs.data?.status !== 200) {
    return (
      <Alert className="mt-3">
        {logs.data?.status === 404
          ? 'This run is no longer in Dagster.'
          : 'The event log could not be loaded.'}
      </Alert>
    )
  }

  return (
    <div className="mt-3 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
          Level
        </span>
        {LEVEL_CHOICES.map((choice) => (
          <button
            key={choice.value}
            type="button"
            aria-pressed={minLevel === choice.value}
            onClick={() => setMinLevel(choice.value)}
            className={cn(
              'rounded-full border px-2.5 py-0.5 text-xs transition-colors',
              minLevel === choice.value
                ? 'border-primary/40 bg-primary/10 text-primary'
                : 'border-border text-muted-foreground hover:text-foreground',
            )}
          >
            {choice.label}
          </button>
        ))}
        {hidden > 0 && (
          <span className="text-xs text-muted-foreground">{hidden} hidden by this level</span>
        )}
      </div>

      {events.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Nothing at this level. Dagster logs most of a run at debug level.
        </p>
      ) : (
        <ul className="max-h-96 overflow-y-auto rounded-md border border-border bg-input/40">
          {events.map((event, index) => (
            <LogLine key={`${event.timestamp}-${index}`} event={event} />
          ))}
        </ul>
      )}

      {current?.has_more && (
        <Button
          variant="outline"
          size="sm"
          disabled={logs.isFetching}
          onClick={() => {
            setPages(seen)
            setCursor(current.next_cursor)
          }}
        >
          {logs.isFetching ? 'Loading…' : 'Load more'}
        </Button>
      )}
    </div>
  )
}

function LogLine({ event }: { event: LogEvent }) {
  const [showStack, setShowStack] = useState(false)
  const tone = levelTone(event.level)
  const time = event.timestamp ? TIME.format(new Date(event.timestamp)) : ''
  // Dagster emits genuinely empty messages; a blank row with no explanation
  // reads as a rendering bug, so it is labelled.
  const message = event.message?.trim()

  return (
    <li className="border-b border-border/60 px-3 py-1.5 last:border-b-0">
      <div className="flex gap-3 font-mono text-xs leading-relaxed">
        <span className="shrink-0 text-muted-foreground">{time}</span>
        <span
          className={cn(
            'w-16 shrink-0 uppercase',
            tone === 'failed' && 'text-status-failed',
            tone === 'queued' && 'text-status-queued',
            tone === 'muted' && 'text-muted-foreground',
          )}
        >
          {event.level}
        </span>
        {/*
          Always rendered, even when empty: most events carry no step key, and
          letting the column collapse leaves every message at a different
          indent down the log.
        */}
        <span
          className="w-32 shrink-0 truncate text-muted-foreground"
          title={event.step_key ?? undefined}
        >
          {event.step_key}
        </span>
        <span
          className={cn(
            'min-w-0 whitespace-pre-wrap break-words',
            !message && 'italic text-muted-foreground',
          )}
        >
          {message || 'no message'}
        </span>
      </div>

      {event.error && (
        <div className="mt-1 pl-3">
          <button
            type="button"
            onClick={() => setShowStack((value) => !value)}
            aria-expanded={showStack}
            className="text-xs text-status-failed hover:underline"
          >
            {showStack ? 'Hide stack' : 'Show stack'}
          </button>
          <p className="mt-1 font-mono text-xs text-status-failed">{event.error.message}</p>
          {showStack && (
            <pre className="mt-1 overflow-x-auto rounded border border-border bg-background p-2 font-mono text-[11px] text-muted-foreground">
              {event.error.stack.join('')}
            </pre>
          )}
        </div>
      )}
    </li>
  )
}
