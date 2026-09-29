import type { Bbox } from '@/features/places/bbox'

/**
 * The area a layer is read for, from the area the map is showing.
 *
 * Not the viewport itself. Asking for exactly what is on screen would mean a
 * new request for every pixel of pan, each with a key nothing has answered
 * before. So the viewport is padded, then snapped outward onto a grid: small
 * moves land on the same window, the cache answers them, and nothing is
 * fetched twice.
 *
 * The window always covers the viewport. It is never smaller, so there is no
 * gap at the edge of the screen — only extra, already loaded, just off it.
 */

/** How far past the viewport to read, as a share of its width. */
const PAD = 0.25

/**
 * The grid cell size at a zoom level.
 *
 * Roughly one viewport per cell: a screen is about `360 / 2 ** (zoom - 2)`
 * degrees wide at common window sizes. Larger cells would refetch less and
 * read much more; smaller ones the other way round. Tuned by eye.
 */
function stepFor(zoom: number): number {
  return 360 / 2 ** Math.max(0, Math.floor(zoom) - 2)
}

const clampLon = (value: number) => Math.min(180, Math.max(-180, value))
const clampLat = (value: number) => Math.min(90, Math.max(-90, value))

export function windowFor(viewport: Bbox, zoom: number): Bbox {
  const [west, south, east, north] = viewport
  const step = stepFor(zoom)
  const padLon = (east - west) * PAD
  const padLat = (north - south) * PAD

  // Floor the minimums and ceil the maximums, so snapping only ever grows the
  // box. Rounding would sometimes cut a corner off the viewport.
  return [
    clampLon(Math.floor((west - padLon) / step) * step),
    clampLat(Math.floor((south - padLat) / step) * step),
    clampLon(Math.ceil((east + padLon) / step) * step),
    clampLat(Math.ceil((north + padLat) / step) * step),
  ]
}
