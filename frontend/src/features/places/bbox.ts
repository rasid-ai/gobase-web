/** An area as [min_lon, min_lat, max_lon, max_lat], SRID 4326. */
export type Bbox = [number, number, number, number]

const DECIMAL = /^[+-]?(\d+(\.\d*)?|\.\d+)$/

/**
 * Read an area out of a URL, or null if it cannot be read.
 *
 * Kept in step with `BboxField` in backend/apps/catalog/serializers.py: the two
 * validate the same thing on either side of the wire, and a link this accepts
 * must not be one the API rejects.
 *
 * `Number()` is not enough on its own — it takes `0x10`, `1e5` and `Infinity`,
 * none of which belong in a coordinate. Same reason `coordinates.ts` has its
 * own decimal pattern.
 */
export function parseBbox(raw: string | null): Bbox | null {
  if (!raw) return null

  const parts = raw.split(',')
  if (parts.length !== 4 || !parts.every((part) => DECIMAL.test(part.trim()))) return null

  const [minLon, minLat, maxLon, maxLat] = parts.map((part) => Number(part))
  if (minLon < -180 || maxLon > 180 || minLon > 180 || maxLon < -180) return null
  if (minLat < -90 || maxLat > 90 || minLat > 90 || maxLat < -90) return null
  // Equal corners are fine — a zero-area box asks what covers one spot. Only
  // inside-out is meaningless.
  if (minLon > maxLon || minLat > maxLat) return null

  return [minLon, minLat, maxLon, maxLat]
}

/** The same area as the URL and the API carry it. */
export function serializeBbox(bbox: Bbox): string {
  return bbox.join(',')
}
