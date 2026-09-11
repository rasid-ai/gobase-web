import type { StyleSpecification } from 'maplibre-gl'
import { useCallback, useMemo, useRef, useState } from 'react'
import Map, {
  Layer,
  type MapLayerMouseEvent,
  type MapRef,
  Marker,
  Source,
} from 'react-map-gl/maplibre'

import { mapAssetData, useMapAssetDetail, useMapAssetsAtPoint } from '@/api/generated/map/map'
import type { AssetSummary } from '@/api/generated/model'
import { useToast } from '@/components/ui/toast'
import { cn } from '@/lib/utils'

import { AssetDetailPanel, AssetList } from './AssetPanel'
import { LayersPanel } from './LayersPanel'
import {
  type ActiveLayer,
  LayersProvider,
  boundsOf,
  toFeatureCollection,
  useLayers,
} from './layers'
import { useMapTokens } from './mapTokens'

import 'maplibre-gl/dist/maplibre-gl.css'

/**
 * The Map workspace (specs/map.md).
 *
 * Click a point, see the catalog assets whose coverage includes it grouped by
 * data type, select one to see its metadata and footprint. Drawing an area is
 * the mode shell only — its behaviour waits on the Q&A engine decision.
 */

/** The three interaction modes are mutually exclusive (specs/map.md). */
const MODES = ['navigate', 'point', 'area'] as const
type Mode = (typeof MODES)[number]

const MODE_LABEL: Record<Mode, string> = {
  navigate: 'Navigate',
  point: 'Point',
  area: 'Draw area',
}

const OSM: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      attribution: '© OpenStreetMap contributors',
    },
  },
  layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
}

type Point = { lon: number; lat: number }

/**
 * The layer store is scoped to the Map, not the app.
 *
 * It wraps the page here rather than at the route so that anything rendering
 * the workspace — the router, a test — gets the store without extra wiring.
 */
export function WorkspacePage() {
  return (
    <LayersProvider>
      <MapWorkspace />
    </LayersProvider>
  )
}

function MapWorkspace() {
  const [mode, setMode] = useState<Mode>('point')
  const [point, setPoint] = useState<Point | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [loadingId, setLoadingId] = useState<string | null>(null)
  const tokens = useMapTokens()
  const toast = useToast()
  const { layers, add } = useLayers()
  const map = useRef<MapRef | null>(null)

  const assets = useMapAssetsAtPoint(
    { lon: point?.lon ?? 0, lat: point?.lat ?? 0 },
    { query: { enabled: point !== null } },
  )

  const detail = useMapAssetDetail(selectedId ?? '', {
    query: { enabled: selectedId !== null },
  })

  const groups = assets.data?.status === 200 ? assets.data.data.groups : []
  const selected = detail.data?.status === 200 ? detail.data.data : null

  const footprint = useMemo(() => {
    if (!selected?.footprint) return null
    return { type: 'Feature' as const, properties: {}, geometry: selected.footprint }
  }, [selected])

  function onMapClick(event: MapLayerMouseEvent) {
    // Only point mode inspects; navigate and area leave clicks to the map.
    if (mode !== 'point') return
    setSelectedId(null)
    setPoint({ lon: event.lngLat.lng, lat: event.lngLat.lat })
  }

  // Clearing a selection keeps the list open — deselecting returns you to it.
  // Drawn layers are untouched: they outlive the selection (docs/adr/008).
  const clearSelection = () => setSelectedId(null)

  /**
   * Load an asset's features and draw them.
   *
   * Called directly rather than through a query hook: this is an action with a
   * start and an end, not state the page reads, and the result lives in the
   * layer store afterwards rather than in the cache.
   */
  const draw = useCallback(
    async (asset: AssetSummary) => {
      setLoadingId(asset.asset_id)
      try {
        const response = await mapAssetData(asset.asset_id)
        if (response.status !== 200) {
          toast.show(
            response.status === 404
              ? 'That asset has no vector data to draw.'
              : 'The data lake could not be read. Try again shortly.',
          )
          return
        }

        const data = response.data
        // The footprint comes from the detail endpoint, which may not have been
        // fetched; a layer without one simply draws no outline.
        const footprint = selectedId === asset.asset_id ? (selected?.footprint ?? null) : null

        add({
          assetId: asset.asset_id,
          label: label(asset),
          features: data.features,
          footprint,
          truncated: data.truncated,
          count: data.count,
        })

        // The footprint is the asset's own coverage and the better frame when
        // we have it; otherwise fall back to the extent of what was drawn.
        const box = (footprint ? boundsOf(footprint) : null) ?? boundsFrom(data.features)
        if (box) {
          map.current?.fitBounds(
            [
              [box[0], box[1]],
              [box[2], box[3]],
            ],
            { padding: 48, duration: 600 },
          )
        }
      } catch {
        toast.show('The data lake could not be reached. Try again shortly.')
      } finally {
        setLoadingId(null)
      }
    },
    [add, selected, selectedId, toast],
  )

  return (
    <div className="relative h-full w-full">
      <Map
        ref={map}
        initialViewState={{ longitude: 33.003, latitude: 33.545, zoom: 11 }}
        mapStyle={OSM}
        onClick={onMapClick}
        cursor={mode === 'point' ? 'crosshair' : 'grab'}
        dragPan={mode !== 'area'}
        style={{ position: 'absolute', inset: 0 }}
      >
        {point ? (
          <Marker longitude={point.lon} latitude={point.lat} color={tokens.selection} />
        ) : null}

        {layers.map((layer) => (
          <DrawnLayer key={layer.assetId} layer={layer} color={tokens.result} />
        ))}

        {footprint ? (
          <Source id="footprint" type="geojson" data={footprint}>
            <Layer
              id="footprint-fill"
              type="fill"
              paint={{ 'fill-color': tokens.footprint, 'fill-opacity': 0.25 }}
            />
            <Layer
              id="footprint-line"
              type="line"
              paint={{ 'line-color': tokens.footprint, 'line-width': 1.5 }}
            />
          </Source>
        ) : null}
      </Map>

      <ModeSwitch mode={mode} onChange={setMode} />
      <LayersPanel />

      {/*
        Nothing covering the point renders nothing at all — no panel, no error
        (specs/map.md).
      */}
      {groups.length > 0 ? (
        <aside
          aria-label="Assets at this point"
          className="absolute right-4 top-4 bottom-4 z-10 flex w-[22rem] flex-col overflow-y-auto rounded-lg border border-border bg-background/95 p-4 backdrop-blur"
        >
          {selected ? (
            <AssetDetailPanel detail={selected} onClear={clearSelection} />
          ) : (
            <AssetList
              groups={groups}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onDraw={draw}
              loadingId={loadingId}
            />
          )}
        </aside>
      ) : null}
    </div>
  )
}

