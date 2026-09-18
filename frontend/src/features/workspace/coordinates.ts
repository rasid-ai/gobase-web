/**
 * Reading a coordinate pair typed or pasted by a person.
 *
 * The input is **latitude first**, the order every mapping site writes and the
 * order anything copied from one will be in. The API takes `lon, lat`, so the
 * swap happens here and nowhere else (specs/map.md).
 */

export type Coordinates = { lat: number; lon: number }

export type ParseResult = { ok: true; value: Coordinates } | { ok: false; error: string }

export const FORMAT_HINT = 'Enter latitude, longitude — for example 51.0504, 13.7373'

/** A plain decimal number, optionally signed. */
const DECIMAL = /^[+-]?(\d+(\.\d*)?|\.\d+)$/

/**
 * Parse one decimal value.
 *
 * The regex rather than `Number()` alone, because `Number` accepts things no
 * one means as a coordinate — `0x10`, `1e5`, `Infinity` — and turns an empty
 * string into 0.
 */
function toNumber(text: string): number | null {
  if (!DECIMAL.test(text)) return null
  const value = Number(text)
  return Number.isFinite(value) ? value : null
}

/**
 * Read "lat, lon" from free text.
 *
 * A comma or any run of whitespace separates the two, so both `51.05, 13.73`
 * and `51.05 13.73` work — a pasted pair should not need editing first.
 *
 * A reversed pair cannot be detected when both values are in range: `13.73,
 * 51.05` is a legitimate coordinate in the Indian Ocean. The label carries the
 * order; nothing here guesses at intent.
 */
export function parseCoordinates(text: string): ParseResult {
  const parts = text
    .trim()
    .split(/[\s,]+/)
    .filter(Boolean)
  if (parts.length !== 2) return { ok: false, error: FORMAT_HINT }

  const lat = toNumber(parts[0])
  const lon = toNumber(parts[1])
  if (lat === null || lon === null) return { ok: false, error: FORMAT_HINT }

  if (lat < -90 || lat > 90) {
    return { ok: false, error: `Latitude must be between -90 and 90. Got ${lat}.` }
  }
  if (lon < -180 || lon > 180) {
    return { ok: false, error: `Longitude must be between -180 and 180. Got ${lon}.` }
  }

  return { ok: true, value: { lat, lon } }
}

/**
 * Is this text an attempt at a coordinate pair, valid or not?
 *
 * Two numbers, separated by a comma or a space. The answer decides which of
 * the two searches runs, so it has to be about shape and not about validity:
 * `91, 13.7` is an out-of-range coordinate and deserves the range error, not a
 * geocoder that will make nothing of it. `Beirut` is not an attempt at all.
 */
export function looksLikeCoordinates(text: string): boolean {
  const parts = text
    .trim()
    .split(/[\s,]+/)
    .filter(Boolean)
  return parts.length === 2 && parts.every((part) => DECIMAL.test(part))
}
