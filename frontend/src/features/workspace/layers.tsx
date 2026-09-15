import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import type { AssetDataFeaturesItem } from '@/api/generated/model'

/**
 * The layers currently drawn on the map.
 *
 * Layers outlive the selection that loaded them (docs/adr/008): closing the
 * popup, picking another asset or clearing a point all leave them alone. Only
 * the panel's own controls remove them.
 *
 * A context rather than a state library: this is one list and four operations,
 * and the project has no store to join. It lives above the map so nothing else
 * on the page can reset it by re-rendering.
 */

export type ActiveLayer = {
  assetId: string
  /** What to call it in the panel. The catalog has no display name. */
  label: string
  features: readonly AssetDataFeaturesItem[]
  /** The file held more features than the server returns. */
  truncated: boolean
  count: number
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
}

const LayersContext = createContext<LayersApi | null>(null)

export function LayersProvider({ children }: { children: ReactNode }) {
  const [layers, setLayers] = useState<readonly ActiveLayer[]>([])

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
    }),
    [layers, add, toggle, remove, clear],
  )

  return <LayersContext.Provider value={api}>{children}</LayersContext.Provider>
}

export function useLayers(): LayersApi {
  const context = useContext(LayersContext)
  if (!context) throw new Error('useLayers must be used inside a LayersProvider')
  return context
}

/** A GeoJSON FeatureCollection for MapLibre, from what the API returned. */
export function toFeatureCollection(features: readonly AssetDataFeaturesItem[]) {
  // The contract types `geometry` as an open object because GeoJSON allows
  // seven geometry types and a null; `@types/geojson` is not installed, so
  // there is no narrower type to assert to here. MapLibre's `data` prop is
  // loose enough to take this as it stands.
  return {
    type: 'FeatureCollection' as const,
    features: features as unknown as Record<string, unknown>[],
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