function ModeSwitch({ mode, onChange }: { mode: Mode; onChange: (mode: Mode) => void }) {
  return (
    <div
      role="radiogroup"
      aria-label="Map mode"
      className="absolute left-4 top-4 z-10 flex overflow-hidden rounded-md border border-border bg-background/95 backdrop-blur"
    >
      {MODES.map((option) => (
        <button
          key={option}
          type="button"
          role="radio"
          aria-checked={mode === option}
          onClick={() => onChange(option)}
          className={cn(
            'px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.06em]',
            mode === option
              ? 'bg-map-footprint/15 text-foreground'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {MODE_LABEL[option]}
        </button>
      ))}
    </div>
  )
}

/**
 * One drawn asset: its features, and its footprint outline when known.
 *
 * Three layers because a single file may hold points, lines and polygons at
 * once — 10 of the catalog's 22 vector layers are mixed. Each filters on
 * geometry type so nothing is drawn with the wrong mark.
 */
function DrawnLayer({ layer, color }: { layer: ActiveLayer; color: string }) {
  const data = useMemo(() => toFeatureCollection(layer.features), [layer.features])
  const visibility = layer.visible ? 'visible' : 'none'

  return (
    <Source id={`asset-${layer.assetId}`} type="geojson" data={data}>
      <Layer
        id={`asset-${layer.assetId}-fill`}
        type="fill"
        filter={['==', ['geometry-type'], 'Polygon']}
        layout={{ visibility }}
        paint={{ 'fill-color': color, 'fill-opacity': 0.25 }}
      />
      <Layer
        id={`asset-${layer.assetId}-line`}
        type="line"
        // Lines and polygon outlines share this layer, which is why it does not
        // filter to LineString only.
        filter={['!=', ['geometry-type'], 'Point']}
        layout={{ visibility }}
        paint={{ 'line-color': color, 'line-width': 1.5 }}
      />
      <Layer
        id={`asset-${layer.assetId}-circle`}
        type="circle"
        filter={['==', ['geometry-type'], 'Point']}
        layout={{ visibility }}
        paint={{ 'circle-color': color, 'circle-radius': 3, 'circle-opacity': 0.85 }}
      />
    </Source>
  )
}

/** The bounding box across every feature drawn, for the initial zoom. */
function boundsFrom(
  features: readonly { geometry: unknown }[],
): [number, number, number, number] | null {
  let box: [number, number, number, number] | null = null
  for (const feature of features) {
    const next = boundsOf(feature.geometry)
    if (!next) continue
    box = box
      ? [
          Math.min(box[0], next[0]),
          Math.min(box[1], next[1]),
          Math.max(box[2], next[2]),
          Math.max(box[3], next[3]),
        ]
      : next
  }
  return box
}

/** The catalog has no display name, so the source it came from is the identity. */
function label(asset: AssetSummary): string {
  if (asset.summary) return asset.summary
  const uri = asset.source_uri ?? ''
  return uri.split('/').filter(Boolean).pop() || uri || asset.asset_id
}
