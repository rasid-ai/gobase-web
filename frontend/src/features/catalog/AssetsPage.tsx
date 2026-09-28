import { keepPreviousData } from '@tanstack/react-query'
import { ChevronLeft } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { useCatalogDatasetList } from '@/api/generated/catalog/catalog'
import type { AssetListItem, CatalogAssetListSort, Dataset } from '@/api/generated/model'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Pagination } from '@/components/ui/pagination'
import { Skeleton } from '@/components/ui/skeleton'
import { serializeBbox } from '@/features/places/bbox'
import { useAreaParam } from '@/features/places/useAreaParam'
import { cn } from '@/lib/utils'

import { AssetFilters, type BrowseMode, ingestedAfter } from './AssetFilters'
import { formatBbox, formatBytes, formatIngested } from './formatAsset'
import { PAGE_SIZE, useAssetPage } from './useAssetPage'

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground'

const SORTS: { value: CatalogAssetListSort; label: string }[] = [
  { value: '-ingested_at', label: 'Newest ingestion' },
  { value: 'ingested_at', label: 'Oldest ingestion' },
  { value: 'name', label: 'Name A–Z' },
  { value: '-name', label: 'Name Z–A' },
  { value: 'data_type', label: 'Data type' },
]

/**
 * Assets — everything the knowledge base holds, browsable (specs/assets.md).
 *
 * The map answers "what covers this point". This answers "what do we have",
 * which is a different question and so a different page rather than another
 * panel on the map (docs/adr/010).
 *
 * Two ways to browse (docs/adr/016). By dataset: the datasets first, searched
 * by name, then the assets of the one you open, searched by their metadata and
 * filtered by data type. Or every asset at once, searched by metadata — the
 * dataset's name included, so a dataset can be found from here too.
 */
