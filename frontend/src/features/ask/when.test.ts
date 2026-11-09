import { describe, expect, it } from 'vitest'

import { ago, day } from './when'

const NOW = new Date(2026, 10, 9, 12, 0, 0).getTime()
const MINUTE = 60_000
const before = (ms: number) => new Date(NOW - ms).toISOString()
const on = (year: number, month: number, date: number) =>
  new Date(year, month, date, 9, 0).toISOString()

describe('ago', () => {
  it('counts minutes, then hours, then gives the day', () => {
    expect(ago(before(30_000), NOW)).toBe('just now')
    expect(ago(before(4 * MINUTE), NOW)).toBe('4 min ago')
    expect(ago(before(3 * 60 * MINUTE), NOW)).toBe('3 h ago')
    expect(ago(on(2026, 9, 31), NOW)).toBe('Oct 31')
  })
})

describe('day', () => {
  it('says today, a month and day, or the year too when it is not this one', () => {
    expect(day(on(2026, 10, 9), NOW)).toBe('today')
    expect(day(on(2026, 9, 20), NOW)).toBe('Oct 20')
    expect(day(on(2025, 9, 20), NOW)).toBe('Oct 20, 2025')
  })
})
