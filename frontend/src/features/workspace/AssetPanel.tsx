import { keepPreviousData } from '@tanstack/react-query'
import { ChevronLeft, Maximize2, Minimize2 } from 'lucide-react'
import { useState } from 'react'

import { useCatalogAssetList, useCatalogDatasetList } from '@/api/generated/catalog/catalog'
import type { AssetDetail, AssetListItem, Dataset } from '@/api/generated/model'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Segmented } from '@/components/ui/segmented'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

import { MetadataValue, formatScalar, isStructured } from './MetadataValue'
import { useLayers } from './layers'
import type { AssetFeatures } from './useAssetFeatures'
import { useAssetFeatures } from './useAssetFeatures'

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground'

/**
 * How many of a dataset's files the pane lists at once.
 *
 * The API's own ceiling. A point or an area rarely holds this many files of
 * one dataset; when it does, the pane says so and the search box narrows it.
 */
export const PANE_LIMIT = 200

/** Where the pane is looking: a clicked point or a drawn area, as the catalog takes them. */
export type PanePlace = { lon: number; lat: number } | { area: string }

/**
 * The right-hand pane: the datasets at a place, the files in one, one file's detail.
 *
 * Three levels, and the catalog answers each (docs/adr/016):
 * 1. the datasets holding anything here, searched by name;
 * 2. the files of the chosen dataset, searched by their metadata and chosen
 *    between by data type — which only means something once a dataset is
 *    chosen, so it is offered only here;
 * 3. the selected file's metadata.
 *
 * The page keys this by place, so a new point or area starts it afresh. A
 * place nothing covers shows no pane at all, as before (specs/map.md); an
 * asset arrived at from the Assets page shows its detail with no list behind.
 */
export function AssetPane({
  place,
  label,
  selected,
  selectedId,
  onSelect,
  onDraw,
}: {
  place: PanePlace | null
  /** What the pane lists, for assistive technology. */
  label: string
  selected: AssetDetail | null
  selectedId: string | null
  onSelect: (assetId: string | null) => void
  /** Load this asset's features onto the map. */
  onDraw: (assetId: string, name: string) => void
}) {
  // Held here rather than in the levels: going back from a dataset restores
  // the search that found it, and clearing a detail returns to the same list.
  const [datasetQuery, setDatasetQuery] = useState('')
  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [expanded, setExpanded] = useState(false)

  const datasets = useCatalogDatasetList(
    { ...place, ...(datasetQuery ? { q: datasetQuery } : {}) },
    { query: { enabled: place !== null, placeholderData: keepPreviousData } },
  )

  const answer = datasets.data
  const found = answer?.status === 200 ? answer.data.results : []
  // Nothing here at all — not "nothing matches what you typed" — shows no pane.
  const empty = answer?.status === 200 && found.length === 0 && datasetQuery === ''
  // A request that threw leaves no answer at all; it is still a failure to
  // show, with the search box kept, rather than a pane that vanishes mid-word.
  const failed = datasets.isError || (answer !== undefined && answer.status !== 200)

  if (!selected && (place === null || (answer === undefined && !failed) || empty)) return null

  return (
    <aside
      aria-label={selected ? 'Selected asset' : label}
      className={cn(
        'absolute bottom-4 right-4 top-4 z-10 flex flex-col overflow-y-auto rounded-lg border border-border bg-background/95 p-4 backdrop-blur transition-[width]',
        // Only the detail widens: its tables need the room, the lists do not.
        selected && expanded ? 'w-[min(48rem,calc(100%-2rem))]' : 'w-[22rem]',
      )}
    >
      {selected ? (
        <AssetDetailPanel
          detail={selected}
          expanded={expanded}
          onExpand={setExpanded}
          onClear={() => onSelect(null)}
          onDraw={onDraw}
        />
      ) : null}

      {/*
        Hidden rather than unmounted behind a detail, so its search, its
        data type and its scroll are where they were when the detail clears.
      */}
      {place !== null ? (
        <div hidden={selected !== null} className="flex min-h-0 flex-col gap-3">
          {dataset ? (
            <DatasetFiles
              key={dataset.dataset}
              place={place}
              dataset={dataset}
              selectedId={selectedId}
              onBack={() => setDataset(null)}
              onSelect={onSelect}
              onDraw={onDraw}
            />
          ) : (
            <DatasetList
              datasets={found}
              failed={failed}
              busy={datasets.isFetching}
              query={datasetQuery}
              onQuery={setDatasetQuery}
              onOpen={setDataset}
              onRetry={() => void datasets.refetch()}
            />
          )}
        </div>
      ) : null}
    </aside>
  )
}

