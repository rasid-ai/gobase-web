/** The window a layer is read for: docs/adr/012. */

import { describe, expect, it } from 'vitest'

import type { Bbox } from '@/features/places/bbox'

import { windowFor } from './view'

const covers = (window: Bbox, viewport: Bbox) =>
  window[0] <= viewport[0] &&
  window[1] <= viewport[1] &&
  window[2] >= viewport[2] &&
  window[3] >= viewport[3]

describe('windowFor', () => {
  it('always covers the viewport', () => {
    // If it did not, there would be a strip at the edge of the screen with
    // nothing drawn on it.
    const viewports: Bbox[] = [
      [13.5, 50.9, 14.0, 51.2],
      [-0.2, 51.4, 0.1, 51.6],
      [35.1, 33.0, 36.7, 34.7],
      [-74.1, 40.6, -73.9, 40.8],
    ]
    for (const viewport of viewports) {
      for (const zoom of [2, 6, 8.5, 12, 16]) {
        expect(covers(windowFor(viewport, zoom), viewport)).toBe(true)
      }
    }
  })

  it('gives one window for small moves, so panning does not refetch', () => {
    const start: Bbox = [13.5, 50.9, 14.0, 51.2]
    const nudged: Bbox = [13.51, 50.91, 14.01, 51.21]

    expect(windowFor(nudged, 8.5)).toEqual(windowFor(start, 8.5))
  })

  it('gives a different window once a move crosses a cell', () => {
    const here: Bbox = [13.5, 50.9, 14.0, 51.2]
    const faraway: Bbox = [20.0, 40.0, 20.5, 40.3]

    expect(windowFor(faraway, 8.5)).not.toEqual(windowFor(here, 8.5))
  })

  it('reads a smaller area as you zoom in', () => {
    const viewport: Bbox = [13.73, 51.05, 13.75, 51.07]
    const area = (box: Bbox) => (box[2] - box[0]) * (box[3] - box[1])

    const wide = area(windowFor(viewport, 8))
    const close = area(windowFor(viewport, 14))

    expect(close).toBeLessThan(wide)
  })

  it('stays inside the world', () => {
    // A view at the edge pads past the pole or the antimeridian, and a bbox
    // the server would refuse is worse than a slightly smaller read.
    const [west, south, east, north] = windowFor([-179.9, -89.9, 179.9, 89.9], 2)

    expect(west).toBeGreaterThanOrEqual(-180)
    expect(south).toBeGreaterThanOrEqual(-90)
    expect(east).toBeLessThanOrEqual(180)
    expect(north).toBeLessThanOrEqual(90)
  })
})
