import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import type { AssetListItem } from '@/api/generated/model'
import { cn } from '@/lib/utils'

import { OpenPdf } from './OpenPdf'
import { formatBbox, formatBytes, formatIngested, formatPages } from './formatAsset'

export const MICRO = 'font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground'

/** A card's action: a text link in the foot, whether it is a link or a button. */
export const ACTION = cn(
  'rounded text-xs text-primary hover:underline',
  'focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50',
)

export const GRID = 'grid grid-cols-1 gap-3.5 md:grid-cols-2 xl:grid-cols-3'

/**
 * One asset as the catalog lists it (specs/assets.md).
 *
 * Shared by the browse grid and the deep search results, which nest a
 * document's matching passages under its name through `children`
 * (docs/adr/020), so the two grids read as one family.
 */
export function AssetCard({
  asset,
  showDataset,
  children,
}: {
  asset: AssetListItem
  showDataset: boolean
  children?: ReactNode
}) {
  const bbox = formatBbox(asset.bbox)
  // A document's name is its PDF's; the title the parser read is a second
  // line, when there is one and it says something the name does not. Its
  // size is always 0 in the catalog, so the page count stands in.
  const title =
    asset.document?.title && asset.document.title !== asset.name ? asset.document.title : null
  const size =
    asset.document && asset.document.pages != null
      ? formatPages(asset.document.pages)
      : formatBytes(asset.bytes)

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
        {title && (
          <p className="text-xs leading-snug text-muted-foreground wrap-anywhere">{title}</p>
        )}
        <p className="truncate font-mono text-[11px] text-foreground" title={asset.asset_id}>
          {asset.asset_id}
        </p>
        <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          {asset.topic_path && <span>{asset.topic_path}</span>}
          {asset.topic_path && <span className="text-border">·</span>}
          <span>{size}</span>
        </p>
      </div>

      {/* Edge to edge, between the body and the foot: a list of rows, not a paragraph. */}
      {children}

      <div className="mt-auto flex items-center gap-2 border-t border-border px-3.5 py-2.5">
        <span className="font-mono text-[11px] tracking-[0.04em] text-muted-foreground">
          {formatIngested(asset.ingested_at)}
        </span>
        <span className="flex-1" />
        {/*
          Each action is offered only where it can go: no PDF button for a
          document whose PDF the catalog does not record, and no map link
          for an asset with no coverage. Offered and broken is worse.
        */}
        {asset.document?.pdf && (
          <OpenPdf assetId={asset.asset_id} className={cn(ACTION, 'disabled:opacity-60')} />
        )}
        {asset.bbox && (
          <Link to={`/map?asset=${asset.asset_id}`} title={bbox ?? undefined} className={ACTION}>
            Locate on map
          </Link>
        )}
      </div>
    </article>
  )
}
