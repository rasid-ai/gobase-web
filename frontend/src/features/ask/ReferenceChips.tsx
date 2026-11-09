import { useMapAssetDetail } from '@/api/generated/map/map'
import type { ChatReference } from '@/api/generated/model'
import { Skeleton } from '@/components/ui/skeleton'
import { useLayers } from '@/features/workspace/layers'
import { cn } from '@/lib/utils'

import { type GroupedReferences, layerScope } from './references'

const MICRO = 'font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground'

const CHIP =
  'inline-flex max-w-full items-center gap-2 rounded-md border border-border bg-background px-3 py-1.5 text-left text-sm transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'

/**
 * The asset's name and data type, for a chip.
 *
 * A reference carries only an id (docs/adr/024), so the chip reads the
 * asset's detail — the same request the map's panel makes when the chip is
 * clicked, so that click is then answered from the cache. An id the catalog
 * does not have shows no chip: there is nothing true to say about it.
 */
function useAssetLabel(assetId: string) {
  const detail = useMapAssetDetail(assetId)
  const asset = detail.data?.status === 200 ? detail.data.data : null
  const missing = detail.isError || (detail.data !== undefined && detail.data.status !== 200)
  return { asset, loading: !asset && !missing }
}

function ChipSkeleton() {
  return <Skeleton className="h-8 w-44" />
}

/** A cited asset, with its page for a passage. Selecting it shows its metadata. */
export function CitationChip({
  assetId,
  page,
  onSelect,
}: {
  assetId: string
  page: number | null
  onSelect: (assetId: string) => void
}) {
  const { asset, loading } = useAssetLabel(assetId)
  if (loading) return <ChipSkeleton />
  if (!asset) return null

  return (
    <button type="button" onClick={() => onSelect(assetId)} className={CHIP} title={asset.name}>
      <span className="truncate">{asset.name}</span>
      <span className={cn(MICRO, 'shrink-0')}>
        {asset.data_type}
        {page !== null ? ` p. ${page}` : ''}
      </span>
    </button>
  )
}

/**
 * A layer the answer put on the map, with the count it gave.
 *
 * Clicking shows or hides it. A layer from a reopened session is not on the
 * map yet, so the first click draws it. Drawing goes through the same layer
 * store as the asset panel's Draw (docs/adr/008), so the layer follows the
 * drawn area or the view as any other does.
 */
export function LayerChip({ reference }: { reference: ChatReference }) {
  const assetId = reference.asset_id!
  const { asset, loading } = useAssetLabel(assetId)
  const { layers, add, toggle } = useLayers()
  if (loading) return <ChipSkeleton />
  if (!asset) return null

  const layer = layers.find((one) => one.assetId === assetId)
  const shown = layer?.visible ?? false
  const label = `${asset.name} · ${layerScope(reference)}`

  return (
    <button
      type="button"
      aria-pressed={shown}
      onClick={() => (layer ? toggle(assetId) : add({ assetId, label }))}
      className={cn(CHIP, !shown && 'border-dashed text-muted-foreground')}
      title={shown ? `Hide ${label}` : `Show ${label}`}
    >
      <span
        aria-hidden="true"
        className={cn(
          'size-3 shrink-0 rounded-[2px] border border-map-result',
          shown && 'bg-map-result',
        )}
      />
      <span className="truncate">{label}</span>
      {reference.total !== null && reference.total !== undefined ? (
        <span className={cn(MICRO, 'shrink-0')}>{reference.total.toLocaleString()}</span>
      ) : null}
    </button>
  )
}

/** The citations under an answer, and "Framed to the answer" when it moved the map. */
export function Citations({
  grouped,
  onSelect,
  onFrame,
}: {
  grouped: GroupedReferences
  onSelect: (assetId: string) => void
  onFrame: (bbox: [number, number, number, number]) => void
}) {
  const { citations, frame } = grouped
  if (citations.length === 0 && !frame) return null

  return (
    <div className="flex flex-col items-start gap-2">
      {frame ? (
        <button
          type="button"
          onClick={() => onFrame(frame)}
          className="text-sm text-muted-foreground hover:text-foreground hover:underline"
          title="Frame the map on the answer again"
        >
          Framed to the answer
        </button>
      ) : null}
      {citations.map((citation) => (
        <CitationChip
          key={`${citation.assetId}:${citation.page ?? ''}`}
          assetId={citation.assetId}
          page={citation.page}
          onSelect={onSelect}
        />
      ))}
    </div>
  )
}

/** What the answer hands over: assets to open, and layers on the map. */
export function OutputBox({
  grouped,
  onSelect,
}: {
  grouped: GroupedReferences
  onSelect: (assetId: string) => void
}) {
  const { assets, layers } = grouped
  if (assets.length === 0 && layers.length === 0) return null

  return (
    <section
      aria-label="What the answer found"
      className="flex flex-col gap-3 rounded-lg border border-border p-4"
    >
      {assets.length > 0 ? (
        <div className="flex flex-col items-start gap-2">
          <h3 className={MICRO}>Assets · {assets.length}</h3>
          {assets.map((assetId) => (
            <CitationChip key={assetId} assetId={assetId} page={null} onSelect={onSelect} />
          ))}
        </div>
      ) : null}
      {layers.length > 0 ? (
        <div className="flex flex-col items-start gap-2">
          <h3 className={MICRO}>On the map · {layers.length}</h3>
          {layers.map((reference) => (
            <LayerChip key={reference.asset_id} reference={reference} />
          ))}
        </div>
      ) : null}
    </section>
  )
}
