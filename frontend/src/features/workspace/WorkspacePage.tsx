import type { StyleSpecification } from 'maplibre-gl'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Map, {
  Layer,
  type MapLayerMouseEvent,
  type MapRef,
  Marker,
  Source,
} from 'react-map-gl/maplibre'
import { useSearchParams } from 'react-router-dom'

import { mapAssetData, useMapAssetDetail, useMapAssetsAtPoint } from '@/api/generated/map/map'
import type { Place } from '@/api/generated/model'
import { useToast } from '@/components/ui/toast'
import type { Bbox } from '@/features/places/bbox'
import { useAreaParam } from '@/features/places/useAreaParam'
import { cn } from '@/lib/utils'

import { AssetDetailPanel, AssetList } from './AssetPanel'
import { LayersPanel } from './LayersPanel'
import { PlaceSearch } from './PlaceSearch'
import type { Coordinates } from './coordinates'
import {
  type ActiveLayer,
  LayersProvider,
  boundsOf,
  toFeatureCollection,
  useLayers,
} from './layers'
import { useMapTokens } from './mapTokens'

// Side effect only: points MapLibre at its worker before any map is built.
import './mapWorker'

import 'maplibre-gl/dist/maplibre-gl.css'

/**
 * The Atlas workspace (specs/map.md).
 *
 * Click a point, see the catalog assets whose coverage includes it grouped by
 * data type, select one to see its metadata and footprint, and draw its
 * features. Draw-area is not here yet: it waits on the Q&A engine decision.
 */

/**
 * The interaction modes, mutually exclusive (specs/map.md).
 *
 * Draw-area is absent rather than disabled: its behaviour needs the ask path,
 * which is blocked on the Q&A engine decision, and a control that switches a
 * mode and then does nothing is worse than no control. It returns with GP-7.
 */
const MODES = ['navigate', 'point'] as const
type Mode = (typeof MODES)[number]

