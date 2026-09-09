/**
 * How Dagster's status strings become something on screen.
 *
 * The API passes Dagster's values through unchanged, so this is the one place
 * that knows them. Two separate vocabularies arrive: a run has nine possible
 * statuses, a step only four, and they are not the same four.
 */

export type Tone = 'success' | 'running' | 'failed' | 'queued' | 'neutral'

export type StatusLook = {
  tone: Tone
  label: string
  /** Ring dot instead of a disc, for states that are not going anywhere. */
  hollow: boolean
}

/** Runs that have not finished. The page refreshes while any of these show. */
export const ACTIVE_RUN_STATUSES = ['QUEUED', 'NOT_STARTED', 'MANAGED', 'STARTING', 'STARTED']

// Nine statuses onto four tokens. The two canceled states have no token of
// their own; they take the muted neutral rather than a colour invented here.
const RUN_LOOK: Record<string, StatusLook> = {
  SUCCESS: { tone: 'success', label: 'Success', hollow: false },
  FAILURE: { tone: 'failed', label: 'Failed', hollow: false },
  QUEUED: { tone: 'queued', label: 'Queued', hollow: false },
  NOT_STARTED: { tone: 'queued', label: 'Not started', hollow: false },
  STARTING: { tone: 'running', label: 'Starting', hollow: false },
  STARTED: { tone: 'running', label: 'Running', hollow: false },
  MANAGED: { tone: 'running', label: 'Managed', hollow: false },
  CANCELING: { tone: 'neutral', label: 'Canceling', hollow: true },
  CANCELED: { tone: 'neutral', label: 'Canceled', hollow: true },
}

const STEP_LOOK: Record<string, StatusLook> = {
  SUCCESS: { tone: 'success', label: 'Success', hollow: false },
  FAILURE: { tone: 'failed', label: 'Failed', hollow: false },
  IN_PROGRESS: { tone: 'running', label: 'Running', hollow: false },
  SKIPPED: { tone: 'neutral', label: 'Skipped', hollow: true },
}

/** `SOME_NEW_STATE` -> `Some new state`, so an unknown value still reads. */
function humanise(status: string): string {
  const words = status.replace(/_/g, ' ').toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function look(table: Record<string, StatusLook>, status: string | null): StatusLook {
  if (!status) return { tone: 'neutral', label: 'Unknown', hollow: true }
  // A Dagster upgrade can add a status. Showing it plainly beats crashing or
  // silently colouring it as something it is not.
  return table[status] ?? { tone: 'neutral', label: humanise(status), hollow: true }
}

export const runStatusLook = (status: string | null) => look(RUN_LOOK, status)
export const stepStatusLook = (status: string | null) => look(STEP_LOOK, status)

export const isRunActive = (status: string) => ACTIVE_RUN_STATUSES.includes(status)