export function AssetsPage() {
  const [mode, setMode] = useState<BrowseMode>('datasets')
  const [dataset, setDataset] = useState<Dataset | null>(null)
  // Two searches, because they search two different things: dataset names,
  // and the metadata of assets. Each keeps its own text, so coming back out
  // of a dataset finds the dataset search as it was left.
  const [datasetSearch, setDatasetSearch] = useState('')
  const [search, setSearch] = useState('')
  const [types, setTypes] = useState<string[]>([])
  const [window, setWindow] = useState('any')
  const [sort, setSort] = useState<CatalogAssetListSort>('-ingested_at')
  const [page, setPage] = useState(1)
  const scroller = useRef<HTMLDivElement>(null)
  // The area is the one filter that lives in the URL, because it is the one
  // that crosses to the map and back (docs/adr/011). The mode and the open
  // dataset cross no page, so by the same rule they are not in it.
  const [area, setArea] = useAreaParam()

  /** The datasets are on screen, rather than assets. */
  const listingDatasets = mode === 'datasets' && dataset === null

  // Position matters in both: the generated client builds the query string in
  // each object's own order, and the tests key on the whole URL.
  const scope = {
    ...(ingestedAfter(window) ? { ingested_after: ingestedAfter(window) } : {}),
    ...(area ? { bbox: serializeBbox(area.bbox) } : {}),
  }

  const datasets = useCatalogDatasetList(
    { ...(datasetSearch !== '' ? { q: datasetSearch } : {}), ...scope },
    { query: { enabled: listingDatasets, placeholderData: keepPreviousData } },
  )

  const assets = useAssetPage(
    {
      ...(search !== '' ? { q: search } : {}),
      ...(types.length > 0 ? { data_type: types } : {}),
      ...(dataset ? { dataset: dataset.dataset } : {}),
      ...scope,
      sort,
    },
    page,
    !listingDatasets,
  )

  const filtered = listingDatasets
    ? datasetSearch !== '' || window !== 'any' || area !== null
    : search !== '' || types.length > 0 || window !== 'any' || area !== null

  const answer = assets.data
  const read = answer?.status === 200
  const results = read ? answer.data.results : []
  const total = read ? answer.data.count : 0
  const dataTypes = read ? answer.data.data_type_counts : []
  const pageCount = Math.ceil(total / PAGE_SIZE)

  const datasetAnswer = datasets.data
  const datasetList = datasetAnswer?.status === 200 ? datasetAnswer.data.results : []

  // A refetch can shrink the catalog under a page that no longer exists, and
  // the empty grid there would read as "nothing matches", which is not what
  // happened. Set during render, not in an effect: React throws this render
  // away and redoes it with the corrected page, so the dead one never paints.
  if (pageCount > 0 && page > pageCount) setPage(pageCount)

  const goToPage = (next: number) => {
    setPage(next)
    // The control sits at the foot of a long grid, so without this the new
    // page opens already scrolled past its first rows.
    if (scroller.current) scroller.current.scrollTop = 0
  }

  // Changing what is asked for goes back to page one: page 4 of the old list
  // has nothing to do with page 4 of the new one.
  const applyFilter = (change: () => void) => {
    change()
    goToPage(1)
  }

  const clear = () => {
    if (listingDatasets) {
      setDatasetSearch('')
    } else {
      setSearch('')
      setTypes([])
    }
    setWindow('any')
    setArea(null)
  }

  // Entering or leaving a dataset starts its asset search afresh: what was
  // typed about one dataset's assets says nothing about another's. The place
  // and the window stay, because they describe where and when, not what.
  const openDataset = (next: Dataset | null) =>
    applyFilter(() => {
      setDataset(next)
      setSearch('')
      setTypes([])
    })

  const changeMode = (next: BrowseMode) =>
    applyFilter(() => {
      setMode(next)
      setDataset(null)
      setSearch('')
      setDatasetSearch('')
      setTypes([])
    })

  const toggleType = (dataType: string) =>
    setTypes((current) =>
      current.includes(dataType)
        ? current.filter((item) => item !== dataType)
        : [...current, dataType],
    )

  return (
    <div className="flex h-full min-h-0">
      <AssetFilters
        mode={mode}
        onMode={changeMode}
        search={listingDatasets ? datasetSearch : search}
        onSearch={(next) =>
          applyFilter(() => (listingDatasets ? setDatasetSearch(next) : setSearch(next)))
        }
        searchLabel={
          listingDatasets
            ? 'Search datasets'
            : dataset
              ? `Search ${dataset.label}`
              : 'Search assets'
        }
        placeholder={
          // Short enough for the 240px rail: longer ones were cut off mid-word.
          listingDatasets ? 'Dataset name or place…' : 'Metadata or place…'
        }
        // Choosing a data type means nothing among datasets, which each hold
        // several; it is offered once there are assets to choose between.
        dataTypes={listingDatasets ? [] : dataTypes}
        selectedTypes={types}
        onToggleType={(dataType) => applyFilter(() => toggleType(dataType))}
        window={window}
        onWindow={(next) => applyFilter(() => setWindow(next))}
        area={area}
        onArea={(next) => applyFilter(() => setArea(next))}
        onClear={() => applyFilter(clear)}
        dirty={filtered}
      />

      <div ref={scroller} className="min-w-0 flex-1 overflow-y-auto px-8 py-7">
        {dataset ? (
          <button
            type="button"
            onClick={() => openDataset(null)}
            className="mb-2 flex items-center gap-1 rounded text-sm text-primary hover:underline focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
          >
            <ChevronLeft aria-hidden className="size-4" />
            All datasets
          </button>
        ) : null}

        <header className="flex flex-wrap items-baseline gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">
            {/* The page keeps its name in both modes; the count says what is listed. */}
            {dataset ? dataset.label : 'Assets'}
          </h1>
          {listingDatasets
            ? datasetAnswer?.status === 200 && (
                <p className="text-sm text-muted-foreground">
                  {datasetList.length} {datasetList.length === 1 ? 'dataset' : 'datasets'}
                </p>
              )
            : read && <p className="text-sm text-muted-foreground">{countLabel(page, total)}</p>}
          <span className="flex-1" />
          {/* Datasets are listed by name; only assets have orderings to choose. */}
          {listingDatasets ? null : (
            <label className="flex items-center gap-2">
              <span className={MICRO}>Sort</span>
              <select
                value={sort}
                onChange={(event) =>
                  applyFilter(() => setSort(event.target.value as CatalogAssetListSort))
                }
                className="h-9 rounded-md border border-input bg-card px-2.5 text-sm text-foreground focus-visible:border-ring focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
              >
                {SORTS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          )}
        </header>

        {listingDatasets ? (
          <div
            className={cn('mt-6 transition-opacity', datasets.isFetching && 'opacity-60')}
            aria-busy={datasets.isFetching}
          >
            <DatasetsBody
              pending={datasets.isPending}
              status={datasetAnswer?.status}
              datasets={datasetList}
              filtered={filtered}
              onOpen={openDataset}
              onRetry={() => void datasets.refetch()}
            />
          </div>
        ) : (
          <>
            {/*
              The page being replaced stays legible but dimmed while the next
              one is read, so a slow step is visible without the grid
              disappearing.
            */}
            <div
              className={cn('mt-6 transition-opacity', assets.isFetching && 'opacity-60')}
              aria-busy={assets.isFetching}
            >
              <AssetsBody
                pending={assets.isPending}
                status={answer?.status}
                results={results}
                filtered={filtered}
                inDataset={dataset !== null}
                onRetry={() => void assets.refetch()}
              />
            </div>

            <Pagination className="mt-6" page={page} pageCount={pageCount} onPage={goToPage} />
          </>
        )}
      </div>
    </div>
  )
}

/** How much of the catalog is on screen, and how much there is. */
function countLabel(page: number, total: number) {
  if (total <= PAGE_SIZE) return `${total} ${total === 1 ? 'asset' : 'assets'}`
  const from = (page - 1) * PAGE_SIZE + 1
  return `${from}–${Math.min(page * PAGE_SIZE, total)} of ${total} assets`
}

function Loading({ label }: { label: string }) {
  return (
    <div className={GRID} aria-busy="true" aria-label={label}>
      {[0, 1, 2, 3, 4, 5].map((card) => (
        <Skeleton key={card} className="h-40 w-full rounded-lg" />
      ))}
    </div>
  )
}

function Unreadable({ onRetry }: { onRetry: () => void }) {
  return (
    <Alert className="flex flex-wrap items-center justify-between gap-3">
      <span>The catalog could not be loaded.</span>
      <Button variant="outline" size="sm" onClick={onRetry}>
        Try again
      </Button>
    </Alert>
  )
}

function Empty({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded-lg border border-border px-5 py-12 text-center">
      <p className="text-sm font-medium">{title}</p>
      <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
    </div>
  )
}

const NOTHING_INGESTED =
  'Nothing has been ingested yet. Assets appear here once the pipeline has run.'

function DatasetsBody({
  pending,
  status,
  datasets,
  filtered,
  onOpen,
  onRetry,
}: {
  pending: boolean
  status: number | undefined
  datasets: readonly Dataset[]
  filtered: boolean
  onOpen: (dataset: Dataset) => void
  onRetry: () => void
}) {
  if (pending) return <Loading label="Loading datasets" />
  if (status !== 200) return <Unreadable onRetry={onRetry} />
  if (datasets.length === 0) {
    return filtered ? (
      <Empty
        title="No datasets match these filters"
        detail="Clear the filters to see every dataset."
      />
    ) : (
      <Empty title="The catalog is empty" detail={NOTHING_INGESTED} />
    )
  }

  return (
    <ul className={GRID}>
      {datasets.map((dataset) => (
        <li key={dataset.dataset}>
          <DatasetCard dataset={dataset} onOpen={() => onOpen(dataset)} />
        </li>
      ))}
    </ul>
  )
}

/**
 * One dataset: what it is called, what it holds, and the way in.
 *
 * Built like an asset card so the two grids read as one family: data chrome
 * across a divided top, the name, and a divided foot with the action.
 */
function DatasetCard({ dataset, onOpen }: { dataset: Dataset; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`Open ${dataset.label}`}
      className={cn(
        'flex h-full w-full flex-col overflow-hidden rounded-lg border border-border bg-card text-left hover:border-primary/60',
        'focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50',
      )}
    >
      {/*
        Each type in the catalog's own words, styled like every other — the
        page holds no list of types (specs/map.md).
      */}
      <span className="flex w-full flex-wrap items-center gap-x-2 border-b border-border px-3.5 py-2.5">
        {dataset.data_type_counts.map((type) => (
          <span key={type.data_type} className={MICRO}>
            {type.data_type} {type.count}
          </span>
        ))}
      </span>

      <span className="flex w-full flex-1 flex-col gap-1.5 px-3.5 pb-3 pt-3">
        <span className="text-sm font-medium leading-snug">{dataset.label}</span>
        <span className="truncate font-mono text-[11px] text-muted-foreground">
          {dataset.dataset}
        </span>

        <span className="mt-auto flex items-center gap-2 border-t border-border pt-2.5">
          <span className="text-xs text-muted-foreground">
            {dataset.count} {dataset.count === 1 ? 'asset' : 'assets'}
          </span>
          <span className="flex-1" />
          <span className="text-xs text-primary">Open</span>
        </span>
      </span>
    </button>
  )
}

