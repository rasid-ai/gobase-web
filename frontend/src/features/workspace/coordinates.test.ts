import { describe, expect, it } from 'vitest'

import { FORMAT_HINT, parseCoordinates } from './coordinates'

/** Latitude first, as every mapping site writes it (specs/map.md). */
describe('parseCoordinates', () => {
  it('reads a pasted pair', () => {
    expect(parseCoordinates('51.0504, 13.7373')).toEqual({
      ok: true,
      value: { lat: 51.0504, lon: 13.7373 },
    })
  })

  it.each([
    ['spaces instead of a comma', '51.0504 13.7373'],
    ['padding around it', '  51.0504,13.7373  '],
    ['a space after the comma only', '51.0504,  13.7373'],
  ])('reads a pair with %s', (_label, text) => {
    expect(parseCoordinates(text)).toEqual({
      ok: true,
      value: { lat: 51.0504, lon: 13.7373 },
    })
  })

  it('reads negative and zero values', () => {
    expect(parseCoordinates('-33.8688, -151.2093')).toEqual({
      ok: true,
      value: { lat: -33.8688, lon: -151.2093 },
    })
    expect(parseCoordinates('0, 0')).toEqual({ ok: true, value: { lat: 0, lon: 0 } })
  })

  it('accepts the exact limits', () => {
    expect(parseCoordinates('90, 180').ok).toBe(true)
    expect(parseCoordinates('-90, -180').ok).toBe(true)
  })

  it.each([
    ['empty', ''],
    ['one value', '51.0504'],
    ['three values', '51.0504, 13.7373, 9'],
    ['words', 'Dresden'],
    ['a half-typed number', '51.0504, 13.7.3'],
    ['scientific notation', '5.1e1, 13.7373'],
    ['hex', '0x33, 13.7373'],
  ])('rejects %s with the format hint', (_label, text) => {
    expect(parseCoordinates(text)).toEqual({ ok: false, error: FORMAT_HINT })
  })

  it('names the offending value when latitude is out of range', () => {
    const result = parseCoordinates('91, 13.7373')
    expect(result.ok).toBe(false)
    expect(result.ok === false && result.error).toMatch(/Latitude must be between -90 and 90/)
  })

  it('names the offending value when longitude is out of range', () => {
    const result = parseCoordinates('51.0504, 181')
    expect(result.ok).toBe(false)
    expect(result.ok === false && result.error).toMatch(/Longitude must be between -180 and 180/)
  })

  it('takes a reversed pair at face value when both values are in range', () => {
    // 13.73, 51.05 is a real place in the Indian Ocean. Nothing here can tell
    // it from a mistake, so the label carries the order and this does not guess.
    expect(parseCoordinates('13.7373, 51.0504')).toEqual({
      ok: true,
      value: { lat: 13.7373, lon: 51.0504 },
    })
  })

  it('rejects a reversed pair only when it puts latitude out of range', () => {
    // The common paste mistake for a high-latitude place, which is catchable.
    expect(parseCoordinates('13.7373, 151.05').ok).toBe(true)
    expect(parseCoordinates('151.05, 13.7373').ok).toBe(false)
  })
})
