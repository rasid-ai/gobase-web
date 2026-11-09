import { useEffect, useState } from 'react'

/**
 * Times as the Ask panel shows them. Display only: the panel prints them in
 * mono capitals, so these return plain words and the CSS does the case.
 */

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

const MONTH_DAY = new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric' })
const MONTH_DAY_YEAR = new Intl.DateTimeFormat('en', {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
})

/** How long ago, for the header: "just now", "4 min ago", "3 h ago", then a date. */
export function ago(iso: string, now: number): string {
  const then = new Date(iso).getTime()
  const elapsed = Math.max(0, now - then)
  if (elapsed < MINUTE) return 'just now'
  if (elapsed < HOUR) return `${Math.floor(elapsed / MINUTE)} min ago`
  if (elapsed < DAY) return `${Math.floor(elapsed / HOUR)} h ago`
  return day(iso, now)
}

/** Which day, for the session list: "today", "Oct 31", or "Oct 31, 2025" in another year. */
export function day(iso: string, now: number): string {
  const date = new Date(iso)
  const today = new Date(now)
  if (date.toDateString() === today.toDateString()) return 'today'
  return (date.getFullYear() === today.getFullYear() ? MONTH_DAY : MONTH_DAY_YEAR).format(date)
}

/** The current time, ticking once a minute, so "4 min ago" moves on its own. */
export function useNow(): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), MINUTE)
    return () => clearInterval(timer)
  }, [])
  return now
}