function AssetsBody({
  pending,
  status,
  results,
  filtered,
  inDataset,
  onRetry,
}: {
  pending: boolean
  status: number | undefined
  results: readonly AssetListItem[]
  filtered: boolean
  /** Inside one dataset, where every card would name the same dataset. */
  inDataset: boolean
  onRetry: () => void
}) {
  if (pending) return <Loading label="Loading assets" />
  if (status !== 200) return <Unreadable onRetry={onRetry} />
  if (results.length === 0) {
    if (filtered) {
      return (
        <Empty
          title={
            inDataset
              ? 'No assets in this dataset match these filters'
              : 'No assets match these filters'
          }
          detail={
            inDataset
              ? 'Clear the filters to see all of it.'
              : 'Clear the filters to see every asset.'
          }
        />
      )
    }
    return <Empty title="The catalog is empty" detail={NOTHING_INGESTED} />
  }

  return (
    <ul className={GRID}>
      {results.map((asset) => (
        <li key={asset.asset_id}>
          <AssetCard asset={asset} showDataset={!inDataset} />
        </li>
      ))}
    </ul>
  )
}

const GRID = 'grid grid-cols-1 gap-3.5 md:grid-cols-2 xl:grid-cols-3'

function AssetCard({ asset, showDataset }: { asset: AssetListItem; showDataset: boolean }) {
  const bbox = formatBbox(asset.bbox)

  return (
    <article className="flex h-full flex-col overflow-hidden rounded-lg border border-border bg-card">
      {/*
        The data type is shown as the catalog wrote it and styled like every
        other type. Nothing here maps a type to a colour or a label — that list
        belongs to the knowledge base and it grows (specs/map.md).
      */}
      <div className="flex items-center gap-2 border-b border-border px-3.5 py-2.5">
        <span className={MICRO}>{asset.data_type}</span>
        <span className="flex-1" />
        {asset.format && <span className={MICRO}>{asset.format}</span>}
      </div>

      <div className="flex flex-1 flex-col gap-1.5 px-3.5 pb-3 pt-3">
        {showDataset && asset.dataset_label ? (
          <p className="text-xs text-muted-foreground">{asset.dataset_label}</p>
        ) : null}
        {/* Some names have no break in them at all: lulc_2019_bbox_34.88257_… */}
        <p className="text-sm font-medium leading-snug wrap-anywhere">{asset.name}</p>
        <p className="truncate font-mono text-[11px] text-foreground" title={asset.asset_id}>
          {asset.asset_id}
        </p>
        <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          {asset.topic_path && <span>{asset.topic_path}</span>}
          {asset.topic_path && <span className="text-border">·</span>}
          <span>{formatBytes(asset.bytes)}</span>
        </p>

        <div className="mt-auto flex items-center gap-2 border-t border-border pt-2.5">
          <span className="font-mono text-[11px] tracking-[0.04em] text-muted-foreground">
            {formatIngested(asset.ingested_at)}
          </span>
          <span className="flex-1" />
          {/*
            An asset with no coverage has nowhere to go, so the link is not
            offered rather than offered and broken.
          */}
          {asset.bbox && (
            <Link
              to={`/map?asset=${asset.asset_id}`}
              title={bbox ?? undefined}
              className={cn(
                'rounded text-xs text-primary hover:underline',
                'focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50',
              )}
            >
              Locate on map
            </Link>
          )}
        </div>
      </div>
    </article>
  )
}
