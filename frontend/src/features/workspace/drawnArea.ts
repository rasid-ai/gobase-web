import type { Feature, Polygon } from 'geojson'

/**
 * A polygon drawn on the map, and how it travels to the API (docs/adr/014).
 *
 * Here rather than beside `places/bbox.ts` because a drawn area never leaves
 * the map: it is component state, not a URL parameter, so it has no business
 * in the module the Assets page shares.
 *
 * The rules the draw tool enforces are the rules `AreaField` checks in
 * backend/apps/catalog/serializers.py — at most MAX_AREA_VERTICES corners, not
 * crossing itself — so a shape the tool finished is never one the server
 * refuses. Kept in step on purpose; the server is still the one that decides.
 */

/** A closed ring of [lon, lat] pairs, SRID 4326: the last pair repeats the first. */
export type Ring = readonly (readonly [number, number])[]

/**
 * The most corners a drawn area may have. Mirrors `MAX_AREA_VERTICES` on the
 * server, where the reason lives: the area travels in a GET query string, and
 * the host nginx refuses a request line over 8 KB.
 */
export const MAX_AREA_CORNERS = 100

/**
 * Decimal places kept on each coordinate: about 11 cm on the ground. The draw
 * tool rounds to this as it draws, so what is sent is what was seen, and it
 * keeps a 100-corner polygon comfortably inside gunicorn's limit.
 */
export const AREA_PRECISION = 6

/** How many corners a closed ring has. The closing pair is not a corner. */
export function cornersOf(ring: Ring): number {
  return Math.max(0, ring.length - 1)
}

/** The ring as WKT, `POLYGON((lon lat, lon lat, ...))`, as `?area=` carries it. */
export function serializeArea(ring: Ring): string {
  return `POLYGON((${ring.map(([lon, lat]) => `${lon} ${lat}`).join(', ')}))`
}

/** The ring as a GeoJSON Feature, for drawing the outline on the map. */
export function areaFeature(ring: Ring): Feature<Polygon> {
  return {
    type: 'Feature',
    properties: {},
    geometry: { type: 'Polygon', coordinates: [ring.map(([lon, lat]) => [lon, lat])] },
  }
}
