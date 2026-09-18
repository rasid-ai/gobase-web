import { useEffect, useState } from 'react'

/** How long typing rests before it counts as a search. */
export const DEBOUNCE_MS = 300

/**
 * A value that lags behind, settling only once it has stopped changing.
 *
 * Every geocode is billed, so a search fires per pause rather than per
 * keystroke (docs/adr/011).
 */
export function useDebounced<T>(value: T, delay = DEBOUNCE_MS): T {
  const [settled, setSettled] = useState(value)

  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])

  return settled
}