const MODE_LABEL: Record<Mode, string> = {
  navigate: 'Navigate',
  point: 'Point',
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

/**
 * Where the map opens: Lebanon, the area the portal is operated for.
 *
 * Centre is the middle of the country's bounding box (lon 35.10-36.63,
 * lat 33.05-34.69) and the zoom fits the whole of it with a little margin.
 * This is a starting view, not a limit — nothing constrains panning.
 */
const HOME_VIEW = { longitude: 35.87, latitude: 33.87, zoom: 8.5 }

/**
 * How the view is framed on a box.
 *
 * `maxZoom` is the important one. An asset's coverage can be a single point —
 * a box with no area — and `fitBounds` answers that with the map's maximum
 * zoom, which is far past the deepest tile the basemap has. The result is an
 * empty screen that looks like a broken map rather than a place. Capping it
 * lands on a neighbourhood instead.
 */
const FIT = { padding: 48, maxZoom: 16, duration: 600 } as const

type Point = { lon: number; lat: number }

/**
 * The layer store is scoped to the Atlas page, not the app.
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
  // An asset can be chosen from the Assets page, which arrives as `?asset=`
  // (docs/adr/009). The parameter is the selection rather than a copy of it, so
  // the link survives a reload and can be shared.
  const [params, setParams] = useSearchParams()
  const linkedId = params.get('asset')
  // The searched area travels in the URL too, and is read the same way
  // (docs/adr/011).
  const [area, setArea] = useAreaParam()

  const [mode, setMode] = useState<Mode>('point')
  const [point, setPoint] = useState<Point | null>(null)
  const [clickedId, setClickedId] = useState<string | null>(null)
  const [loadingId, setLoadingId] = useState<string | null>(null)

  const selectedId = clickedId ?? linkedId
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

  /**
   * The selected asset's coverage.
   *
   * It is a stand-in for data you cannot see, so it gives way as soon as you
   * can see it: drawing the asset's features leaves the box outlining the very
   * thing it was describing. Hiding the layer brings the box back, because
   * then there is nothing to see again.
   */
  const footprint = useMemo(() => {
    if (!selected?.footprint) return null
    const shown = layers.some((layer) => layer.assetId === selected.asset_id && layer.visible)
    if (shown) return null
    return { type: 'Feature' as const, properties: {}, geometry: selected.footprint }
  }, [selected, layers])

  /**
   * Select an asset, or clear the selection.
   *
   * One selection with two ways in — a row in the point list, or the `?asset=`
   * link — so clearing has to take both. Leaving the parameter behind would
   * re-select the linked asset on the next render.
   */
  const select = useCallback(
    (assetId: string | null) => {
      setClickedId(assetId)
      if (params.has('asset')) {
        const next = new URLSearchParams(params)
        next.delete('asset')
        setParams(next, { replace: true })
      }
    },
    [params, setParams],
  )

  function onMapClick(event: MapLayerMouseEvent) {
    // Only point mode inspects; navigate leaves clicks to the map.
    if (mode !== 'point') return
    select(null)
    setPoint({ lon: event.lngLat.lng, lat: event.lngLat.lat })
  }

  /**
   * Go to a typed coordinate, or to a place that was searched for.
   *
   * Deliberately the same end state as `onMapClick`: a point set, the previous
   * selection cleared, the marker moved. The only additions are moving the
   * view, since nothing else would show you where you landed, and switching
   * the mode, so the mode switch keeps telling the truth about what a
   * subsequent click will do.
   *
   * A place may bring its own extent, which is a better frame than any fixed
   * zoom: a country and a street corner are not the same trip. FIT's maxZoom is
   * what stops a tiny extent landing past the deepest tile the basemap has,
   * exactly as it does for an asset's coverage.
   */
  function goTo({ lat, lon }: Coordinates, box?: Bbox | null) {
    setMode('point')
    select(null)
    setPoint({ lon, lat })

    if (box) {
      map.current?.fitBounds(
        [
          [box[0], box[1]],
          [box[2], box[3]],
        ],
        FIT,
      )
      return
    }

    // Keep the current zoom when it is already close enough to be useful;
    // otherwise a marker dropped at world zoom is invisible.
    const current = map.current?.getZoom() ?? 0
    map.current?.flyTo({ center: [lon, lat], zoom: Math.max(current, 12), duration: 800 })
  }

  /**
   * Go to a searched place, and put it in the URL.
   *
   * The parameters describe an area, so a reload restores the framing and the
   * name — not the marker or the panel, which are the result of an action
   * rather than of the area (docs/adr/011).
   */
  function goToPlace(place: Place) {
    const box = place.bbox ? (place.bbox as Bbox) : null
    goTo({ lat: place.lat, lon: place.lon }, box)
    setArea(box ? { name: place.name, bbox: box } : null)
  }

  // Development only: lets the map be inspected from the console when
  // something does not render. Set from the ref rather than `onLoad`, which
  // fires only when the map is first created and so is missed by a hot reload.
  useEffect(() => {
    if (!import.meta.env.DEV) return
    ;(window as unknown as { __map?: unknown }).__map = map.current?.getMap?.() ?? map.current
  })

  // Clearing a selection keeps the list open — deselecting returns you to it.
  // Drawn layers are untouched: they outlive the selection (docs/adr/008).
  const clearSelection = () => select(null)

  /**
   * Frame an asset arrived at from the Assets page.
   *
   * Only for a linked asset, and only once: a row click leaves the view alone,
   * because you are already looking at the place you clicked. A link carries no
   * view at all, so without this the footprint would draw somewhere off-screen.
   */
  const framed = useRef<string | null>(null)
  useEffect(() => {
    if (clickedId) return

    // An asset and an area can both be in the URL, and there is one camera.
    // The asset wins: its coverage is the more specific answer to "where
    // should I be looking".
    const target = linkedId ? `asset:${linkedId}` : area ? `bbox:${area.bbox.join(',')}` : null
    if (!target || framed.current === target) return

    const box = linkedId ? (selected?.footprint ? boundsOf(selected.footprint) : null) : area!.bbox
    if (!box) return

    framed.current = target
    map.current?.fitBounds(
      [
        [box[0], box[1]],
        [box[2], box[3]],
      ],
      FIT,
    )
  }, [linkedId, clickedId, selected, area])

  /**
   * Load an asset's features and draw them.
   *
   * Called directly rather than through a query hook: this is an action with a
   * start and an end, not state the page reads, and the result lives in the
   * layer store afterwards rather than in the cache.
   *
   * Takes an id and a name rather than a catalog row, because both panels draw:
   * the point list has a row to hand and the metadata pane does not.
   */
  const draw = useCallback(
    async (assetId: string, name: string) => {
      setLoadingId(assetId)
      try {
        const response = await mapAssetData(assetId)
        if (response.status !== 200) {
          toast.show(
            response.status === 404
              ? 'That asset has no vector data to draw.'
              : 'The data lake could not be read. Try again shortly.',
          )
          return
        }

        const data = response.data
        // Only used to frame the view below: the asset's own coverage is a
        // better box than the extent of whatever features came back, and the
        // detail endpoint may not have been asked for it.
        const footprint = selectedId === assetId ? (selected?.footprint ?? null) : null

        add({
          assetId,
          label: name,
          features: data.features,
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
            FIT,
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
        initialViewState={HOME_VIEW}
        mapStyle={OSM}
        onClick={onMapClick}
        cursor={mode === 'point' ? 'crosshair' : 'grab'}
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

      <div className="absolute left-4 top-4 z-10 flex flex-col gap-2">
        <ModeSwitch mode={mode} onChange={setMode} />
        <PlaceSearch onGo={goTo} onGoPlace={goToPlace} />
      </div>
      <LayersPanel />

      {/*
        Nothing covering the point renders nothing at all — no panel, no error
        (specs/map.md). An asset reached from the Assets page opens the panel
        too, with no point clicked and so no list behind it.
      */}
      {groups.length > 0 || selected ? (
        <aside
          aria-label={selected ? 'Selected asset' : 'Assets at this point'}
          className="absolute right-4 top-4 bottom-4 z-10 flex w-[22rem] flex-col overflow-y-auto rounded-lg border border-border bg-background/95 p-4 backdrop-blur"
        >
          {selected ? (
            <AssetDetailPanel
              detail={selected}
              onClear={clearSelection}
              onDraw={draw}
              loading={loadingId === selected.asset_id}
            />
          ) : (
            <AssetList
              groups={groups}
              selectedId={selectedId}
              onSelect={select}
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
      className="flex overflow-hidden rounded-md border border-border bg-background/95 backdrop-blur"
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
 * One drawn asset's features.
 *
 * Three layers because a single file may hold points, lines and polygons at
 * once — 10 of the catalog's 22 vector layers are mixed. Each filters on
 * geometry type so nothing is drawn with the wrong mark.
 */
/**
 * Which geometry types each mark draws.
 *
 * Listed in full rather than compared to one name: `geometry-type` reports the
 * feature's own type, so `MultiPolygon` is not `Polygon` and a `==` test drops
 * it silently. The catalog holds both — 12 MultiPolygon and 244
 * MultiLineString features across the Dresden layers.
 */
const AREA_TYPES = ['Polygon', 'MultiPolygon']
const LINE_TYPES = ['LineString', 'MultiLineString', ...AREA_TYPES]
const POINT_TYPES = ['Point', 'MultiPoint']

function DrawnLayer({ layer, color }: { layer: ActiveLayer; color: string }) {
  const data = useMemo(() => toFeatureCollection(layer.features), [layer.features])
  const visibility = layer.visible ? 'visible' : 'none'

  return (
    <Source id={`asset-${layer.assetId}`} type="geojson" data={data}>
      <Layer
        id={`asset-${layer.assetId}-fill`}
        type="fill"
        filter={['in', ['geometry-type'], ['literal', AREA_TYPES]]}
        layout={{ visibility }}
        paint={{ 'fill-color': color, 'fill-opacity': 0.25 }}
      />
      <Layer
        id={`asset-${layer.assetId}-line`}
        type="line"
        // Lines and polygon outlines share this layer, which is why areas are
        // in the list too.
        filter={['in', ['geometry-type'], ['literal', LINE_TYPES]]}
        layout={{ visibility }}
        paint={{ 'line-color': color, 'line-width': 1.5 }}
      />
      <Layer
        id={`asset-${layer.assetId}-circle`}
        type="circle"
        filter={['in', ['geometry-type'], ['literal', POINT_TYPES]]}
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
