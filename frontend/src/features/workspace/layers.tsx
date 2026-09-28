import type { Feature, FeatureCollection } from 'geojson'
import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import type { AssetDataFeaturesItem } from '@/api/generated/model'
import type { Bbox } from '@/features/places/bbox'

import type { Ring } from './drawnArea'

/**
 * The layers currently drawn on the map, and the area they are drawn for.
 *
 * Layers outlive the selection that loaded them (docs/adr/008): closing the
 * popup, picking another asset or clearing a point all leave them alone. Only
 * the panel's own controls remove them.
 *
 * A layer is an identity and whether it is shown — not its features. The
 * features belong to an area and are read per window (docs/adr/012), so they
 * live in the query cache, where panning back to somewhere already read costs
 * nothing. `useAssetFeatures` is how anything gets at them.
 *
 * The window sits here too because it is what every layer is read for, and
 * because the panels need it as much as the map does. It is the camera, so it
 * never reaches the URL: `?bbox=` already means the area the *user* chose
 * (docs/adr/011), and one name cannot carry both.
 *
 * So does the drawn area, for the same reason. While one is set it replaces
 * the window as the thing every layer is read for, and layers stop following
 * the map (docs/adr/014). Called `drawnArea`, not `area`: `useAreaParam`
 * already means the searched place by that word.
 *
 * A context rather than a state library: this is one list and a handful of
 * operations, and the project has no store to join. It lives above the map so
 * nothing else on the page can reset it by re-rendering.
 */

export type ActiveLayer = {
  assetId: string
  /** What to call it in the panel. The catalog has no display name. */
  label: string
  visible: boolean
}

type LayersApi = {
  layers: readonly ActiveLayer[]
  /** Add a layer, or replace one already loaded for the same asset. */
  add: (layer: Omit<ActiveLayer, 'visible'>) => void
  toggle: (assetId: string) => void
  remove: (assetId: string) => void
  clear: () => void
  has: (assetId: string) => boolean
  /** The area every layer is read for, or null until the map has settled once. */
  view: Bbox | null
  setView: (view: Bbox) => void
  /** A polygon the user drew. While set, layers are read for it, not the view. */
  drawnArea: Ring | null
  setDrawnArea: (area: Ring | null) => void
}

const LayersContext = createContext<LayersApi | null>(null)

export function LayersProvider({ children }: { children: ReactNode }) {
  const [layers, setLayers] = useState<readonly ActiveLayer[]>([])
  const [view, setView] = useState<Bbox | null>(null)
  const [drawnArea, setDrawnArea] = useState<Ring | null>(null)

  const add = useCallback((layer: Omit<ActiveLayer, 'visible'>) => {
    setLayers((current) => {
      const existing = current.find((one) => one.assetId === layer.assetId)
      // Re-adding keeps whether it was hidden: the user's choice survives a refetch.
      const next: ActiveLayer = { ...layer, visible: existing?.visible ?? true }
      return existing
        ? current.map((one) => (one.assetId === layer.assetId ? next : one))
        : [...current, next]
    })
  }, [])

  const toggle = useCallback((assetId: string) => {
    setLayers((current) =>
      current.map((one) => (one.assetId === assetId ? { ...one, visible: !one.visible } : one)),
    )
  }, [])

  const remove = useCallback((assetId: string) => {
    setLayers((current) => current.filter((one) => one.assetId !== assetId))
  }, [])

  const clear = useCallback(() => setLayers([]), [])

  const api = useMemo<LayersApi>(
    () => ({
      layers,
      add,
      toggle,
      remove,
      clear,
      has: (assetId: string) => layers.some((one) => one.assetId === assetId),
      view,
      setView,
      drawnArea,
      setDrawnArea,
    }),
    [layers, add, toggle, remove, clear, view, drawnArea],
  )

  return <LayersContext.Provider value={api}>{children}</LayersContext.Provider>
}

export function useLayers(): LayersApi {
  const context = useContext(LayersContext)
  if (!context) throw new Error('useLayers must be used inside a LayersProvider')
  return context
}

/** A GeoJSON FeatureCollection for MapLibre, from what the API returned. */
export function toFeatureCollection(features: readonly AssetDataFeaturesItem[]): FeatureCollection {
  // The contract types `geometry` as an open object because GeoJSON allows
  // seven geometry types and a null, and an OpenAPI schema has no plain way to
  // say which. The server builds these with DuckDB's ST_AsGeoJSON, so they are
  // GeoJSON Features; the assertion says so once, here, rather than at every
  // `<Source>`. MapLibre's `data` prop is strictly typed now that
  // `@types/geojson` is a direct dependency.
  return {
    type: 'FeatureCollection',
    features: features as unknown as Feature[],
  }
}

/** The bounding box of a GeoJSON geometry, or null if it has no coordinates. */
export function boundsOf(geometry: unknown): [number, number, number, number] | null {
  let minLon = Infinity
  let minLat = Infinity
  let maxLon = -Infinity
  let maxLat = -Infinity

  const walk = (value: unknown) => {
    if (!Array.isArray(value)) return
    // A coordinate pair is two numbers; anything else is a nested ring or list.
    if (typeof value[0] === 'number' && typeof value[1] === 'number') {
      const [lon, lat] = value as [number, number]
      minLon = Math.min(minLon, lon)
      minLat = Math.min(minLat, lat)
      maxLon = Math.max(maxLon, lon)
      maxLat = Math.max(maxLat, lat)
      return
    }
    value.forEach(walk)
  }

  const coordinates = (geometry as { coordinates?: unknown } | null)?.coordinates
  walk(coordinates)

  if (minLon === Infinity) return null
  return [minLon, minLat, maxLon, maxLat]
}
