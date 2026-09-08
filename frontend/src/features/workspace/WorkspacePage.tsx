import type { StyleSpecification } from 'maplibre-gl'
import { useMemo, useState } from 'react'
import Map, { Layer, type MapLayerMouseEvent, Marker, Source } from 'react-map-gl/maplibre'

import { useMapAssetDetail, useMapAssetsAtPoint } from '@/api/generated/map/map'
import { cn } from '@/lib/utils'

import { AssetDetailPanel, AssetList } from './AssetPanel'
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

export function WorkspacePage() {
  const [mode, setMode] = useState<Mode>('point')
  const [point, setPoint] = useState<Point | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const tokens = useMapTokens()

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
  const clearSelection = () => setSelectedId(null)

  return (
    <div className="relative h-full w-full">
      <Map
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

      {/*
        Nothing covering the point renders nothing at all — no panel, no error
        (specs/map.md).
      */}
      {groups.length > 0 ? (
        <aside className="absolute right-4 top-4 bottom-4 z-10 flex w-[22rem] flex-col overflow-y-auto rounded-lg border border-border bg-background/95 p-4 backdrop-blur">
          {selected ? (
            <AssetDetailPanel detail={selected} onClear={clearSelection} />
          ) : (
            <AssetList groups={groups} selectedId={selectedId} onSelect={setSelectedId} />
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
