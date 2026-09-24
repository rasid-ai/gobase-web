import { useEffect, useRef } from 'react'
import type { RefObject } from 'react'
import type { MapRef } from 'react-map-gl/maplibre'
import {
  type GeoJSONStoreFeatures,
  TerraDraw,
  TerraDrawPolygonMode,
  ValidateNotSelfIntersecting,
} from 'terra-draw'
import { TerraDrawMapLibreGLAdapter } from 'terra-draw-maplibre-gl-adapter'

import { AREA_PRECISION, MAX_AREA_CORNERS, type Ring } from './drawnArea'
import { hex } from './mapTokens'

/**
 * The polygon tool, live only while the map is in draw-area mode.
 *
 * terra-draw is used for the act of drawing and nothing else. When a polygon
 * is finished it is handed up and cleared from the tool, and the page draws
 * the outline itself as an ordinary source — so the area outlives the mode,
 * and leaving draw mode to pan around the area does not wipe it.
 *
 * The rules match `AreaField` on the server: no more than MAX_AREA_CORNERS
 * corners, and no edge crossing another. The server still checks both; this
 * is so the user is told at the click that broke the rule, not after.
 *
 * Renders nothing. It drives the map it is given.
 */
export function DrawArea({
  mapRef,
  ready,
  active,
  color,
  onDrawn,
  onRefused,
}: {
  mapRef: RefObject<MapRef | null>
  /**
   * The map has loaded. Not read from MapLibre's `isStyleLoaded()`, which is
   * also false while tiles are loading — and with a raster basemap they load
   * on every pan, so waiting on it would wait for an event that already fired.
   */
  ready: boolean
  active: boolean
  /** A resolved token colour, as `useMapTokens` gives it. */
  color: string
  onDrawn: (ring: Ring) => void
  /** A click was refused, and why, in words for the user. */
  onRefused: (reason: string) => void
}) {
  // The tool is built once per activation. Callbacks change identity on every
  // render of the page, and rebuilding the tool for that would drop a
  // half-drawn polygon, so the latest ones are read through a ref.
  const handlers = useRef({ onDrawn, onRefused })
  useEffect(() => {
    handlers.current = { onDrawn, onRefused }
  })

  useEffect(() => {
    if (!active || !ready) return
    const map = mapRef.current?.getMap()
    if (!map) return

    const colour = hex(color)
    const draw = new TerraDraw({
      // Rounding happens here, as the user draws, so what is sent is exactly
      // what was on screen.
      adapter: new TerraDrawMapLibreGLAdapter({ map, coordinatePrecision: AREA_PRECISION }),
      modes: [
        new TerraDrawPolygonMode({
          validation: (feature, context) => refuse(feature, context.updateType, handlers),
          styles: {
            fillColor: colour,
            fillOpacity: 0.15,
            outlineColor: colour,
            outlineWidth: 2,
            closingPointColor: colour,
            closingPointOutlineColor: colour,
          },
        }),
      ],
    })

    draw.on('finish', (id) => {
      const feature = draw.getSnapshotFeature(id)
      draw.clear()
      if (feature?.geometry.type !== 'Polygon') return
      const ring = feature.geometry.coordinates[0].map(([lon, lat]) => [lon, lat] as const)
      handlers.current.onDrawn(ring)
    })

    // Closing a polygon is a click on its first corner, and two quick clicks
    // there would otherwise zoom the map as well. Panning stays on: a large
    // area needs it mid-draw, and the adapter already holds the map still
    // when a corner is being dragged.
    map.doubleClickZoom.disable()
    draw.start()
    draw.setMode('polygon')

    return () => {
      draw.stop()
      map.doubleClickZoom.enable()
    }
  }, [active, ready, mapRef, color])

  return null
}

/**
 * The validation terra-draw runs on each change to the polygon being drawn.
 *
 * Not on provisional updates, which fire as the pointer moves: refusing the
 * cursor's position would stop the rubber-band line following it, and saying
 * so on every mouse move would be noise. A click and the finish are what get
 * checked, and only those are reported.
 */
function refuse(
  feature: GeoJSONStoreFeatures,
  updateType: string,
  handlers: { current: { onRefused: (reason: string) => void } },
): { valid: boolean; reason?: string } {
  if (updateType === 'provisional' || feature.geometry.type !== 'Polygon') return { valid: true }

  // Distinct points, not ring length: while drawing, the ring also carries a
  // closing point and the cursor's, and either would count a corner twice.
  const corners = new Set(feature.geometry.coordinates[0].map((point) => point.join(','))).size
  if (corners > MAX_AREA_CORNERS) {
    const reason = `An area can have at most ${MAX_AREA_CORNERS} corners.`
    handlers.current.onRefused(reason)
    return { valid: false, reason }
  }

  const crossing = ValidateNotSelfIntersecting(feature)
  if (!crossing.valid) {
    const reason = "An area's edges can't cross each other."
    handlers.current.onRefused(reason)
    return { valid: false, reason }
  }
  return { valid: true }
}
