/** Display helpers for run data. Formatting only — nothing is derived here. */

/** An em dash, for a value the API genuinely has no answer for. */
export const NONE = '—'

/**
 * Runs range from seconds to hours, so the unit changes with the magnitude
 * rather than padding everything to the largest one.
 */
export function formatDuration(seconds: number | null): string {
  if (seconds === null || Number.isNaN(seconds)) return NONE
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.round((seconds % 3600) / 60)
  return minutes === 0 ? `${hours}h` : `${hours}h ${minutes}m`
}

const STARTED_FORMAT = new Intl.DateTimeFormat(undefined, {
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

export function formatStarted(iso: string | null): string {
  if (!iso) return NONE
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? NONE : STARTED_FORMAT.format(date)
}

/** The full timestamp, for the title attribute behind the short form. */
export function formatExact(iso: string | null): string | undefined {
  if (!iso) return undefined
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? undefined : date.toLocaleString()
}

/** How long ago the list was last fetched, for the refresh control. */
export function formatSince(at: number, now: number): string {
  const seconds = Math.max(0, Math.round((now - at) / 1000))
  if (seconds < 45) return 'Just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  return `${hours}h ago`
}

/** `catalog_ingest` -> `Catalog ingest`. Dagster step keys are snake_case. */
export function formatStepKey(key: string): string {
  const words = key.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

export function formatTrigger(kind: string, name: string | null): string {
  const label = kind.charAt(0).toUpperCase() + kind.slice(1)
  return name ? `${label} · ${name}` : label
}