/** Level 1: the datasets at this place, searched by their names. */
function DatasetList({
  datasets,
  failed,
  busy,
  query,
  onQuery,
  onOpen,
  onRetry,
}: {
  datasets: readonly Dataset[]
  failed: boolean
  busy: boolean
  query: string
  onQuery: (query: string) => void
  onOpen: (dataset: Dataset) => void
  onRetry: () => void
}) {
  return (
    <>
      <p className={MICRO}>Datasets · {datasets.length}</p>
      <Input
        type="search"
        value={query}
        onChange={(event) => onQuery(event.target.value)}
        placeholder="Search datasets…"
        aria-label="Search datasets"
        className="h-9"
      />

      {failed ? (
        <Failed what="The datasets" onRetry={onRetry} />
      ) : datasets.length === 0 ? (
        <p className="text-sm text-muted-foreground">No datasets here match “{query}”.</p>
      ) : (
        <ul className={cn('flex flex-col gap-1 transition-opacity', busy && 'opacity-60')}>
          {datasets.map((dataset) => (
            <li key={dataset.dataset}>
              <button
                type="button"
                onClick={() => onOpen(dataset)}
                aria-label={`Open ${dataset.label}`}
                className="w-full rounded-md border border-border px-3 py-2 text-left hover:border-map-footprint/60 focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
              >
                <span className="flex items-baseline gap-2">
                  <span className="min-w-0 flex-1 truncate text-sm">{dataset.label}</span>
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {dataset.count}
                  </span>
                </span>
                <span className={`${MICRO} mt-0.5 block truncate`}>
                  {dataset.data_type_counts
                    .map((type) => `${type.data_type} ${type.count}`)
                    .join(' · ')}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

/** Choosing every data type at once. Not a data type, so it can never collide with one. */
const ALL = ''

/**
 * Level 2: one dataset's files at this place.
 *
 * Keyed by dataset, so a different dataset starts with an empty search and
 * every type — what was typed about one dataset's files says nothing about
 * another's.
 */
function DatasetFiles({
  place,
  dataset,
  selectedId,
  onBack,
  onSelect,
  onDraw,
}: {
  place: PanePlace
  dataset: Dataset
  selectedId: string | null
  onBack: () => void
  onSelect: (assetId: string) => void
  onDraw: (assetId: string, name: string) => void
}) {
  const [query, setQuery] = useState('')
  const [type, setType] = useState(ALL)

  // Key order is the URL's order in the generated client.
  const files = useCatalogAssetList(
    {
      ...place,
      dataset: dataset.dataset,
      ...(query ? { q: query } : {}),
      ...(type !== ALL ? { data_type: [type] } : {}),
      sort: 'name',
      limit: PANE_LIMIT,
    },
    { query: { placeholderData: keepPreviousData } },
  )

  const answer = files.data
  const read = answer?.status === 200
  const failed = files.isError || (answer !== undefined && !read)
  const results = read ? answer.data.results : []
  const total = read ? answer.data.count : 0
  // The counts ignore the type already chosen, so the other choices stay
  // visible with their sizes (docs/adr/010).
  const types = read ? answer.data.data_type_counts : []

  return (
    <>
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={onBack}
          className={cn(
            MICRO,
            'flex items-center gap-1 rounded hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          )}
        >
          <ChevronLeft aria-hidden className="size-3.5" />
          Datasets
        </button>
      </div>
      <h2 className="text-sm font-medium leading-snug">{dataset.label}</h2>

      <Input
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search names and metadata…"
        aria-label={`Search ${dataset.label}`}
        className="h-9"
      />

      {/*
        The choices are the types the catalog reported for this dataset here,
        never a list held in the portal (specs/map.md). Shown even when there
        is one, because then it says what the dataset holds.
      */}
      {types.length > 0 ? (
        <Segmented
          label="Data type"
          mono
          value={type}
          onChange={setType}
          options={[
            { value: ALL, label: 'All' },
            ...types.map((item) => ({
              value: item.data_type,
              label: `${item.data_type} ${item.count}`,
            })),
          ]}
        />
      ) : null}

      {failed ? (
        <Failed what="The files" onRetry={() => void files.refetch()} />
      ) : !read ? (
        <div className="flex flex-col gap-1" aria-busy="true" aria-label="Loading files">
          {[0, 1, 2].map((row) => (
            <Skeleton key={row} className="h-12 w-full rounded-md" />
          ))}
        </div>
      ) : results.length === 0 ? (
        <p className="text-sm text-muted-foreground">No files here match these filters.</p>
      ) : (
        <div
          className={cn('flex flex-col gap-2 transition-opacity', files.isFetching && 'opacity-60')}
        >
          <AssetList assets={results} selectedId={selectedId} onSelect={onSelect} onDraw={onDraw} />
          {total > results.length ? (
            <p className={MICRO}>
              {results.length} of {total} · search to narrow
            </p>
          ) : null}
        </div>
      )}
    </>
  )
}

function Failed({ what, onRetry }: { what: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-start gap-2">
      <p className="text-sm text-muted-foreground">{what} could not be loaded.</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        Try again
      </Button>
    </div>
  )
}

/** The files of a dataset, each with its own control to draw it. */
function AssetList({
  assets,
  selectedId,
  onSelect,
  onDraw,
}: {
  assets: readonly AssetListItem[]
  selectedId: string | null
  onSelect: (assetId: string) => void
  /** Load this asset's features onto the map. */
  onDraw: (assetId: string, name: string) => void
}) {
  return (
    <ul className="flex flex-col gap-1">
      {assets.map((asset) => (
        <li key={asset.asset_id}>
          <AssetRow
            asset={asset}
            selected={asset.asset_id === selectedId}
            onSelect={() => onSelect(asset.asset_id)}
            onDraw={() => onDraw(asset.asset_id, asset.name)}
          />
        </li>
      ))}
    </ul>
  )
}

function AssetRow({
  asset,
  selected,
  onSelect,
  onDraw,
}: {
  asset: AssetListItem
  selected: boolean
  onSelect: () => void
  onDraw: () => void
}) {
  const { layers } = useLayers()
  const drawn = layers.find((layer) => layer.assetId === asset.asset_id)
  // Same asset, same area, same query key as the layer on the map: React Query
  // hands both this row and the map one answer, not two requests.
  const features = useAssetFeatures(asset.asset_id, Boolean(drawn?.visible))
  const loading = Boolean(drawn) && features.loading

  return (
    <div
      className={[
        'w-full rounded-md border px-3 py-2 text-sm',
        selected
          ? 'border-map-footprint bg-map-footprint/10'
          : 'border-border hover:border-map-footprint/60',
      ].join(' ')}
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onSelect}
          aria-current={selected ? 'true' : undefined}
          aria-label={`Details for ${asset.name}`}
          className="min-w-0 flex-1 text-left"
        >
          <span className="block truncate">{asset.name}</span>
          <span className={`${MICRO} mt-0.5 block`}>
            {[asset.data_type, asset.format].filter(Boolean).join(' · ')}
          </span>
        </button>

        {/*
          Drawing is its own control, not the row click: selecting shows
          metadata, drawing puts features on the map, and one must not force
          the other (docs/adr/008).
        */}
        <button
          type="button"
          onClick={onDraw}
          disabled={loading}
          aria-label={drawn ? `Redraw ${asset.name}` : `Draw ${asset.name}`}
          className="shrink-0 font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          {loading ? <Spinner /> : drawn ? <span aria-hidden>✓</span> : 'Draw'}
        </button>
      </div>

      {drawn ? <LayerNote features={features} className="mt-1" /> : null}
    </div>
  )
}

/**
 * What a drawn layer is showing, in a line.
 *
 * Silent when the layer is simply drawn and whole — the features on the map
 * already say that. It speaks when the answer is partial, and the advice is
 * the actual fix rather than a limit to live with: a smaller area is read in
 * full. Which smaller area depends on the scope. Zooming in shrinks a window,
 * but a drawn area is fixed, so zooming in does nothing to it — there the fix
 * is to draw a smaller one.
 */
function LayerNote({ features, className }: { features: AssetFeatures; className?: string }) {
  if (features.failed) {
    return (
      <p className={`${MICRO} ${className ?? ''}`}>
        {features.notFound ? 'No vector data to draw' : 'Could not read this layer'}
      </p>
    )
  }
  if (!features.truncated) return null
  return (
    <p className={`${MICRO} ${className ?? ''}`}>
      {features.count} features shown ·{' '}
      {features.scope === 'area' ? 'draw a smaller area for the rest' : 'zoom in for the rest'}
    </p>
  )
}

function Spinner() {
  return (
    <span
      role="status"
      aria-label="Loading"
      className="block size-3 animate-spin rounded-full border border-current border-t-transparent"
    />
  )
}

/**
 * One asset's metadata, and the controls that act on it.
 *
 * The key set is not fixed and differs by data type, so nothing here is
 * hardcoded per field — an unknown key renders like any other. What changes
 * with the size of the pane is decided by a value's shape instead: plain values
 * are always shown, and structured ones — a vector file's `columns`, a
 * raster's `bands`, `tags` and `stats` — only once the pane is expanded, where
 * each is a table rather than a line of JSON.
 */
export function AssetDetailPanel({
  detail,
  expanded,
  onExpand,
  onClear,
  onDraw,
}: {
  detail: AssetDetail
  expanded: boolean
  onExpand: (expanded: boolean) => void
  onClear: () => void
  /** Load this asset's features onto the map. */
  onDraw: (assetId: string, name: string) => void
}) {
  const entries = Object.entries(detail.metadata ?? {})
  const plain = entries.filter(([, value]) => !isStructured(value))
  const structured = entries.filter(([, value]) => isStructured(value))

  const { layers } = useLayers()
  const drawn = layers.find((layer) => layer.assetId === detail.asset_id)
  const features = useAssetFeatures(detail.asset_id, Boolean(drawn?.visible))
  const loading = Boolean(drawn) && features.loading

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <p className={MICRO}>{detail.data_type}</p>
        <span className="flex-1" />
        <Button
          variant="outline"
          size="sm"
          onClick={() => onExpand(!expanded)}
          aria-expanded={expanded}
          aria-label={expanded ? 'Collapse details' : 'Expand details'}
          title={expanded ? 'Collapse' : 'Expand'}
        >
          {expanded ? <Minimize2 aria-hidden /> : <Maximize2 aria-hidden />}
        </Button>
        {/*
          Drawing is offered here for the same reason it is offered in the row
          above: an asset reached from the Assets page never passes through
          that list, so without this the only way to draw it would be to find
          it again by clicking the map.

          Offered whatever the data type is. Only vector assets have features
          to draw, but which types those are belongs to the knowledge base and
          not to this file (specs/map.md) — an asset with nothing to draw says
          so when asked, exactly as it does from the list.
        */}
        <Button
          variant="outline"
          size="sm"
          onClick={() => onDraw(detail.asset_id, detail.name)}
          disabled={loading}
        >
          {loading ? <Spinner /> : drawn ? 'Redraw' : 'Draw'}
        </Button>
        <Button variant="outline" size="sm" onClick={onClear}>
          Clear
        </Button>
      </div>

      <h2 className="break-words text-sm font-medium leading-snug">{detail.name}</h2>

      {drawn ? <LayerNote features={features} /> : null}

      <dl className="flex flex-col divide-y divide-border border-y border-border">
        {plain.map(([key, value]) => (
          <div key={key} className="grid grid-cols-[minmax(0,9rem)_1fr] gap-3 py-2">
            <dt className={MICRO}>{key}</dt>
            <dd className="min-w-0 break-words font-mono text-[12px]">{formatScalar(value)}</dd>
          </div>
        ))}
      </dl>

      {structured.length > 0 && !expanded ? (
        <button
          type="button"
          onClick={() => onExpand(true)}
          className="self-start rounded text-sm text-primary hover:underline focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          {structured.length} more {structured.length === 1 ? 'field' : 'fields'} · Expand
        </button>
      ) : null}

      {expanded
        ? structured.map(([key, value]) => (
            <section key={key} aria-label={key} className="flex flex-col gap-1.5">
              <h3 className={MICRO}>{key}</h3>
              <MetadataValue value={value} />
            </section>
          ))
        : null}
    </div>
  )
}
