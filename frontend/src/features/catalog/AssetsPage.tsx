import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import type { AssetListItem, CatalogAssetListSort } from '@/api/generated/model'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Pagination } from '@/components/ui/pagination'
import { Skeleton } from '@/components/ui/skeleton'
import { serializeBbox } from '@/features/places/bbox'
import { useAreaParam } from '@/features/places/useAreaParam'
import { cn } from '@/lib/utils'

import { AssetFilters, ingestedAfter } from './AssetFilters'
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
 */
export function AssetsPage() {
  const [search, setSearch] = useState('')
  const [types, setTypes] = useState<string[]>([])
  const [window, setWindow] = useState('any')
  const [sort, setSort] = useState<CatalogAssetListSort>('-ingested_at')
  const [page, setPage] = useState(1)
  const scroller = useRef<HTMLDivElement>(null)
  // The area is the one filter that lives in the URL, because it is the one
  // that crosses to the map and back (docs/adr/011).
  const [area, setArea] = useAreaParam()

  const filtered = search !== '' || types.length > 0 || window !== 'any' || area !== null

  const assets = useAssetPage(
    {
      ...(search !== '' ? { q: search } : {}),
      ...(types.length > 0 ? { data_type: types } : {}),
      ...(ingestedAfter(window) ? { ingested_after: ingestedAfter(window) } : {}),
      // Position matters: the generated client builds the query string in
      // this object's own order, and the tests key on the whole URL.
      ...(area ? { bbox: serializeBbox(area.bbox) } : {}),
      sort,
    },
    page,
  )

  const answer = assets.data
  const read = answer?.status === 200
  const results = read ? answer.data.results : []
  const total = read ? answer.data.count : 0
  const dataTypes = read ? answer.data.data_type_counts : []
  const pageCount = Math.ceil(total / PAGE_SIZE)

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
    setSearch('')
    setTypes([])
    setWindow('any')
    setArea(null)
  }

  const toggleType = (dataType: string) =>
    setTypes((current) =>
      current.includes(dataType)
        ? current.filter((item) => item !== dataType)
        : [...current, dataType],
    )

  return (
    <div className="flex h-full min-h-0">
      <AssetFilters
        search={search}
        onSearch={(next) => applyFilter(() => setSearch(next))}
        dataTypes={dataTypes}
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
        <header className="flex flex-wrap items-baseline gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">Assets</h1>
          {read && <p className="text-sm text-muted-foreground">{countLabel(page, total)}</p>}
          <span className="flex-1" />
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
        </header>

        {/*
          The page being replaced stays legible but dimmed while the next one
          is read, so a slow step is visible without the grid disappearing.
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
            onRetry={() => void assets.refetch()}
          />
        </div>

        <Pagination className="mt-6" page={page} pageCount={pageCount} onPage={goToPage} />
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

function AssetsBody({
  pending,
  status,
  results,
  filtered,
  onRetry,
}: {
  pending: boolean
  status: number | undefined
  results: readonly AssetListItem[]
  filtered: boolean
  onRetry: () => void
}) {
  if (pending) {
    return (
      <div className={GRID} aria-busy="true" aria-label="Loading assets">
        {[0, 1, 2, 3, 4, 5].map((card) => (
          <Skeleton key={card} className="h-40 w-full rounded-lg" />
        ))}
      </div>
    )
  }

  if (status !== 200) {
    return (
      <Alert className="flex flex-wrap items-center justify-between gap-3">
        <span>The catalog could not be loaded.</span>
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      </Alert>
    )
  }

  if (results.length === 0) {
    return (
      <div className="rounded-lg border border-border px-5 py-12 text-center">
        <p className="text-sm font-medium">
          {filtered ? 'No assets match these filters' : 'The catalog is empty'}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          {filtered
            ? 'Clear the filters to see every asset.'
            : 'Nothing has been ingested yet. Assets appear here once the pipeline has run.'}
        </p>
      </div>
    )
  }

  return (
    <ul className={GRID}>
      {results.map((asset) => (
        <li key={asset.asset_id}>
          <AssetCard asset={asset} />
        </li>
      ))}
    </ul>
  )
}

const GRID = 'grid grid-cols-1 gap-3.5 md:grid-cols-2 xl:grid-cols-3'

function AssetCard({ asset }: { asset: AssetListItem }) {
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
        <p className="text-sm font-medium leading-snug">{asset.name}</p>
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
