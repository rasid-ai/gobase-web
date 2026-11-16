/**
 * Dagster's LogLevel enum, in severity order.
 *
 * A real run's log is mostly DEBUG — 14 of 18 events on the first run this
 * was built against — so the viewer defaults to INFO. The filter picks a
 * minimum level rather than an exact one, which is how log levels are
 * normally read and keeps DEBUG one click away instead of gone.
 */
export const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const

export type LogLevel = (typeof LOG_LEVELS)[number]

export const DEFAULT_MIN_LEVEL: LogLevel = 'INFO'

/** The choices offered; CRITICAL is folded into ERROR, being vanishingly rare. */
export const LEVEL_CHOICES: { value: LogLevel; label: string }[] = [
  { value: 'DEBUG', label: 'All' },
  { value: 'INFO', label: 'Info' },
  { value: 'WARNING', label: 'Warning' },
  { value: 'ERROR', label: 'Error' },
]

export function atLeast(level: string | null, minimum: LogLevel): boolean {
  // An unrecognised level is never hidden: a filter that silently swallows
  // something unknown is worse than a little noise.
  const index = LOG_LEVELS.indexOf(level as LogLevel)
  if (index === -1) return true
  return index >= LOG_LEVELS.indexOf(minimum)
}

export function levelTone(level: string | null): 'failed' | 'queued' | 'muted' {
  if (level === 'ERROR' || level === 'CRITICAL') return 'failed'
  if (level === 'WARNING') return 'queued'
  return 'muted'
}
